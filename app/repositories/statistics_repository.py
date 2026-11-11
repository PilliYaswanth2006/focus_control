from app.database.connection import get_db


def list_progress_entries_in_range(start_utc=None, end_utc=None, include_demo=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT pe.*,
               ti.name AS task_item_name,
               ti.target_unit,
               ti.target_quantity,
               ti.parent_centered_task_id,
               ct.name AS centered_task_name,
               ct.primary_color AS centered_color,
               ct.is_demo
        FROM task_progress_entries pe
        JOIN task_items ti ON ti.id = pe.task_item_id
        JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
        WHERE COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct.is_deleted, 0) = 0
    """
    params = []
    if not include_demo:
        sql += " AND ct.is_demo = 0"
    if start_utc:
        sql += " AND pe.entry_timestamp >= ?"
        params.append(start_utc)
    if end_utc:
        sql += " AND pe.entry_timestamp <= ?"
        params.append(end_utc)
    sql += " ORDER BY pe.entry_timestamp ASC, pe.id ASC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_completed_items_in_range(start_utc=None, end_utc=None, include_demo=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ti.id, ti.name, ti.completed_at, ti.target_quantity, ti.target_unit,
               ti.parent_centered_task_id, ct.name AS parent_name, ct.primary_color AS parent_color, ct.is_demo
        FROM task_items ti
        JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
        WHERE ti.status = 'Completed'
          AND ti.completed_at IS NOT NULL
          AND COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct.is_deleted, 0) = 0
    """
    params = []
    if not include_demo:
        sql += " AND ct.is_demo = 0"
    if start_utc:
        sql += " AND ti.completed_at >= ?"
        params.append(start_utc)
    if end_utc:
        sql += " AND ti.completed_at <= ?"
        params.append(end_utc)
    sql += " ORDER BY ti.completed_at ASC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_completed_centered_in_range(start_utc=None, end_utc=None, include_demo=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT id, name, completed_at, primary_color, target_allocation, target_unit, is_demo
        FROM centered_tasks
        WHERE status = 'Completed'
          AND completed_at IS NOT NULL
          AND COALESCE(is_deleted, 0) = 0
    """
    params = []
    if not include_demo:
        sql += " AND is_demo = 0"
    if start_utc:
        sql += " AND completed_at >= ?"
        params.append(start_utc)
    if end_utc:
        sql += " AND completed_at <= ?"
        params.append(end_utc)
    sql += " ORDER BY completed_at ASC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_urge_events_in_range(start_utc=None, end_utc=None, include_demo=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ue.*, c.name AS challenge_name, c.is_demo, cc.cycle_number
        FROM urge_events ue
        JOIN challenges c ON c.id = ue.challenge_id
        JOIN challenge_cycles cc ON cc.id = ue.cycle_id
        WHERE COALESCE(ue.is_deleted, 0) = 0
          AND COALESCE(c.is_deleted, 0) = 0
    """
    params = []
    if not include_demo:
        sql += " AND c.is_demo = 0"
    if start_utc:
        sql += " AND ue.event_timestamp >= ?"
        params.append(start_utc)
    if end_utc:
        sql += " AND ue.event_timestamp <= ?"
        params.append(end_utc)
    sql += " ORDER BY ue.event_timestamp ASC, ue.id ASC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_reflections_in_range(start_date=None, end_date=None, include_demo=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT dr.*, c.name AS challenge_name, c.is_demo
        FROM challenge_daily_reflections dr
        JOIN challenges c ON c.id = dr.challenge_id
        WHERE COALESCE(c.is_deleted, 0) = 0
    """
    params = []
    if not include_demo:
        sql += " AND c.is_demo = 0"
    if start_date:
        sql += " AND dr.record_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND dr.record_date <= ?"
        params.append(end_date)
    sql += " ORDER BY dr.record_date DESC, dr.created_at DESC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_daily_records_in_range(start_date=None, end_date=None, include_demo=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT r.*, c.name AS challenge_name, c.is_demo
        FROM challenge_daily_records r
        JOIN challenges c ON c.id = r.challenge_id
        WHERE COALESCE(c.is_deleted, 0) = 0
    """
    params = []
    if not include_demo:
        sql += " AND c.is_demo = 0"
    if start_date:
        sql += " AND r.record_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND r.record_date <= ?"
        params.append(end_date)
    sql += " ORDER BY r.record_date DESC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_comments_in_range(start_date=None, end_date=None, include_demo=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT cc.*, c.name AS challenge_name, c.is_demo
        FROM challenge_comments cc
        JOIN challenges c ON c.id = cc.challenge_id
        WHERE COALESCE(c.is_deleted, 0) = 0
    """
    params = []
    if not include_demo:
        sql += " AND c.is_demo = 0"
    if start_date:
        sql += " AND cc.record_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND cc.record_date <= ?"
        params.append(end_date)
    sql += " ORDER BY cc.record_date DESC, cc.created_at DESC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]

