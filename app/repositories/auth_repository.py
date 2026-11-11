from app.database.connection import get_db


def get_setting(key, default=None, conn=None):
    db = conn or get_db()
    row = db.execute(
        "SELECT value FROM app_settings WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return default
    return row["value"]


def get_all_settings(conn=None):
    db = conn or get_db()
    rows = db.execute("SELECT key, value, updated_at FROM app_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def upsert_setting(key, value, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, str(value), updated_at),
    )


def insert_activity_log(module, action, entity_type="", entity_id=None, details="", created_at="", conn=None):
    db = conn or get_db()
    db.execute(
        """
        INSERT INTO activity_logs (module, action, entity_type, entity_id, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (module, action, entity_type or "", entity_id, details or "", created_at),
    )


def list_activity_logs(limit=50, module=None, conn=None):
    db = conn or get_db()
    if module:
        rows = db.execute(
            """
            SELECT id, module, action, entity_type, entity_id, details, created_at
            FROM activity_logs
            WHERE module = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (module, int(limit)),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT id, module, action, entity_type, entity_id, details, created_at
            FROM activity_logs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]
