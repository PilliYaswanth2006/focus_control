from app.database.connection import get_db


def list_centered_tasks(status=None, search=None, priority=None, include_archived=True, include_deleted=False, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ct.*,
               parent_link.parent_centered_task_id AS linked_parent_id,
               parent_ct.name AS linked_parent_name
        FROM centered_tasks ct
        LEFT JOIN task_items parent_link
               ON parent_link.linked_centered_task_id = ct.id
              AND COALESCE(parent_link.is_deleted, 0) = 0
        LEFT JOIN centered_tasks parent_ct
               ON parent_ct.id = parent_link.parent_centered_task_id
              AND COALESCE(parent_ct.is_deleted, 0) = 0
        WHERE 1 = 1
    """
    params = []
    if not include_deleted:
        sql += " AND COALESCE(ct.is_deleted, 0) = 0"
    if status and status != "All":
        sql += " AND ct.status = ?"
        params.append(status)
    elif not include_archived:
        sql += " AND ct.status != 'Archived'"

    if priority and priority != "All":
        sql += " AND ct.priority = ?"
        params.append(priority)

    if search:
        sql += " AND (LOWER(ct.name) LIKE ? OR LOWER(ct.description) LIKE ?)"
        like_q = "%" + search.strip().lower() + "%"
        params.extend([like_q, like_q])

    sql += " ORDER BY ct.updated_at DESC, ct.id DESC"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_root_centered_tasks(include_archived=False, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ct.*
        FROM centered_tasks ct
        WHERE COALESCE(ct.is_deleted, 0) = 0
          AND ct.id NOT IN (
            SELECT linked_centered_task_id
            FROM task_items
            WHERE linked_centered_task_id IS NOT NULL
              AND COALESCE(is_deleted, 0) = 0
        )
    """
    if not include_archived:
        sql += " AND ct.status != 'Archived'"
    sql += " ORDER BY ct.weight DESC, ct.id ASC"
    rows = db.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_centered_task(task_id, include_deleted=False, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ct.*,
               parent_link.parent_centered_task_id AS linked_parent_id,
               parent_ct.name AS linked_parent_name,
               parent_link.id AS linked_via_item_id,
               parent_link.weight_pct AS linked_weight_pct
        FROM centered_tasks ct
        LEFT JOIN task_items parent_link
               ON parent_link.linked_centered_task_id = ct.id
              AND COALESCE(parent_link.is_deleted, 0) = 0
        LEFT JOIN centered_tasks parent_ct
               ON parent_ct.id = parent_link.parent_centered_task_id
              AND COALESCE(parent_ct.is_deleted, 0) = 0
        WHERE ct.id = ?
    """
    if not include_deleted:
        sql += " AND COALESCE(ct.is_deleted, 0) = 0"
    row = db.execute(sql, (int(task_id),)).fetchone()
    return dict(row) if row else None


def insert_centered_task(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO centered_tasks (
            name, description, weight, target_allocation, target_unit,
            allocation_mode, allocation_finalized, start_date, target_end_date,
            priority, status, background_image, background_mode, font_family,
            primary_color, accent_color, text_color, metadata_json, is_demo,
            completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data["description"],
            data["weight"],
            data["target_allocation"],
            data["target_unit"],
            data["allocation_mode"],
            data.get("allocation_finalized", 0),
            data["start_date"],
            data["target_end_date"],
            data["priority"],
            data["status"],
            data["background_image"],
            data["background_mode"],
            data["font_family"],
            data["primary_color"],
            data["accent_color"],
            data["text_color"],
            data["metadata_json"],
            data.get("is_demo", 0),
            data.get("completed_at"),
            data["created_at"],
            data["updated_at"],
        ),
    )
    return cur.lastrowid


def update_centered_task(task_id, data, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE centered_tasks
        SET name = ?,
            description = ?,
            weight = ?,
            target_allocation = ?,
            target_unit = ?,
            allocation_mode = ?,
            start_date = ?,
            target_end_date = ?,
            priority = ?,
            status = ?,
            background_image = ?,
            background_mode = ?,
            font_family = ?,
            primary_color = ?,
            accent_color = ?,
            text_color = ?,
            metadata_json = ?,
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            data["name"],
            data["description"],
            data["weight"],
            data["target_allocation"],
            data["target_unit"],
            data["allocation_mode"],
            data["start_date"],
            data["target_end_date"],
            data["priority"],
            data["status"],
            data["background_image"],
            data["background_mode"],
            data["font_family"],
            data["primary_color"],
            data["accent_color"],
            data["text_color"],
            data["metadata_json"],
            data.get("completed_at"),
            data["updated_at"],
            int(task_id),
        ),
    )


def update_centered_task_allocation_fields(task_id, target_allocation, target_unit, finalized, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE centered_tasks
        SET target_allocation = ?,
            target_unit = ?,
            allocation_finalized = COALESCE(?, allocation_finalized),
            updated_at = ?
        WHERE id = ?
        """,
        (target_allocation, target_unit, finalized, updated_at, int(task_id)),
    )


def update_centered_task_status(task_id, status, completed_at, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE centered_tasks
        SET status = ?,
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (status, completed_at, updated_at, int(task_id)),
    )


def soft_delete_centered_task(task_id, deleted_at, conn=None):
    db = conn or get_db()
    cid = int(task_id)
    db.execute(
        """
        UPDATE centered_tasks
        SET is_deleted = 1, deleted_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (deleted_at, deleted_at, cid),
    )
    db.execute(
        """
        UPDATE task_items
        SET is_deleted = 1, deleted_at = ?, updated_at = ?
        WHERE parent_centered_task_id = ? AND COALESCE(is_deleted, 0) = 0
        """,
        (deleted_at, deleted_at, cid),
    )


def restore_centered_task(task_id, orig_deleted_at, updated_at, conn=None):
    db = conn or get_db()
    cid = int(task_id)
    db.execute(
        """
        UPDATE centered_tasks
        SET is_deleted = 0, deleted_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (updated_at, cid),
    )
    if orig_deleted_at:
        db.execute(
            """
            UPDATE task_items
            SET is_deleted = 0, deleted_at = NULL, updated_at = ?
            WHERE parent_centered_task_id = ? AND is_deleted = 1 AND deleted_at = ?
            """,
            (updated_at, cid, orig_deleted_at),
        )


def list_deleted_centered_tasks(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT * FROM centered_tasks
        WHERE COALESCE(is_deleted, 0) = 1
        ORDER BY deleted_at DESC, id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def delete_centered_task(task_id, conn=None):
    db = conn or get_db()
    db.execute("DELETE FROM centered_tasks WHERE id = ?", (int(task_id),))


# ============================================================================
# TASK ITEMS (INTERNAL TASKS)
# ============================================================================

def list_all_task_items(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT ti.*,
               ct_parent.name AS parent_name,
               ct_linked.name AS linked_task_name,
               ct_linked.status AS linked_task_status
        FROM task_items ti
        JOIN centered_tasks ct_parent ON ct_parent.id = ti.parent_centered_task_id
        LEFT JOIN centered_tasks ct_linked ON ct_linked.id = ti.linked_centered_task_id
              AND COALESCE(ct_linked.is_deleted, 0) = 0
        WHERE COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct_parent.is_deleted, 0) = 0
        ORDER BY ti.parent_centered_task_id ASC, ti.sort_order ASC, ti.id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_task_items_by_parent(parent_id, include_archived=True, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ti.*,
               ct_linked.name AS linked_task_name,
               ct_linked.status AS linked_task_status,
               ct_linked.primary_color AS linked_task_color
        FROM task_items ti
        LEFT JOIN centered_tasks ct_linked ON ct_linked.id = ti.linked_centered_task_id
              AND COALESCE(ct_linked.is_deleted, 0) = 0
        WHERE ti.parent_centered_task_id = ?
          AND COALESCE(ti.is_deleted, 0) = 0
    """
    if not include_archived:
        sql += " AND ti.status != 'Archived'"
    sql += " ORDER BY ti.sort_order ASC, ti.id ASC"
    rows = db.execute(sql, (int(parent_id),)).fetchall()
    return [dict(r) for r in rows]


def get_task_item(item_id, include_deleted=False, conn=None):
    db = conn or get_db()
    sql = """
        SELECT ti.*,
               ct_parent.name AS parent_name,
               ct_parent.target_unit AS parent_target_unit,
               ct_parent.target_allocation AS parent_target_allocation,
               ct_parent.primary_color AS parent_primary_color,
               ct_linked.name AS linked_task_name,
               ct_linked.status AS linked_task_status
        FROM task_items ti
        JOIN centered_tasks ct_parent ON ct_parent.id = ti.parent_centered_task_id
        LEFT JOIN centered_tasks ct_linked ON ct_linked.id = ti.linked_centered_task_id
              AND COALESCE(ct_linked.is_deleted, 0) = 0
        WHERE ti.id = ?
    """
    if not include_deleted:
        sql += " AND COALESCE(ti.is_deleted, 0) = 0 AND COALESCE(ct_parent.is_deleted, 0) = 0"
    row = db.execute(sql, (int(item_id),)).fetchone()
    return dict(row) if row else None


def get_parent_link_for_centered_task(centered_task_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        """
        SELECT ti.*, ct.name AS parent_name
        FROM task_items ti
        JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
        WHERE ti.linked_centered_task_id = ?
          AND COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct.is_deleted, 0) = 0
        """,
        (int(centered_task_id),),
    ).fetchone()
    return dict(row) if row else None


def list_all_linked_edges(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT ti.id, ti.parent_centered_task_id, ti.linked_centered_task_id, ti.weight_pct, ti.status
        FROM task_items ti
        JOIN centered_tasks ct_p ON ct_p.id = ti.parent_centered_task_id
        JOIN centered_tasks ct_c ON ct_c.id = ti.linked_centered_task_id
        WHERE ti.item_type = 'linked_centered'
          AND ti.linked_centered_task_id IS NOT NULL
          AND COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct_p.is_deleted, 0) = 0
          AND COALESCE(ct_c.is_deleted, 0) = 0
        """
    ).fetchall()
    return [dict(r) for r in rows]


def insert_task_item(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO task_items (
            parent_centered_task_id, item_type, linked_centered_task_id,
            name, description, weight_pct, target_quantity, target_unit,
            allocated_time_budget, start_date, due_date, priority, status,
            notes, sort_order, reopened_at, completed_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(data["parent_centered_task_id"]),
            data["item_type"],
            data.get("linked_centered_task_id"),
            data["name"],
            data["description"],
            data["weight_pct"],
            data["target_quantity"],
            data["target_unit"],
            data["allocated_time_budget"],
            data["start_date"],
            data["due_date"],
            data["priority"],
            data["status"],
            data["notes"],
            data.get("sort_order", 0),
            data.get("reopened_at"),
            data.get("completed_at"),
            data["created_at"],
            data["updated_at"],
        ),
    )
    return cur.lastrowid


def update_task_item(item_id, data, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_items
        SET name = ?,
            description = ?,
            weight_pct = ?,
            target_quantity = ?,
            target_unit = ?,
            allocated_time_budget = ?,
            start_date = ?,
            due_date = ?,
            priority = ?,
            status = ?,
            notes = ?,
            completed_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            data["name"],
            data["description"],
            data["weight_pct"],
            data["target_quantity"],
            data["target_unit"],
            data["allocated_time_budget"],
            data["start_date"],
            data["due_date"],
            data["priority"],
            data["status"],
            data["notes"],
            data.get("completed_at"),
            data["updated_at"],
            int(item_id),
        ),
    )


