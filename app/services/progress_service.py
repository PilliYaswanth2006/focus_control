from app.database.transaction import transaction
from app.repositories import auth_repository, task_repository
from app.utils.time_utils import local_input_to_utc, parse_utc_iso, utc_now, utc_now_iso
from app.utils.validation import ValidationError, clean_optional_text, parse_float, validate_choice


def _get_timezone():
    return auth_repository.get_setting("timezone", "UTC") or "UTC"


def _evaluate_lifecycle_after_progress(task_item_id, now_utc, conn, allow_auto_complete=True):
    item = task_repository.get_task_item(task_item_id, conn=conn)
    if not item or item["item_type"] == "linked_centered":
        return

    totals = task_repository.get_item_progress_totals(task_item_id, conn=conn)
    total_qty = totals["total_quantity"]
    total_mins = totals["total_time_minutes"]
    has_work = total_qty > 0 or total_mins > 0
    target_qty = float(item["target_quantity"])

    if allow_auto_complete and target_qty > 0 and total_qty >= target_qty and item["status"] not in ("Completed", "Archived"):
        old_status = item["status"]
        task_repository.update_task_item_status(task_item_id, "Completed", now_utc, None, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "task_item",
                "centered_task_id": item["parent_centered_task_id"],
                "task_item_id": task_item_id,
                "entity_name_snapshot": item["name"],
                "from_status": old_status,
                "to_status": "Completed",
                "reason": "Reached target quantity (%.2f / %.2f %s)" % (total_qty, target_qty, item["target_unit"]),
                "changed_at": now_utc,
            },
            conn=conn,
        )
        _propagate_parent_progress_and_completion(item["parent_centered_task_id"], now_utc, conn)
        return

    if has_work and item["status"] in ("Not Started", "Active"):
        old_status = item["status"]
        task_repository.update_task_item_status(task_item_id, "In Progress", None, None, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "task_item",
                "centered_task_id": item["parent_centered_task_id"],
                "task_item_id": task_item_id,
                "entity_name_snapshot": item["name"],
                "from_status": old_status,
                "to_status": "In Progress",
                "reason": "Started progress tracking",
                "changed_at": now_utc,
            },
            conn=conn,
        )
    elif item["status"] == "Completed" and target_qty > 0 and total_qty < target_qty:
        # Progress entry edited or deleted below target -> revert to In Progress with explicit audit
        task_repository.update_task_item_status(task_item_id, "In Progress", None, None, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "task_item",
                "centered_task_id": item["parent_centered_task_id"],
                "task_item_id": task_item_id,
                "entity_name_snapshot": item["name"],
                "from_status": "Completed",
                "to_status": "In Progress",
                "reason": "Progress adjusted below target (%.2f / %.2f %s)" % (total_qty, target_qty, item["target_unit"]),
                "changed_at": now_utc,
            },
            conn=conn,
        )

    _propagate_parent_progress_and_completion(item["parent_centered_task_id"], now_utc, conn)


