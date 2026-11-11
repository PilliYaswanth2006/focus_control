import os
import sqlite3
from datetime import datetime, timezone
from flask import current_app, g, has_app_context


SCHEMA_VERSION = 2

_PREDEFINED_TRIGGER_LOOKUP = {
    "boredom": "Boredom",
    "stress": "Stress",
    "loneliness": "Loneliness",
    "procrastination": "Procrastination",
    "habit": "Habit",
    "notifications": "Notifications",
    "entertainment": "Entertainment",
    "social pressure": "Social pressure",
    "other": "Other",
}


def _configure_connection(conn):
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA busy_timeout = 5000;")
    return conn


def create_connection(db_path):
    if db_path != ":memory:":
        parent_dir = os.path.dirname(os.path.abspath(db_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
    conn = sqlite3.connect(
        db_path,
        isolation_level=None,
        detect_types=sqlite3.PARSE_DECLTYPES,
        check_same_thread=False,
    )
    return _configure_connection(conn)


def get_db():
    if has_app_context():
        if "db_conn" not in g:
            db_path = current_app.config["DATABASE_PATH"]
            g.db_conn = create_connection(db_path)
            if db_path == ":memory:" and not getattr(current_app, "_memory_db_initialized", False):
                run_migrations(g.db_conn)
                current_app._memory_db_initialized = True
        return g.db_conn
    raise RuntimeError("Database access outside Flask application context requires explicit connection.")


def close_db(exception=None):
    conn = g.pop("db_conn", None)
    if conn is not None:
        conn.close()


def _table_columns(conn, table_name):
    rows = conn.execute("PRAGMA table_info(%s)" % table_name).fetchall()
    return {row["name"] for row in rows}


def _ensure_column(conn, table_name, col_name, col_def):
    if col_name not in _table_columns(conn, table_name):
        conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table_name, col_name, col_def))