def update_task_item_allocation(item_id, weight_pct, allocated_time_budget, target_quantity, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_items
        SET weight_pct = ?,
            allocated_time_budget = ?,
            target_quantity = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (weight_pct, allocated_time_budget, target_quantity, updated_at, int(item_id)),
    )


def update_task_item_status(item_id, status, completed_at, reopened_at, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_items
        SET status = ?,
            completed_at = ?,
            reopened_at = COALESCE(?, reopened_at),
            updated_at = ?
        WHERE id = ?
        """,
        (status, completed_at, reopened_at, updated_at, int(item_id)),
    )


def sync_linked_item_names(centered_task_id, new_name, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_items
        SET name = ?, updated_at = ?
        WHERE linked_centered_task_id = ?
        """,
        (new_name, updated_at, int(centered_task_id)),
    )


def soft_delete_task_item(item_id, deleted_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_items
        SET is_deleted = 1, deleted_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (deleted_at, deleted_at, int(item_id)),
    )


def restore_task_item(item_id, updated_at, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_items
        SET is_deleted = 0, deleted_at = NULL, updated_at = ?
        WHERE id = ?
        """,
        (updated_at, int(item_id)),
    )


def list_deleted_task_items(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT ti.*, ct.name AS parent_name, COALESCE(ct.is_deleted, 0) AS parent_is_deleted
        FROM task_items ti
        JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
        WHERE COALESCE(ti.is_deleted, 0) = 1
          AND COALESCE(ct.is_deleted, 0) = 0
        ORDER BY ti.deleted_at DESC, ti.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def delete_task_item(item_id, conn=None):
    db = conn or get_db()
    db.execute("DELETE FROM task_items WHERE id = ?", (int(item_id),))


def count_task_item_progress_entries(item_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM task_progress_entries WHERE task_item_id = ?",
        (int(item_id),),
    ).fetchone()
    return int(row["cnt"]) if row else 0


def count_centered_task_progress_entries(centered_task_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        """
        SELECT COUNT(*) AS cnt
        FROM task_progress_entries pe
        JOIN task_items ti ON ti.id = pe.task_item_id
        WHERE ti.parent_centered_task_id = ?
          AND COALESCE(ti.is_deleted, 0) = 0
        """,
        (int(centered_task_id),),
    ).fetchone()
    return int(row["cnt"]) if row else 0


# ============================================================================
# PROGRESS ENTRIES & SESSIONS
# ============================================================================

def get_all_item_progress_totals(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT pe.task_item_id,
               COALESCE(SUM(pe.quantity_completed), 0) AS total_quantity,
               COALESCE(SUM(pe.time_spent_minutes), 0) AS total_time_minutes,
               COUNT(*) AS entry_count,
               MAX(pe.entry_timestamp) AS last_entry_at
        FROM task_progress_entries pe
        JOIN task_items ti ON ti.id = pe.task_item_id
        WHERE COALESCE(ti.is_deleted, 0) = 0
        GROUP BY pe.task_item_id
        """
    ).fetchall()
    return {
        int(r["task_item_id"]): {
            "total_quantity": float(r["total_quantity"]),
            "total_time_minutes": float(r["total_time_minutes"]),
            "entry_count": int(r["entry_count"]),
            "last_entry_at": r["last_entry_at"],
        }
        for r in rows
    }