def _propagate_parent_progress_and_completion(centered_task_id, now_utc, conn, visited=None):
    if visited is None:
        visited = set()
    if centered_task_id in visited:
        return
    visited.add(centered_task_id)

    parent = task_repository.get_centered_task(centered_task_id, conn=conn)
    if not parent or parent["status"] == "Archived":
        return

    children = task_repository.list_task_items_by_parent(centered_task_id, include_archived=False, conn=conn)
    if not children:
        return

    total_w = sum(float(c["weight_pct"]) for c in children)
    all_completed = all(c["status"] == "Completed" for c in children)
    any_started = any(c["status"] in ("In Progress", "Completed") for c in children)

    if all_completed and abs(total_w - 100.0) <= 0.01 and parent["status"] != "Completed":
        old_s = parent["status"]
        task_repository.update_centered_task_status(centered_task_id, "Completed", now_utc, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "centered_task",
                "centered_task_id": centered_task_id,
                "task_item_id": None,
                "entity_name_snapshot": parent["name"],
                "from_status": old_s,
                "to_status": "Completed",
                "reason": "All weighted internal tasks (100%) completed",
                "changed_at": now_utc,
            },
            conn=conn,
        )
    elif not all_completed and parent["status"] == "Completed":
        task_repository.update_centered_task_status(centered_task_id, "In Progress", None, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "centered_task",
                "centered_task_id": centered_task_id,
                "task_item_id": None,
                "entity_name_snapshot": parent["name"],
                "from_status": "Completed",
                "to_status": "In Progress",
                "reason": "Child task incomplete",
                "changed_at": now_utc,
            },
            conn=conn,
        )
    elif any_started and parent["status"] in ("Not Started", "Active"):
        old_s = parent["status"]
        task_repository.update_centered_task_status(centered_task_id, "In Progress", None, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "centered_task",
                "centered_task_id": centered_task_id,
                "task_item_id": None,
                "entity_name_snapshot": parent["name"],
                "from_status": old_s,
                "to_status": "In Progress",
                "reason": "Child task progress recorded",
                "changed_at": now_utc,
            },
            conn=conn,
        )

    # Check if this centered task is itself linked inside a grandparent centered task
    parent_link = task_repository.get_parent_link_for_centered_task(centered_task_id, conn=conn)
    if parent_link:
        refreshed_parent = task_repository.get_centered_task(centered_task_id, conn=conn)
        if refreshed_parent and refreshed_parent["status"] != parent_link["status"]:
            link_completed_at = now_utc if refreshed_parent["status"] == "Completed" else None
            task_repository.update_task_item_status(
                parent_link["id"], refreshed_parent["status"], link_completed_at, None, now_utc, conn=conn
            )
        _propagate_parent_progress_and_completion(parent_link["parent_centered_task_id"], now_utc, conn, visited)