def _migrate_v1_to_v2(conn, now_utc):
    conn.execute("BEGIN IMMEDIATE")
    try:
        _ensure_column(conn, "centered_tasks", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "centered_tasks", "deleted_at", "TEXT")

        _ensure_column(conn, "task_items", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "task_items", "deleted_at", "TEXT")

        _ensure_column(conn, "challenges", "target_value", "REAL DEFAULT 0")
        _ensure_column(conn, "challenges", "target_unit", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "challenges", "planned_duration_days", "INTEGER")
        _ensure_column(conn, "challenges", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "challenges", "deleted_at", "TEXT")

        _ensure_column(conn, "urge_events", "trigger_category", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, "urge_events", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(conn, "urge_events", "deleted_at", "TEXT")

        conn.execute("DROP INDEX IF EXISTS uq_task_items_single_parent_link")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_task_items_single_parent_link
            ON task_items(linked_centered_task_id)
            WHERE linked_centered_task_id IS NOT NULL AND is_deleted = 0
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_urge_events_trigger_cat
            ON urge_events(trigger_category, event_timestamp DESC)
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS challenge_daily_reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenge_id INTEGER NOT NULL REFERENCES challenges(id) ON DELETE CASCADE,
                cycle_id INTEGER REFERENCES challenge_cycles(id) ON DELETE SET NULL,
                record_date TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                reflection_text TEXT NOT NULL,
                mood TEXT NOT NULL DEFAULT '',
                context TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_daily_reflections_challenge_date
            ON challenge_daily_reflections(challenge_id, record_date DESC, created_at DESC)
            """
        )

        # Backfill non-empty challenge_daily_records rows into timestamped reflections if absent
        existing_daily = conn.execute(
            "SELECT * FROM challenge_daily_records"
        ).fetchall()
        for row in existing_daily:
            if not (row["reflection"] or row["mood"] or row["context"]):
                continue
            already = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM challenge_daily_reflections
                WHERE challenge_id = ? AND record_date = ?
                """,
                (row["challenge_id"], row["record_date"]),
            ).fetchone()
            if already and int(already["cnt"]) == 0:
                conn.execute(
                    """
                    INSERT INTO challenge_daily_reflections (
                        challenge_id, cycle_id, record_date, title,
                        reflection_text, mood, context, created_at, updated_at
                    ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["challenge_id"],
                        row["record_date"],
                        "Daily Reflection",
                        row["reflection"] or row["mood"] or row["context"],
                        row["mood"],
                        row["context"],
                        row["created_at"],
                        row["updated_at"],
                    ),
                )

        # Backfill trigger_category for existing urge_events without overwriting trigger_text
        ev_rows = conn.execute(
            "SELECT id, trigger_text, trigger_category FROM urge_events WHERE trigger_category = '' AND trigger_text != ''"
        ).fetchall()
        for ev in ev_rows:
            matched = _PREDEFINED_TRIGGER_LOOKUP.get(ev["trigger_text"].strip().lower(), "Other")
            conn.execute(
                "UPDATE urge_events SET trigger_category = ? WHERE id = ?",
                (matched, ev["id"]),
            )

        # Backfill planned_duration_days for challenges with start_date and end_date
        ch_rows = conn.execute(
            "SELECT id, start_date, end_date FROM challenges WHERE planned_duration_days IS NULL AND start_date != '' AND end_date != ''"
        ).fetchall()
        for ch in ch_rows:
            try:
                sd = datetime.strptime(ch["start_date"], "%Y-%m-%d")
                ed = datetime.strptime(ch["end_date"], "%Y-%m-%d")
                days = max(1, (ed - sd).days + 1)
                conn.execute(
                    "UPDATE challenges SET planned_duration_days = ? WHERE id = ?",
                    (days, ch["id"]),
                )
            except ValueError:
                pass

        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (2, "v2_soft_delete_triggers_reflections_targets", now_utc),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def run_migrations(conn):
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema_sql = fh.read()

    conn.execute("PRAGMA foreign_keys = ON;")

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()

    current_version = 0
    if row is not None:
        ver_row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_ver FROM schema_migrations"
        ).fetchone()
        current_version = int(ver_row["max_ver"]) if ver_row else 0

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if current_version == 0:
        conn.executescript(schema_sql)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (1, "initial_schema", now_utc),
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (2, "v2_soft_delete_triggers_reflections_targets", now_utc),
        )
        _ensure_default_settings(conn, now_utc)
    elif current_version < 2:
        _migrate_v1_to_v2(conn, now_utc)
        _ensure_default_settings(conn, now_utc)
    else:
        _ensure_default_settings(conn, now_utc)


def _ensure_default_settings(conn, now_utc):
    defaults = [
        ("theme", "light"),
        ("timezone", "Asia/Kolkata"),
        ("session_timeout_minutes", "30"),
        ("display_name", "Focused User"),
        ("task_budget_mode", "fixed"),
        ("task_total_budget", "40"),
        ("task_budget_unit", "hours"),
        ("auth_lock_version", "1"),
        ("auth_failed_attempts", "0"),
        ("auth_locked_until", ""),
    ]
    for key, value in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, now_utc),
        )


def migrate_database_file(db_path):
    conn = create_connection(db_path)
    try:
        run_migrations(conn)
    finally:
        conn.close()


def init_db(app):
    app.teardown_appcontext(close_db)
    db_path = app.config["DATABASE_PATH"]
    if db_path != ":memory:":
        migrate_database_file(db_path)
    else:
        # For :memory: testing, keep a single shared connection on app if desired
        conn = create_connection(":memory:")
        run_migrations(conn)
        app._shared_memory_conn = conn

        @app.before_request
        def _bind_memory_db():
            if "db_conn" not in g:
                g.db_conn = app._shared_memory_conn

        @app.teardown_appcontext
        def _keep_memory_db_open(exception=None):
            g.pop("db_conn", None)