def get_item_progress_totals(item_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        """
        SELECT COALESCE(SUM(quantity_completed), 0) AS total_quantity,
               COALESCE(SUM(time_spent_minutes), 0) AS total_time_minutes,
               COUNT(*) AS entry_count
        FROM task_progress_entries
        WHERE task_item_id = ?
        """,
        (int(item_id),),
    ).fetchone()
    return {
        "total_quantity": float(row["total_quantity"]),
        "total_time_minutes": float(row["total_time_minutes"]),
        "entry_count": int(row["entry_count"]),
    }


def list_progress_entries_for_item(item_id, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT *
        FROM task_progress_entries
        WHERE task_item_id = ?
        ORDER BY entry_timestamp DESC, id DESC
        """,
        (int(item_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def list_progress_entries_for_centered_task(centered_task_id, limit=50, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT pe.*, ti.name AS task_item_name, ti.target_unit
        FROM task_progress_entries pe
        JOIN task_items ti ON ti.id = pe.task_item_id
        WHERE ti.parent_centered_task_id = ?
          AND COALESCE(ti.is_deleted, 0) = 0
        ORDER BY pe.entry_timestamp DESC, pe.id DESC
        LIMIT ?
        """,
        (int(centered_task_id), int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def get_progress_entry(entry_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        "SELECT * FROM task_progress_entries WHERE id = ?",
        (int(entry_id),),
    ).fetchone()
    return dict(row) if row else None


def insert_progress_entry(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO task_progress_entries (
            task_item_id, quantity_completed, time_spent_minutes,
            entry_timestamp, comments, update_source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(data["task_item_id"]),
            data["quantity_completed"],
            data["time_spent_minutes"],
            data["entry_timestamp"],
            data["comments"],
            data["update_source"],
            data["created_at"],
            data["updated_at"],
        ),
    )
    return cur.lastrowid


def update_progress_entry(entry_id, data, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_progress_entries
        SET quantity_completed = ?,
            time_spent_minutes = ?,
            entry_timestamp = ?,
            comments = ?,
            update_source = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            data["quantity_completed"],
            data["time_spent_minutes"],
            data["entry_timestamp"],
            data["comments"],
            data["update_source"],
            data["updated_at"],
            int(entry_id),
        ),
    )


def delete_progress_entry(entry_id, conn=None):
    db = conn or get_db()
    db.execute("DELETE FROM task_progress_entries WHERE id = ?", (int(entry_id),))


# ============================================================================
# TASK SESSIONS
# ============================================================================

def get_active_session(item_id=None, conn=None):
    db = conn or get_db()
    if item_id is not None:
        row = db.execute(
            """
            SELECT ts.*, ti.name AS task_item_name, ti.parent_centered_task_id
            FROM task_sessions ts
            JOIN task_items ti ON ti.id = ts.task_item_id
            WHERE ts.task_item_id = ?
              AND ts.status = 'active'
              AND COALESCE(ti.is_deleted, 0) = 0
            ORDER BY ts.id DESC
            LIMIT 1
            """,
            (int(item_id),),
        ).fetchone()
    else:
        row = db.execute(
            """
            SELECT ts.*, ti.name AS task_item_name, ti.parent_centered_task_id
            FROM task_sessions ts
            JOIN task_items ti ON ti.id = ts.task_item_id
            WHERE ts.status = 'active'
              AND COALESCE(ti.is_deleted, 0) = 0
            ORDER BY ts.id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_task_session(session_id, conn=None):
    db = conn or get_db()
    row = db.execute(
        "SELECT * FROM task_sessions WHERE id = ?",
        (int(session_id),),
    ).fetchone()
    return dict(row) if row else None


def insert_task_session(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO task_sessions (
            task_item_id, started_at, ended_at, duration_minutes,
            notes, status, progress_entry_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(data["task_item_id"]),
            data["started_at"],
            data.get("ended_at"),
            data.get("duration_minutes", 0),
            data.get("notes", ""),
            data.get("status", "active"),
            data.get("progress_entry_id"),
            data["created_at"],
        ),
    )
    return cur.lastrowid


def finish_task_session(session_id, ended_at, duration_minutes, notes, status, progress_entry_id, conn=None):
    db = conn or get_db()
    db.execute(
        """
        UPDATE task_sessions
        SET ended_at = ?,
            duration_minutes = ?,
            notes = ?,
            status = ?,
            progress_entry_id = ?
        WHERE id = ?
        """,
        (ended_at, duration_minutes, notes, status, progress_entry_id, int(session_id)),
    )


def list_sessions_for_item(item_id, limit=20, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT * FROM task_sessions
        WHERE task_item_id = ?
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (int(item_id), int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


# ============================================================================
# ALLOCATIONS & STATUS HISTORY
# ============================================================================

def deactivate_allocations(scope, centered_task_id=None, conn=None):
    db = conn or get_db()
    if centered_task_id is not None:
        db.execute(
            """
            UPDATE task_allocations
            SET is_active = 0
            WHERE scope = ? AND centered_task_id = ? AND is_active = 1
            """,
            (scope, int(centered_task_id)),
        )
    else:
        db.execute(
            """
            UPDATE task_allocations
            SET is_active = 0
            WHERE scope = ? AND is_active = 1
            """,
            (scope,),
        )


def insert_allocation_snapshot(data, conn=None):
    db = conn or get_db()
    cur = db.execute(
        """
        INSERT INTO task_allocations (
            snapshot_group_id, scope, centered_task_id, centered_task_name_snapshot,
            task_item_id, task_item_name_snapshot, budget_mode, total_budget,
            budget_unit, weight_pct, allocated_target, target_unit, reason,
            is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["snapshot_group_id"],
            data["scope"],
            data.get("centered_task_id"),
            data["centered_task_name_snapshot"],
            data.get("task_item_id"),
            data.get("task_item_name_snapshot", ""),
            data["budget_mode"],
            data["total_budget"],
            data["budget_unit"],
            data["weight_pct"],
            data["allocated_target"],
            data["target_unit"],
            data.get("reason", ""),
            data.get("is_active", 1),
            data["created_at"],
        ),
    )
    return cur.lastrowid


def list_allocation_snapshots(centered_task_id=None, task_item_id=None, limit=40, conn=None):
    db = conn or get_db()
    sql = "SELECT * FROM task_allocations WHERE 1 = 1"
    params = []
    if centered_task_id is not None:
        sql += " AND centered_task_id = ?"
        params.append(int(centered_task_id))
    if task_item_id is not None:
        sql += " AND task_item_id = ?"
        params.append(int(task_item_id))
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def insert_status_history(data, conn=None):
    db = conn or get_db()
    db.execute(
        """
        INSERT INTO task_status_history (
            entity_type, centered_task_id, task_item_id,
            entity_name_snapshot, from_status, to_status, reason, changed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["entity_type"],
            data.get("centered_task_id"),
            data.get("task_item_id"),
            data["entity_name_snapshot"],
            data.get("from_status", ""),
            data["to_status"],
            data.get("reason", ""),
            data["changed_at"],
        ),
    )


def list_status_history(centered_task_id=None, task_item_id=None, limit=40, conn=None):
    db = conn or get_db()
    sql = "SELECT * FROM task_status_history WHERE 1 = 1"
    params = []
    if centered_task_id is not None:
        sql += " AND centered_task_id = ?"
        params.append(int(centered_task_id))
    if task_item_id is not None:
        sql += " AND task_item_id = ?"
        params.append(int(task_item_id))
    sql += " ORDER BY changed_at DESC, id DESC LIMIT ?"
    params.append(int(limit))
    rows = db.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def list_completed_centered_tasks(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT * FROM centered_tasks
        WHERE status = 'Completed'
          AND COALESCE(is_deleted, 0) = 0
        ORDER BY COALESCE(completed_at, updated_at) DESC, id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_completed_task_items(conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT ti.*, ct.name AS parent_name, ct.primary_color AS parent_color
        FROM task_items ti
        JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
        WHERE ti.status = 'Completed'
          AND COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct.is_deleted, 0) = 0
        ORDER BY COALESCE(ti.completed_at, ti.updated_at) DESC, ti.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_recent_centered_tasks(limit=5, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT * FROM centered_tasks
        WHERE status != 'Archived'
          AND COALESCE(is_deleted, 0) = 0
        ORDER BY updated_at DESC, id DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def list_overdue_task_items(today_local_str, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT ti.*, ct.name AS parent_name
        FROM task_items ti
        JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
        WHERE ti.due_date != ''
          AND ti.due_date < ?
          AND ti.status NOT IN ('Completed', 'Archived')
          AND ct.status != 'Archived'
          AND COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct.is_deleted, 0) = 0
        ORDER BY ti.due_date ASC
        """,
        (today_local_str,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_upcoming_task_items(today_local_str, end_local_str, conn=None):
    db = conn or get_db()
    rows = db.execute(
        """
        SELECT ti.*, ct.name AS parent_name, ct.primary_color AS parent_color
        FROM task_items ti
        JOIN centered_tasks ct ON ct.id = ti.parent_centered_task_id
        WHERE ti.due_date != ''
          AND ti.due_date >= ?
          AND ti.due_date <= ?
          AND ti.status NOT IN ('Completed', 'Archived')
          AND ct.status != 'Archived'
          AND COALESCE(ti.is_deleted, 0) = 0
          AND COALESCE(ct.is_deleted, 0) = 0
        ORDER BY ti.due_date ASC, ti.id ASC
        """,
        (today_local_str, end_local_str),
    ).fetchall()
    return [dict(r) for r in rows]