def add_progress_entry(task_item_id, form_data):
    item = task_repository.get_task_item(task_item_id)
    if not item:
        raise ValidationError("Internal task not found.")
    if item["status"] == "Archived":
        raise ValidationError("Unarchive '%s' before recording progress." % item["name"])
    if item["item_type"] == "linked_centered":
        raise ValidationError("Log progress directly on the leaf internal tasks inside '%s'." % item["name"])

    qty = parse_float(form_data.get("quantity_completed"), "Quantity completed", min_val=0.0, max_val=1000000.0, default=0.0)
    time_val = parse_float(form_data.get("time_spent_minutes"), "Time spent (minutes)", min_val=0.0, max_val=10080.0, default=0.0)
    if qty <= 0 and time_val <= 0:
        raise ValidationError("Enter a positive quantity completed or time spent.")

    tz_name = _get_timezone()
    raw_ts = (form_data.get("entry_timestamp") or "").strip()
    entry_ts_utc = local_input_to_utc(raw_ts, tz_name) if raw_ts else utc_now_iso()
    comments = clean_optional_text(form_data.get("comments"), max_len=2000)
    update_source = validate_choice(
        form_data.get("update_source"), ("manual", "timer", "quick_log", "adjustment"), "Update source", default="manual"
    )
    now_utc = utc_now_iso()

    with transaction() as conn:
        entry_id = task_repository.insert_progress_entry(
            {
                "task_item_id": task_item_id,
                "quantity_completed": qty,
                "time_spent_minutes": time_val,
                "entry_timestamp": entry_ts_utc,
                "comments": comments,
                "update_source": update_source,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        _evaluate_lifecycle_after_progress(task_item_id, now_utc, conn, allow_auto_complete=True)
        auth_repository.insert_activity_log(
            "tasks",
            "progress_added",
            "task_item",
            task_item_id,
            "Logged +%s %s, %s min on '%s'" % (qty, item["target_unit"], time_val, item["name"]),
            now_utc,
            conn=conn,
        )
    return entry_id


def update_progress_entry(entry_id, form_data):
    existing = task_repository.get_progress_entry(entry_id)
    if not existing:
        raise ValidationError("Progress entry not found.")
    item = task_repository.get_task_item(existing["task_item_id"])

    qty = parse_float(
        form_data.get("quantity_completed"), "Quantity completed", min_val=0.0, max_val=1000000.0,
        default=existing["quantity_completed"]
    )
    time_val = parse_float(
        form_data.get("time_spent_minutes"), "Time spent (minutes)", min_val=0.0, max_val=10080.0,
        default=existing["time_spent_minutes"]
    )
    if qty <= 0 and time_val <= 0:
        raise ValidationError("Enter a positive quantity completed or time spent.")

    tz_name = _get_timezone()
    raw_ts = (form_data.get("entry_timestamp") or "").strip()
    entry_ts_utc = local_input_to_utc(raw_ts, tz_name) if raw_ts else existing["entry_timestamp"]
    comments = clean_optional_text(form_data.get("comments"), max_len=2000)
    update_source = validate_choice(
        form_data.get("update_source"),
        ("manual", "timer", "quick_log", "adjustment"),
        "Update source",
        default=existing["update_source"],
    )
    now_utc = utc_now_iso()

    with transaction() as conn:
        task_repository.update_progress_entry(
            entry_id,
            {
                "quantity_completed": qty,
                "time_spent_minutes": time_val,
                "entry_timestamp": entry_ts_utc,
                "comments": comments,
                "update_source": update_source,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        _evaluate_lifecycle_after_progress(existing["task_item_id"], now_utc, conn, allow_auto_complete=True)
        auth_repository.insert_activity_log(
            "tasks",
            "progress_updated",
            "task_progress_entry",
            entry_id,
            "Edited progress entry #%d on '%s'" % (entry_id, item["name"] if item else ""),
            now_utc,
            conn=conn,
        )


def delete_progress_entry(entry_id):
    existing = task_repository.get_progress_entry(entry_id)
    if not existing:
        raise ValidationError("Progress entry not found.")
    item = task_repository.get_task_item(existing["task_item_id"])
    now_utc = utc_now_iso()

    with transaction() as conn:
        task_repository.delete_progress_entry(entry_id, conn=conn)
        _evaluate_lifecycle_after_progress(existing["task_item_id"], now_utc, conn, allow_auto_complete=False)
        auth_repository.insert_activity_log(
            "tasks",
            "progress_deleted",
            "task_progress_entry",
            entry_id,
            "Deleted progress entry #%d from '%s'" % (entry_id, item["name"] if item else ""),
            now_utc,
            conn=conn,
        )


def reopen_task_item(item_id, reason="", new_target_quantity=None):
    item = task_repository.get_task_item(item_id)
    if not item:
        raise ValidationError("Internal task not found.")
    if item["status"] != "Completed":
        raise ValidationError("Only completed tasks can be reopened.")

    clean_reason = clean_optional_text(reason, max_len=300) or "Explicitly reopened by user"
    now_utc = utc_now_iso()

    with transaction() as conn:
        if new_target_quantity is not None and str(new_target_quantity).strip() != "":
            parsed_target = parse_float(new_target_quantity, "New target quantity", min_val=0.0, max_val=1000000.0)
            task_repository.update_task_item_allocation(
                item_id, float(item["weight_pct"]), float(item["allocated_time_budget"]), parsed_target, now_utc, conn=conn
            )

        task_repository.update_task_item_status(item_id, "In Progress", None, now_utc, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "task_item",
                "centered_task_id": item["parent_centered_task_id"],
                "task_item_id": item_id,
                "entity_name_snapshot": item["name"],
                "from_status": "Completed",
                "to_status": "In Progress",
                "reason": clean_reason,
                "changed_at": now_utc,
            },
            conn=conn,
        )
        _propagate_parent_progress_and_completion(item["parent_centered_task_id"], now_utc, conn)
        auth_repository.insert_activity_log(
            "tasks",
            "task_item_reopened",
            "task_item",
            item_id,
            "Reopened '%s': %s" % (item["name"], clean_reason),
            now_utc,
            conn=conn,
        )


def reopen_centered_task(centered_task_id, reason=""):
    ct = task_repository.get_centered_task(centered_task_id)
    if not ct:
        raise ValidationError("Centered task not found.")
    if ct["status"] != "Completed":
        raise ValidationError("Only completed tasks can be reopened.")

    clean_reason = clean_optional_text(reason, max_len=300) or "Explicitly reopened by user"
    now_utc = utc_now_iso()
    with transaction() as conn:
        task_repository.update_centered_task_status(centered_task_id, "In Progress", None, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "centered_task",
                "centered_task_id": centered_task_id,
                "task_item_id": None,
                "entity_name_snapshot": ct["name"],
                "from_status": "Completed",
                "to_status": "In Progress",
                "reason": clean_reason,
                "changed_at": now_utc,
            },
            conn=conn,
        )
        auth_repository.insert_activity_log(
            "tasks",
            "centered_task_reopened",
            "centered_task",
            centered_task_id,
            "Reopened '%s': %s" % (ct["name"], clean_reason),
            now_utc,
            conn=conn,
        )


def start_focus_session(task_item_id, notes=""):
    item = task_repository.get_task_item(task_item_id)
    if not item:
        raise ValidationError("Internal task not found.")
    if item["status"] == "Archived":
        raise ValidationError("Unarchive '%s' before starting a focus session." % item["name"])
    if item["item_type"] == "linked_centered":
        raise ValidationError("Start focus sessions on concrete internal tasks.")

    active = task_repository.get_active_session()
    if active:
        raise ValidationError(
            "A focus session is already active on '%s'. Finish or cancel it before starting another."
            % active["task_item_name"]
        )

    now_utc = utc_now_iso()
    with transaction() as conn:
        session_id = task_repository.insert_task_session(
            {
                "task_item_id": task_item_id,
                "started_at": now_utc,
                "ended_at": None,
                "duration_minutes": 0,
                "notes": clean_optional_text(notes, max_len=500),
                "status": "active",
                "progress_entry_id": None,
                "created_at": now_utc,
            },
            conn=conn,
        )
        auth_repository.insert_activity_log(
            "tasks", "focus_session_started", "task_session", session_id, "Started focus timer on '%s'" % item["name"], now_utc, conn=conn
        )
    return session_id


def stop_focus_session(session_id, quantity_completed=None, notes="", log_progress=True, cancel=False):
    sess = task_repository.get_task_session(session_id)
    if not sess:
        raise ValidationError("Focus session not found.")
    if sess["status"] != "active":
        raise ValidationError("Focus session is no longer active.")

    now_dt = utc_now()
    now_utc = utc_now_iso()
    start_dt = parse_utc_iso(sess["started_at"]) or now_dt
    elapsed_mins = max(1.0, round((now_dt - start_dt).total_seconds() / 60.0, 2))
    item = task_repository.get_task_item(sess["task_item_id"])
    clean_notes = clean_optional_text(notes, max_len=1000) or sess["notes"]

    with transaction() as conn:
        if cancel:
            task_repository.finish_task_session(
                session_id, now_utc, 0.0, clean_notes, "cancelled", None, conn=conn
            )
            return None

        entry_id = None
        if log_progress and item:
            if quantity_completed is None or str(quantity_completed).strip() == "":
                qty = round(elapsed_mins / 60.0, 2) if item["target_unit"] == "hours" else 0.0
            else:
                qty = parse_float(quantity_completed, "Quantity completed", min_val=0.0, max_val=1000000.0)

            entry_id = task_repository.insert_progress_entry(
                {
                    "task_item_id": item["id"],
                    "quantity_completed": qty,
                    "time_spent_minutes": elapsed_mins,
                    "entry_timestamp": now_utc,
                    "comments": clean_notes or "Logged from Focus Timer",
                    "update_source": "timer",
                    "created_at": now_utc,
                    "updated_at": now_utc,
                },
                conn=conn,
            )
            _evaluate_lifecycle_after_progress(item["id"], now_utc, conn, allow_auto_complete=True)

        task_repository.finish_task_session(
            session_id, now_utc, elapsed_mins, clean_notes, "completed", entry_id, conn=conn
        )
        auth_repository.insert_activity_log(
            "tasks",
            "focus_session_completed",
            "task_session",
            session_id,
            "Completed %.1f min focus session on '%s'" % (elapsed_mins, item["name"] if item else ""),
            now_utc,
            conn=conn,
        )
        return entry_id
