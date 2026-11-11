import csv
import io
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from flask import current_app
from app.database.connection import close_db, get_db, migrate_database_file
from app.repositories import auth_repository, challenge_repository, statistics_repository, task_repository
from app.utils.time_utils import utc_now_iso
from app.utils.validation import ValidationError


SENSITIVE_SETTING_KEYS = {
    "auth_password_hash",
    "auth_failed_attempts",
    "auth_locked_until",
}
REQUIRED_RESTORE_TABLES = {
    "app_settings",
    "centered_tasks",
    "task_items",
    "task_progress_entries",
    "challenges",
    "challenge_cycles",
    "urge_events",
}
MAX_RESTORE_BYTES = 50 * 1024 * 1024


def create_sqlite_backup_bytes():
    db_path = current_app.config["DATABASE_PATH"]
    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    dst_conn = None
    src_conn = None
    close_src = False
    try:
        if db_path == ":memory:":
            src_conn = get_db()
        else:
            src_conn = sqlite3.connect(db_path, check_same_thread=False)
            close_src = True
        dst_conn = sqlite3.connect(temp_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        dst_conn = None
        if close_src:
            src_conn.close()
            src_conn = None
        with open(temp_path, "rb") as fh:
            data = fh.read()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return data, "focus_control_backup_%s.db" % stamp
    finally:
        if dst_conn is not None:
            dst_conn.close()
        if close_src and src_conn is not None:
            src_conn.close()
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def restore_sqlite_backup(file_storage):
    if not file_storage or not file_storage.filename:
        raise ValidationError("Please select a SQLite backup (.db) file to restore.")

    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in (".db", ".sqlite", ".sqlite3"):
        raise ValidationError("Backup file must have a .db, .sqlite, or .sqlite3 extension.")

    raw_bytes = file_storage.read(MAX_RESTORE_BYTES + 1)
    if not raw_bytes:
        raise ValidationError("Uploaded backup file is empty.")
    if len(raw_bytes) > MAX_RESTORE_BYTES:
        raise ValidationError("Backup file exceeds the 50 MB limit.")
    if not raw_bytes.startswith(b"SQLite format 3\x00"):
        raise ValidationError("Uploaded file is not a valid SQLite 3 database.")

    fd, temp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    val_conn = None
    try:
        with open(temp_path, "wb") as fh:
            fh.write(raw_bytes)

        try:
            val_conn = sqlite3.connect(temp_path)
            val_conn.row_factory = sqlite3.Row
            integrity = val_conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                raise ValidationError("SQLite integrity check failed for the uploaded backup.")

            table_rows = val_conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            existing_tables = {r["name"] for r in table_rows}
            missing = sorted(REQUIRED_RESTORE_TABLES - existing_tables)
            if missing:
                raise ValidationError(
                    "Backup is missing required Focus & Control tables: %s." % ", ".join(missing)
                )
        except sqlite3.DatabaseError as exc:
            raise ValidationError("Corrupted or unreadable SQLite database: %s" % str(exc))
        finally:
            if val_conn is not None:
                val_conn.close()
                val_conn = None

        db_path = current_app.config["DATABASE_PATH"]
        if db_path != ":memory:":
            backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
            os.makedirs(backup_dir, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            pre_restore_path = os.path.join(backup_dir, "pre_restore_%s.db" % stamp)
            if os.path.exists(db_path):
                close_db()
                src = sqlite3.connect(db_path)
                dst = sqlite3.connect(pre_restore_path)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
                    src.close()

            close_db()
            for suffix in ("-wal", "-shm"):
                sidecar = db_path + suffix
                if os.path.exists(sidecar):
                    try:
                        os.remove(sidecar)
                    except OSError:
                        pass
            shutil.copyfile(temp_path, db_path)
            migrate_database_file(db_path)
        else:
            # In-memory test target: restore via sqlite backup API onto active connection
            src = sqlite3.connect(temp_path)
            try:
                dst = get_db()
                src.backup(dst)
                from app.database.connection import run_migrations
                run_migrations(dst)
            finally:
                src.close()

        lock_ver = int(auth_repository.get_setting("auth_lock_version", "1") or 1)
        now_utc = utc_now_iso()
        from app.database.transaction import transaction
        with transaction() as conn:
            auth_repository.insert_activity_log(
                "settings",
                "database_restored",
                "system",
                None,
                "Restored SQLite database from '%s'" % file_storage.filename,
                now_utc,
                conn=conn,
            )
        return lock_ver
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def export_json_bytes(include_demo=True):
    db = get_db()
    all_settings = {
        k: v for k, v in auth_repository.get_all_settings(conn=db).items()
        if k not in SENSITIVE_SETTING_KEYS
    }

    demo_ct_filter = "" if include_demo else " AND COALESCE(is_demo, 0) = 0"

    centered_tasks = [
        dict(r)
        for r in db.execute(
            "SELECT * FROM centered_tasks WHERE COALESCE(is_deleted, 0) = 0%s ORDER BY id ASC" % demo_ct_filter
        ).fetchall()
    ]
    task_items = [
        dict(r)
        for r in db.execute(
            """
            SELECT ti.*
            FROM task_items ti
            JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
            WHERE COALESCE(ti.is_deleted, 0) = 0
              AND COALESCE(ct.is_deleted, 0) = 0
            """ + ("" if include_demo else " AND ct.is_demo = 0") + " ORDER BY ti.id ASC"
        ).fetchall()
    ]
    progress_entries = statistics_repository.list_progress_entries_in_range(include_demo=include_demo, conn=db)
    challenges = challenge_repository.list_challenges(include_archived=True, conn=db)
    if not include_demo:
        challenges = [c for c in challenges if not c.get("is_demo")]
    urge_events = statistics_repository.list_urge_events_in_range(include_demo=include_demo, conn=db)
    reflections = statistics_repository.list_reflections_in_range(include_demo=include_demo, conn=db)
    daily_records = statistics_repository.list_daily_records_in_range(include_demo=include_demo, conn=db)
    comments = statistics_repository.list_comments_in_range(include_demo=include_demo, conn=db)

    payload = {
        "exported_at_utc": utc_now_iso(),
        "include_demo": include_demo,
        "settings": all_settings,
        "centered_tasks": centered_tasks,
        "task_items": task_items,
        "task_progress_entries": progress_entries,
        "challenges": challenges,
        "urge_events": urge_events,
        "challenge_daily_records": daily_records,
        "challenge_daily_reflections": reflections,
        "challenge_comments": comments,
    }
    raw_json = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return raw_json, "focus_control_export_%s.json" % stamp


def _rows_to_csv_bytes(headers, rows):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([row.get(h, "") for h in headers])
    return buf.getvalue().encode("utf-8-sig")


def _build_dataset_csv(dataset, include_demo=True):
    db = get_db()
    if dataset == "tasks":
        headers = [
            "id", "name", "allocation_mode", "weight", "target_allocation", "target_unit",
            "priority", "status", "start_date", "target_end_date", "completed_at", "is_demo", "updated_at",
        ]
        sql = "SELECT * FROM centered_tasks WHERE COALESCE(is_deleted, 0) = 0"
        if not include_demo:
            sql += " AND is_demo = 0"
        sql += " ORDER BY id ASC"
        rows = [dict(r) for r in db.execute(sql).fetchall()]
        return _rows_to_csv_bytes(headers, rows), "centered_tasks.csv"

    if dataset == "progress_entries":
        headers = [
            "id", "entry_timestamp", "centered_task_name", "task_item_name",
            "quantity_completed", "target_unit", "time_spent_minutes", "update_source", "comments",
        ]
        rows = statistics_repository.list_progress_entries_in_range(include_demo=include_demo, conn=db)
        return _rows_to_csv_bytes(headers, rows), "task_progress_entries.csv"

    if dataset == "challenges":
        headers = [
            "id", "name", "behaviour_to_avoid", "objective", "start_date", "end_date",
            "planned_duration_days", "target_value", "target_unit", "status",
            "current_cycle_number", "is_demo", "completed_at",
        ]
        rows = challenge_repository.list_challenges(include_archived=True, conn=db)
        if not include_demo:
            rows = [c for c in rows if not c.get("is_demo")]
        return _rows_to_csv_bytes(headers, rows), "challenges.csv"

    if dataset == "urge_events":
        headers = [
            "id", "challenge_name", "cycle_number", "event_type", "outcome",
            "event_timestamp", "trigger_category", "trigger_text", "context",
            "duration_seconds", "comments", "tags",
        ]
        rows = statistics_repository.list_urge_events_in_range(include_demo=include_demo, conn=db)
        return _rows_to_csv_bytes(headers, rows), "urge_events.csv"

    if dataset == "reflections_comments":
        headers = ["entry_kind", "challenge_name", "record_date", "title_or_mood", "text", "context", "created_at"]
        combined = []
        for rf in statistics_repository.list_reflections_in_range(include_demo=include_demo, conn=db):
            combined.append({
                "entry_kind": "reflection",
                "challenge_name": rf["challenge_name"],
                "record_date": rf["record_date"],
                "title_or_mood": rf.get("title", "") + ((" [" + rf["mood"] + "]") if rf.get("mood") else ""),
                "text": rf["reflection_text"],
                "context": rf.get("context", ""),
                "created_at": rf["created_at"],
            })
        for cm in statistics_repository.list_comments_in_range(include_demo=include_demo, conn=db):
            combined.append({
                "entry_kind": "comment",
                "challenge_name": cm["challenge_name"],
                "record_date": cm["record_date"],
                "title_or_mood": "",
                "text": cm["comment_text"],
                "context": "",
                "created_at": cm["created_at"],
            })
        combined.sort(key=lambda r: (r["record_date"], r["created_at"]), reverse=True)
        return _rows_to_csv_bytes(headers, combined), "daily_reflections_and_comments.csv"

    raise ValidationError("Unsupported CSV dataset requested.")


def export_csv_download(dataset, include_demo=True):
    clean_ds = (dataset or "all").strip().lower()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    if clean_ds == "all":
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for ds_name in ("tasks", "progress_entries", "challenges", "urge_events", "reflections_comments"):
                data_bytes, filename = _build_dataset_csv(ds_name, include_demo=include_demo)
                zf.writestr(filename, data_bytes)
        return mem.getvalue(), "focus_control_csv_bundle_%s.zip" % stamp, "application/zip"

    data_bytes, filename = _build_dataset_csv(clean_ds, include_demo=include_demo)
    base, ext = os.path.splitext(filename)
    return data_bytes, "%s_%s%s" % (base, stamp, ext), "text/csv; charset=utf-8"


def get_trash_overview():
    return {
        "centered_tasks": task_repository.list_deleted_centered_tasks(),
        "task_items": task_repository.list_deleted_task_items(),
        "challenges": challenge_repository.list_deleted_challenges(),
        "events": challenge_repository.list_deleted_events(),
    }
