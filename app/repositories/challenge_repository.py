from app.database.connection import get_db


def list_challenges(status=None, search=None, include_archived=True, include_deleted=False, conn=None):
    db = conn or get_db()
    sql = """
        SELECT c.*,
               cs.background_image, cs.background_mode, cs.font_family, cs.font_size,
               cs.text_color, cs.accent_color, cs.card_style, cs.layout_style, cs.metadata_json,
               cc.cycle_number AS current_cycle_number,
               cc.started_at AS current_cycle_started_at,
               cc.status AS current_cycle_status
        FROM challenges c
        LEFT JOIN challenge_settings cs ON cs.challenge_id = c.id
        LEFT JOIN challenge_cycles cc ON cc.id = c.current_cycle_id
        WHERE 1 = 1
    """
    params = []
    if not include_deleted:
        sql += " AND COALESCE(c.is_deleted, 0) = 0"
    if status and status != "All":
        sql += " AND c.status = ?"
        params.append(status)
    elif not include_archived:
        sql += " AND c.status != 'Archived'"

    if search:
        sql += " AND (LOWER(c.name) LIKE ? OR LOWER(c.behaviour_to_avoid) LIKE ? OR LOWER(c.description) LIKE ?)"
        like_q = "%" + search.strip().lower() + "%"
        params.extend([like_q, like_q, like_q])

    sql += " ORDER BY CASE c.status WHEN 'Active' THEN 1 WHEN 'Paused' THEN 2 WHEN 'Not Started' THEN 3 WHEN 'Completed' THEN 4 ELSE 5 END, c.updated_at DESC, c.id DESC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_challenge(challenge_id, include_deleted=False, conn=None):
    db = conn or get_db()
    sql = """
        SELECT c.*,
               cs.background_image, cs.background_mode, cs.font_family, cs.font_size,
               cs.text_color, cs.accent_color, cs.card_style, cs.layout_style, cs.metadata_json,
               cc.cycle_number AS current_cycle_number,
               cc.started_at AS current_cycle_started_at,
               cc.status AS current_cycle_status
        FROM challenges c
        LEFT JOIN challenge_settings cs ON cs.challenge_id = c.id
        LEFT JOIN challenge_cycles cc ON cc.id = c.current_cycle_id
        WHERE c.id = ?
    """
    if not include_deleted:
        sql += " AND COALESCE(c.is_deleted, 0) = 0"
    row = db.execute(sql, (int(challenge_id),)).fetchone()
    return dict(row) if row else None


def insert_challenge(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO challenges (
            name, description, behaviour_to_avoid, objective,
            start_date, end_date, planned_duration_days, target_value, target_unit,
            status, current_cycle_id, is_demo,
            completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data["description"],
            data["behaviour_to_avoid"],
            data["objective"],
            data["start_date"],
            data["end_date"],
            data.get("planned_duration_days"),
            data.get("target_value", 0.0),
            data.get("target_unit", ""),
            data["status"],
            data.get("current_cycle_id"),
            data.get("is_demo", 0),
            data.get("completed_at"),
            data["created_at"],
            data["updated_at"],
        ),
    )
    return cur.lastrowid


def update_challenge(challenge_id, data, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE challenges
        SET name = ?,
            description = ?,
            behaviour_to_avoid = ?,
            objective = ?,
            start_date = ?,
            end_date = ?,
            planned_duration_days = ?,
            target_value = ?,
            target_unit = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            data["name"],
            data["description"],
            data["behaviour_to_avoid"],
            data["objective"],
            data["start_date"],
            data["end_date"],
            data.get("planned_duration_days"),
            data.get("target_value", 0.0),
            data.get("target_unit", ""),
            data["updated_at"],
            int(challenge_id),
        ),
    )


def update_challenge_status_and_cycle(challenge_id, status, current_cycle_id, completed_at, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE challenges
        SET status = ?,
            current_cycle_id = COALESCE(?, current_cycle_id),
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (status, current_cycle_id, completed_at, updated_at, int(challenge_id)),
    )


def upsert_challenge_settings(challenge_id, data, conn=None):
    db = conn or get_db()
    db.execute(
        """
        INSERT INTO challenge_settings (
            challenge_id, background_image, background_mode, font_family,
            font_size, text_color, accent_color, card_style, layout_style,
            metadata_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(challenge_id) DO UPDATE SET
            background_image = excluded.background_image,
            background_mode = excluded.background_mode,
            font_family = excluded.font_family,
            font_size = excluded.font_size,
            text_color = excluded.text_color,
            accent_color = excluded.accent_color,
            card_style = excluded.card_style,
            layout_style = excluded.layout_style,
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            int(challenge_id),
            data["background_image"],
            data["background_mode"],
            data["font_family"],
            data["font_size"],
            data["text_color"],
            data["accent_color"],
            data["card_style"],
            data["layout_style"],
            data["metadata_json"],
            data["updated_at"],
        ),
    )


def soft_delete_challenge(challenge_id, deleted_at, conn=None):
    db = conn or get_db()
    cid = int(challenge_id)
    db.execute(
        """
        UPDATE challenges
        SET is_deleted = 1, deleted_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (deleted_at, deleted_at, cid),
    )
    db.execute(
        """
        UPDATE urge_events
        SET is_deleted = 1, deleted_at = ?, updated_at = ?
        WHERE challenge_id = ? AND COALESCE(is_deleted, 0) = 0
        """,
        (deleted_at, deleted_at, cid),
    )


def restore_challenge(challenge_id, orig_deleted_at, updated_at, conn=None):
    db = conn or get_db()
    cid = int(challenge_id)
    db.execute(
        """
        UPDATE challenges
        SET is_deleted = 0, deleted_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (updated_at, cid),
    )
    if orig_deleted_at:
        db.execute(
            """
            UPDATE urge_events
            SET is_deleted = 0, deleted_at = NULL, updated_at = ?
            WHERE challenge_id = ? AND is_deleted = 1 AND deleted_at = ?
            """,
            (updated_at, cid, orig_deleted_at),
        )


def list_deleted_challenges(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT * FROM challenges
        WHERE COALESCE(is_deleted, 0) = 1
        ORDER BY deleted_at DESC, id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def delete_challenge_full(challenge_id, conn=None):
    db = conn or get_db()
    cid = int(challenge_id)
    db.execute("UPDATE challenges SET current_cycle_id = NULL WHERE id = ?", (cid,))
    db.execute("DELETE FROM urge_events WHERE challenge_id = ?", (cid,))
    db.execute("DELETE FROM challenge_daily_reflections WHERE challenge_id = ?", (cid,))
    db.execute("DELETE FROM challenge_comments WHERE challenge_id = ?", (cid,))
    db.execute("DELETE FROM challenge_daily_records WHERE challenge_id = ?", (cid,))
    db.execute("DELETE FROM challenge_cycles WHERE challenge_id = ?", (cid,))
    db.execute("DELETE FROM challenge_settings WHERE challenge_id = ?", (cid,))
    db.execute("DELETE FROM challenges WHERE id = ?", (cid,))


# ============================================================================
# CYCLES
# ============================================================================

def list_cycles_for_challenge(challenge_id, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT * FROM challenge_cycles
        WHERE challenge_id = ?
        ORDER BY cycle_number DESC
        """,
        (int(challenge_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_cycle(cycle_id, conn=None):
    db = conn or get_db()
    row = db.execute("SELECT * FROM challenge_cycles WHERE id = ?", (int(cycle_id),)).fetchone()
    return dict(row) if row else None


def get_max_cycle_number(challenge_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        "SELECT COALESCE(MAX(cycle_number), 0) AS max_num FROM challenge_cycles WHERE challenge_id = ?",
        (int(challenge_id),),
    ).fetchone()
    return int(row["max_num"]) if row else 0


def insert_cycle(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO challenge_cycles (
            challenge_id, cycle_number, status, started_at, ended_at, reset_reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(data["challenge_id"]),
            int(data["cycle_number"]),
            data["status"],
            data["started_at"],
            data.get("ended_at"),
            data.get("reset_reason", ""),
            data["created_at"],
        ),
    )
    return cur.lastrowid


def update_cycle_status(cycle_id, status, ended_at=None, reset_reason=None, started_at=None, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE challenge_cycles
        SET status = ?,
            ended_at = COALESCE(?, ended_at),
            reset_reason = COALESCE(?, reset_reason),
            started_at = COALESCE(?, started_at)
        WHERE id = ?
        """,
        (status, ended_at, reset_reason, started_at, int(cycle_id)),
    )


# ============================================================================
# URGE / THOUGHT / ACTION EVENTS
# ============================================================================

def list_events_for_challenge(challenge_id, cycle_id=None, event_type=None, outcome=None,
                              start_utc=None, end_utc=None, limit=500, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ue.*, cc.cycle_number
        FROM urge_events ue
        JOIN challenge_cycles cc ON cc.id = ue.cycle_id
        WHERE ue.challenge_id = ?
          AND COALESCE(ue.is_deleted, 0) = 0
    """
    params = [int(challenge_id)]
    if cycle_id:
        sql += " AND ue.cycle_id = ?"
        params.append(int(cycle_id))
    if event_type:
        sql += " AND ue.event_type = ?"
        params.append(event_type)
    if outcome:
        sql += " AND ue.outcome = ?"
        params.append(outcome)
    if start_utc:
        sql += " AND ue.event_timestamp >= ?"
        params.append(start_utc)
    if end_utc:
        sql += " AND ue.event_timestamp <= ?"
        params.append(end_utc)
    sql += " ORDER BY ue.event_timestamp DESC, ue.id DESC LIMIT ?"
    params.append(int(limit))
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_all_events(challenge_id=None, start_utc=None, end_utc=None, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ue.*, c.name AS challenge_name, cc.cycle_number
        FROM urge_events ue
        JOIN challenges c ON c.id = ue.challenge_id
        JOIN challenge_cycles cc ON cc.id = ue.cycle_id
        WHERE COALESCE(ue.is_deleted, 0) = 0
          AND COALESCE(c.is_deleted, 0) = 0
    """
    params = []
    if challenge_id:
        sql += " AND ue.challenge_id = ?"
        params.append(int(challenge_id))
    if start_utc:
        sql += " AND ue.event_timestamp >= ?"
        params.append(start_utc)
    if end_utc:
        sql += " AND ue.event_timestamp <= ?"
        params.append(end_utc)
    sql += " ORDER BY ue.event_timestamp DESC, ue.id DESC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_event(event_id, include_deleted=False, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ue.*, c.name AS challenge_name, cc.cycle_number
        FROM urge_events ue
        JOIN challenges c ON c.id = ue.challenge_id
        JOIN challenge_cycles cc ON cc.id = ue.cycle_id
        WHERE ue.id = ?
    """
    if not include_deleted:
        sql += " AND COALESCE(ue.is_deleted, 0) = 0 AND COALESCE(c.is_deleted, 0) = 0"
    row = db.execute(sql, (int(event_id),)).fetchone()
    return dict(row) if row else None


def count_events_for_challenge(challenge_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM urge_events WHERE challenge_id = ? AND COALESCE(is_deleted, 0) = 0",
        (int(challenge_id),),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def insert_event(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO urge_events (
            challenge_id, cycle_id, event_type, outcome, related_urge_id,
            event_timestamp, trigger_category, trigger_text, context, duration_seconds,
            comments, tags, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(data["challenge_id"]),
            int(data["cycle_id"]),
            data["event_type"],
            data["outcome"],
            data.get("related_urge_id"),
            data["event_timestamp"],
            data.get("trigger_category", ""),
            data["trigger_text"],
            data["context"],
            int(data["duration_seconds"]),
            data["comments"],
            data["tags"],
            data["created_at"],
            data["updated_at"],
        ),
    )
    return cur.lastrowid


def update_event(event_id, data, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE urge_events
        SET event_type = ?,
            outcome = ?,
            related_urge_id = ?,
            event_timestamp = ?,
            trigger_category = ?,
            trigger_text = ?,
            context = ?,
            duration_seconds = ?,
            comments = ?,
            tags = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            data["event_type"],
            data["outcome"],
            data.get("related_urge_id"),
            data["event_timestamp"],
            data.get("trigger_category", ""),
            data["trigger_text"],
            data["context"],
            int(data["duration_seconds"]),
            data["comments"],
            data["tags"],
            data["updated_at"],
            int(event_id),
        ),
    )


def update_event_outcome(event_id, outcome, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        "UPDATE urge_events SET outcome = ?, updated_at = ? WHERE id = ?",
        (outcome, updated_at, int(event_id)),
    )


def soft_delete_event(event_id, deleted_at, conn=None):
    db = conn or get_db()
    db.execute(
        "UPDATE urge_events SET is_deleted = 1, deleted_at = ?, updated_at = ? WHERE id = ?",
        (deleted_at, deleted_at, int(event_id)),
    )


def restore_event(event_id, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        "UPDATE urge_events SET is_deleted = 0, deleted_at = NULL, updated_at = ? WHERE id = ?",
        (updated_at, int(event_id)),
    )


def list_deleted_events(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT ue.*, c.name AS challenge_name
        FROM urge_events ue
        JOIN challenges c ON c.id = ue.challenge_id
        WHERE COALESCE(ue.is_deleted, 0) = 1
          AND COALESCE(c.is_deleted, 0) = 0
        ORDER BY ue.deleted_at DESC, ue.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def delete_event(event_id, conn=None):
    db = conn or get_db()
    db.execute("DELETE FROM urge_events WHERE id = ?", (int(event_id),))


# ============================================================================
# DAILY RECORDS, MULTI-REFLECTIONS & COMMENTS
# ============================================================================

def list_daily_records(challenge_id, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT * FROM challenge_daily_records
        WHERE challenge_id = ?
        ORDER BY record_date DESC
        """,
        (int(challenge_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_daily_record(challenge_id, record_date, reflection, mood, context, now_utc, conn=None):
    db = conn or get_db()
    db.execute(
        """
        INSERT INTO challenge_daily_records (
            challenge_id, record_date, reflection, mood, context, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(challenge_id, record_date) DO UPDATE SET
            reflection = excluded.reflection,
            mood = excluded.mood,
            context = excluded.context,
            updated_at = excluded.updated_at
        """,
        (int(challenge_id), record_date, reflection, mood, context, now_utc, now_utc),
    )


def list_daily_reflections(challenge_id, record_date=None, conn=None):
    db = conn or get_db()
    if record_date:
        rows = db.execute(
            """
            SELECT * FROM challenge_daily_reflections
            WHERE challenge_id = ? AND record_date = ?
            ORDER BY created_at DESC, id DESC
            """,
            (int(challenge_id), record_date),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT * FROM challenge_daily_reflections
            WHERE challenge_id = ?
            ORDER BY record_date DESC, created_at DESC, id DESC
            """,
            (int(challenge_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_daily_reflection(reflection_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        "SELECT * FROM challenge_daily_reflections WHERE id = ?",
        (int(reflection_id),),
    ).fetchone()
    return dict(row) if row else None


def insert_daily_reflection(challenge_id, cycle_id, record_date, title, reflection_text, mood, context, now_utc, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO challenge_daily_reflections (
            challenge_id, cycle_id, record_date, title,
            reflection_text, mood, context, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (int(challenge_id), cycle_id, record_date, title, reflection_text, mood, context, now_utc, now_utc),
    )
    return cur.lastrowid


def update_daily_reflection(reflection_id, title, reflection_text, mood, context, now_utc, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE challenge_daily_reflections
        SET title = ?,
            reflection_text = ?,
            mood = ?,
            context = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (title, reflection_text, mood, context, now_utc, int(reflection_id)),
    )


def delete_daily_reflection(reflection_id, conn=None):
    db = conn or get_db()
    db.execute("DELETE FROM challenge_daily_reflections WHERE id = ?", (int(reflection_id),))


def list_comments_for_challenge(challenge_id, record_date=None, conn=None):
    db = conn or get_db()
    if record_date:
        rows = db.execute(
            """
            SELECT * FROM challenge_comments
            WHERE challenge_id = ? AND record_date = ?
            ORDER BY created_at DESC, id DESC
            """,
            (int(challenge_id), record_date),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT * FROM challenge_comments
            WHERE challenge_id = ?
            ORDER BY record_date DESC, created_at DESC, id DESC
            """,
            (int(challenge_id),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_comment(comment_id, conn=None):
    db = conn or get_db()
    row = db.execute("SELECT * FROM challenge_comments WHERE id = ?", (int(comment_id),)).fetchone()
    return dict(row) if row else None


def insert_comment(challenge_id, cycle_id, record_date, comment_text, now_utc, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO challenge_comments (
            challenge_id, cycle_id, record_date, comment_text, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (int(challenge_id), cycle_id, record_date, comment_text, now_utc, now_utc),
    )
    return cur.lastrowid


def update_comment(comment_id, comment_text, now_utc, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE challenge_comments
        SET comment_text = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (comment_text, now_utc, int(comment_id)),
    )


def delete_comment(comment_id, conn=None):
    db = conn or get_db()
    db.execute("DELETE FROM challenge_comments WHERE id = ?", (int(comment_id),))

