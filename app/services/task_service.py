import json
import uuid
from app.database.transaction import transaction
from app.repositories import auth_repository, task_repository
from app.services import allocation_service, progress_service
from app.utils.time_utils import local_today_str, utc_now_iso
from app.utils.uploads import resolve_background_choice
from app.utils.validation import (
    VALID_FONTS,
    VALID_PRIORITIES,
    VALID_TASK_STATUSES,
    ValidationError,
    clean_optional_text,
    parse_float,
    parse_metadata_json,
    require_non_empty,
    validate_choice,
    validate_date_order,
    validate_date_str,
    validate_hex_color,
)


PRIORITY_RANK = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
}


def _get_timezone():
    return auth_repository.get_setting("timezone", "UTC") or "UTC"


def _parse_metadata_dict(raw_json):
    try:
        parsed = json.loads(raw_json or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _validate_root_budget_weight(new_weight, exclude_task_id=None, conn=None):
    roots = task_repository.list_root_centered_tasks(include_archived=False, conn=conn)
    other_sum = sum(
        float(r["weight"])
        for r in roots
        if r["allocation_mode"] == "budgeted" and r["id"] != exclude_task_id
    )
    if other_sum + float(new_weight) > 100.001:
        remaining = max(0.0, round(100.0 - other_sum, 2))
        raise ValidationError(
            "Top-level budgeted weights cannot exceed 100%% (currently %.2f%% allocated, %.2f%% remaining)."
            % (other_sum, remaining)
        )


def compute_workspace_task_progress(root_tasks, metrics_idx):
    """
    Canonical workspace completion progress across root non-archived centered tasks.
    Uses SUM(Weight * Completion) / 100 for budgeted roots so unallocated weight
    is never silently treated as completed.
    """
    if not root_tasks:
        return 0.0

    budgeted_roots = [r for r in root_tasks if r.get("allocation_mode") == "budgeted"]
    if budgeted_roots:
        weighted_sum = sum(
            float(r["weight"]) * float(metrics_idx.get(r["id"], {}).get("completion_pct", 0.0))
            for r in budgeted_roots
        )
        return min(100.0, round(weighted_sum / 100.0, 1))

    manual_w_sum = sum(float(r["weight"]) for r in root_tasks)
    if 0 < manual_w_sum <= 100.001:
        weighted_sum = sum(
            float(r["weight"]) * float(metrics_idx.get(r["id"], {}).get("completion_pct", 0.0))
            for r in root_tasks
        )
        return min(100.0, round(weighted_sum / 100.0, 1))
    if manual_w_sum > 100.001:
        weighted_sum = sum(
            float(r["weight"]) * float(metrics_idx.get(r["id"], {}).get("completion_pct", 0.0))
            for r in root_tasks
        )
        return min(100.0, round(weighted_sum / manual_w_sum, 1))

    target_sum = sum(max(0.0, float(r.get("target_allocation", 0) or 0)) for r in root_tasks)
    if target_sum > 0:
        return round(
            sum(
                max(0.0, float(r.get("target_allocation", 0) or 0))
                * float(metrics_idx.get(r["id"], {}).get("completion_pct", 0.0))
                for r in root_tasks
            )
            / target_sum,
            1,
        )
    return round(
        sum(float(metrics_idx.get(r["id"], {}).get("completion_pct", 0.0)) for r in root_tasks) / len(root_tasks),
        1,
    )


def build_task_metrics_index(conn=None):
    """
    Compute non-duplicated metrics for all centered tasks and task items in one pass.
    - Leaf time & quantity always sum directly from task_progress_entries via item_totals.
    - Linked centered tasks propagate completion_pct and display rolled-up time without double counting global totals.
    - Parent progress uses strict weighted formula SUM(Child Weight * Child Completion) / 100.
    """
    all_centered = task_repository.list_centered_tasks(include_archived=True, conn=conn)
    all_items = task_repository.list_all_task_items(conn=conn)
    item_totals = task_repository.get_all_item_progress_totals(conn=conn)

    centered_by_id = {ct["id"]: ct for ct in all_centered}
    items_by_parent = {}
    for item in all_items:
        items_by_parent.setdefault(item["parent_centered_task_id"], []).append(item)

    today_str = local_today_str(_get_timezone())
    centered_metrics = {}
    visiting = set()

    def compute_centered(ct_id):
        if ct_id in centered_metrics:
            return centered_metrics[ct_id]
        if ct_id in visiting:
            return {
                "completion_pct": 0.0,
                "total_time_minutes": 0.0,
                "total_time_hours": 0.0,
                "active_item_count": 0,
                "completed_item_count": 0,
                "overdue_item_count": 0,
                "total_weight_pct": 0.0,
                "unallocated_weight_pct": 100.0,
                "weights_valid_100": False,
                "items": [],
            }
        visiting.add(ct_id)
        ct = centered_by_id.get(ct_id)
        children = items_by_parent.get(ct_id, [])

        active_items = [it for it in children if it["status"] != "Archived"]
        total_weight_pct = round(sum(float(it["weight_pct"]) for it in active_items), 4)
        weights_valid_100 = len(active_items) > 0 and abs(total_weight_pct - 100.0) <= 0.01

        enriched_items = []
        weighted_completion_sum = 0.0
        total_time_minutes = 0.0
        completed_count = 0
        overdue_count = 0

        for it in children:
            it_copy = dict(it)
            if it["item_type"] == "linked_centered" and it["linked_centered_task_id"]:
                child_m = compute_centered(it["linked_centered_task_id"])
                it_completion = child_m["completion_pct"]
                it_time_mins = child_m["total_time_minutes"]
                it_qty = round((it_completion / 100.0) * float(it["target_quantity"]), 2)
                it_copy["linked_metrics"] = child_m
                it_copy["entry_count"] = child_m["active_item_count"]
            else:
                totals = item_totals.get(it["id"], {"total_quantity": 0.0, "total_time_minutes": 0.0, "entry_count": 0})
                it_qty = round(totals["total_quantity"], 4)
                it_time_mins = round(totals["total_time_minutes"], 2)
                it_copy["entry_count"] = totals["entry_count"]
                if it["status"] == "Completed":
                    it_completion = 100.0
                elif float(it["target_quantity"]) > 0:
                    it_completion = min(100.0, round((it_qty / float(it["target_quantity"])) * 100.0, 2))
                else:
                    it_completion = 0.0

            is_overdue = bool(
                it["due_date"]
                and it["due_date"] < today_str
                and it["status"] not in ("Completed", "Archived")
                and (not ct or ct["status"] != "Archived")
            )
            it_copy["actual_quantity"] = round(it_qty, 2)
            it_copy["actual_time_minutes"] = round(it_time_mins, 2)
            it_copy["actual_time_hours"] = round(it_time_mins / 60.0, 2)
            it_copy["completion_pct"] = round(it_completion, 1)
            it_copy["is_overdue"] = is_overdue
            enriched_items.append(it_copy)

            if it["status"] != "Archived":
                weighted_completion_sum += float(it["weight_pct"]) * it_completion
                total_time_minutes += it_time_mins
                if it["status"] == "Completed":
                    completed_count += 1
                if is_overdue:
                    overdue_count += 1

        if ct and ct["status"] == "Completed" and not active_items:
            overall_pct = 100.0
        elif active_items:
            overall_pct = min(100.0, round(weighted_completion_sum / 100.0, 2))
        else:
            overall_pct = 0.0

        res = {
            "completion_pct": round(overall_pct, 1),
            "total_time_minutes": round(total_time_minutes, 2),
            "total_time_hours": round(total_time_minutes / 60.0, 2),
            "active_item_count": len(active_items),
            "completed_item_count": completed_count,
            "overdue_item_count": overdue_count,
            "total_weight_pct": round(total_weight_pct, 2),
            "unallocated_weight_pct": round(max(0.0, 100.0 - total_weight_pct), 2),
            "weights_valid_100": weights_valid_100,
            "items": enriched_items,
        }
        centered_metrics[ct_id] = res
        visiting.discard(ct_id)
        return res

    for ct in all_centered:
        compute_centered(ct["id"])

    return centered_metrics


def list_centered_tasks_with_metrics(
    status=None,
    search=None,
    priority=None,
    sort_by="priority_updated",
    date_from=None,
    date_to=None,
    overdue_only=False,
    include_archived=True,
):
    tasks = task_repository.list_centered_tasks(
        status=status, search=search, priority=None, include_archived=include_archived
    )
    metrics_idx = build_task_metrics_index()
    today_str = local_today_str(_get_timezone())
    enriched = []
    for t in tasks:
        m = metrics_idx.get(t["id"], {})
        t["metrics"] = m
        t["metadata"] = _parse_metadata_dict(t.get("metadata_json"))
        t["is_overdue"] = bool(
            t.get("target_end_date")
            and t["target_end_date"] < today_str
            and t["status"] not in ("Completed", "Archived")
        )
        if priority and priority != "All" and t["priority"] != priority:
            continue
        if overdue_only and not (t["is_overdue"] or m.get("overdue_item_count", 0) > 0):
            continue
        if date_from:
            end_or_start = t.get("target_end_date") or t.get("start_date") or ""
            if end_or_start and end_or_start < date_from:
                continue
        if date_to:
            start_or_end = t.get("start_date") or t.get("target_end_date") or ""
            if start_or_end and start_or_end > date_to:
                continue
        enriched.append(t)

    if sort_by == "weight":
        enriched.sort(key=lambda t: (-float(t.get("weight", 0) or 0), -float(t.get("target_allocation", 0) or 0), t["name"].lower()))
    elif sort_by == "completion":
        enriched.sort(key=lambda t: (-float(t["metrics"].get("completion_pct", 0.0)), PRIORITY_RANK.get(t["priority"], 2)))
    elif sort_by == "deadline":
        enriched.sort(key=lambda t: (t.get("target_end_date", "") == "", t.get("target_end_date") or "9999-12-31", PRIORITY_RANK.get(t["priority"], 2)))
    elif sort_by == "priority":
        enriched.sort(key=lambda t: (PRIORITY_RANK.get(t["priority"], 2), -float(t["metrics"].get("completion_pct", 0.0)), t["name"].lower()))
    elif sort_by == "name":
        enriched.sort(key=lambda t: t["name"].lower())
    elif sort_by == "updated":
        enriched.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
    else:
        enriched.sort(key=lambda t: t.get("updated_at", ""), reverse=True)
        enriched.sort(key=lambda t: PRIORITY_RANK.get(t["priority"], 2))

    return enriched


def get_centered_task_details(task_id):
    task = task_repository.get_centered_task(task_id)
    if not task:
        return None
    metrics_idx = build_task_metrics_index()
    task["metrics"] = metrics_idx.get(task["id"], {})
    task["metadata"] = _parse_metadata_dict(task.get("metadata_json"))
    task["tree_children"] = _build_nested_tree(task["id"], metrics_idx, depth=0, visited=set())
    task["allocations"] = task_repository.list_allocation_snapshots(centered_task_id=task["id"], limit=30)
    task["status_history"] = task_repository.list_status_history(centered_task_id=task["id"], limit=30)
    task["recent_progress"] = task_repository.list_progress_entries_for_centered_task(task["id"], limit=25)
    task["link_candidates"] = get_link_candidates(task["id"])
    return task


def _build_nested_tree(centered_id, metrics_idx, depth=0, visited=None):
    if visited is None:
        visited = set()
    if centered_id in visited or depth > 12:
        return []
    visited = set(visited) | {centered_id}
    m = metrics_idx.get(centered_id, {})
    nodes = []
    for item in m.get("items", []):
        node = dict(item)
        node["depth"] = depth
        if item["item_type"] == "linked_centered" and item["linked_centered_task_id"]:
            node["children"] = _build_nested_tree(
                item["linked_centered_task_id"], metrics_idx, depth=depth + 1, visited=visited
            )
        else:
            node["children"] = []
        nodes.append(node)
    return nodes


def get_task_item_details(item_id):
    item = task_repository.get_task_item(item_id)
    if not item:
        return None
    metrics_idx = build_task_metrics_index()
    parent_m = metrics_idx.get(item["parent_centered_task_id"], {})
    enriched = None
    for candidate in parent_m.get("items", []):
        if candidate["id"] == item["id"]:
            enriched = candidate
            break
    if enriched:
        item.update(enriched)
    item["progress_entries"] = task_repository.list_progress_entries_for_item(item["id"])
    item["sessions"] = task_repository.list_sessions_for_item(item["id"])
    item["active_session"] = task_repository.get_active_session(item_id=item["id"])
    item["allocations"] = task_repository.list_allocation_snapshots(task_item_id=item["id"], limit=20)
    item["status_history"] = task_repository.list_status_history(task_item_id=item["id"], limit=25)
    return item


def get_ancestors_of_centered_task(centered_id, conn=None):
    edges = task_repository.list_all_linked_edges(conn=conn)
    parent_of = {}
    for e in edges:
        parent_of[e["linked_centered_task_id"]] = e["parent_centered_task_id"]

    ancestors = []
    curr = centered_id
    seen = set()
    while curr in parent_of and curr not in seen:
        seen.add(curr)
        p = parent_of[curr]
        ancestors.append(p)
        curr = p
    return ancestors


def validate_link_candidate(parent_id, candidate_id, conn=None):
    if int(parent_id) == int(candidate_id):
        return False, "A centered task cannot be linked to itself."

    candidate = task_repository.get_centered_task(candidate_id, conn=conn)
    if not candidate:
        return False, "Selected centered task does not exist."
    if candidate["status"] == "Archived":
        return False, "Archived centered tasks cannot be linked."

    existing_link = task_repository.get_parent_link_for_centered_task(candidate_id, conn=conn)
    if existing_link is not None:
        if int(existing_link["parent_centered_task_id"]) == int(parent_id):
            return False, "Already linked inside this centered task."
        return False, (
            "Already linked under '%s'. Unlink it there first or create a new independent task to prevent duplicate progress."
            % existing_link["parent_name"]
        )

    ancestors = get_ancestors_of_centered_task(parent_id, conn=conn)
    if int(candidate_id) in ancestors:
        return False, "Circular reference detected: '%s' is an ancestor of this task." % candidate["name"]

    return True, "Eligible to link"


def get_link_candidates(parent_id, conn=None):
    all_tasks = task_repository.list_centered_tasks(include_archived=False, conn=conn)
    candidates = []
    for ct in all_tasks:
        if ct["id"] == int(parent_id):
            continue
        ok, reason = validate_link_candidate(parent_id, ct["id"], conn=conn)
        candidates.append({
            "id": ct["id"],
            "name": ct["name"],
            "status": ct["status"],
            "weight": ct["weight"],
            "eligible": ok,
            "reason": reason,
        })
    return candidates


def create_centered_task(form_data, bg_file=None):
    name = require_non_empty(form_data.get("name"), "Task name", max_len=140)
    description = clean_optional_text(form_data.get("description"), max_len=2000)
    weight = parse_float(form_data.get("weight"), "Weight (%)", min_val=0.0, max_val=100.0, default=0.0)
    allocation_mode = validate_choice(
        form_data.get("allocation_mode"), ("budgeted", "manual"), "Allocation mode", default="budgeted"
    )
    target_unit = clean_optional_text(form_data.get("target_unit"), max_len=30) or "hours"
    manual_target = parse_float(
        form_data.get("target_allocation"), "Target allocation", min_val=0.0, max_val=100000.0, default=0.0
    )

    start_date = validate_date_str(form_data.get("start_date"), "Start date")
    target_end_date = validate_date_str(form_data.get("target_end_date"), "Target end date")
    validate_date_order(start_date, target_end_date, "Start date", "Target end date")

    priority = validate_choice(form_data.get("priority"), VALID_PRIORITIES, "Priority", default="Medium")
    status = validate_choice(form_data.get("status"), VALID_TASK_STATUSES, "Status", default="Not Started")
    font_family = validate_choice(form_data.get("font_family"), VALID_FONTS, "Font family", default="Inter")
    primary_color = validate_hex_color(form_data.get("primary_color"), default="#4F46E5")
    accent_color = validate_hex_color(form_data.get("accent_color"), default="#0EA5E9")
    text_color = validate_hex_color(form_data.get("text_color"), default="")
    metadata_json = parse_metadata_json(
        form_data.get("metadata_json"),
        form_data.getlist("meta_key") if hasattr(form_data, "getlist") else None,
        form_data.getlist("meta_value") if hasattr(form_data, "getlist") else None,
    )

    bg_path, bg_mode = resolve_background_choice(bg_file, form_data.get("background_preset"))
    now_utc = utc_now_iso()
    completed_at = now_utc if status == "Completed" else None

    with transaction() as conn:
        if allocation_mode == "budgeted":
            if status != "Archived":
                _validate_root_budget_weight(weight, exclude_task_id=None, conn=conn)
            global_budget = float(auth_repository.get_setting("task_total_budget", "40", conn=conn) or 40)
            budget_unit = auth_repository.get_setting("task_budget_unit", "hours", conn=conn) or "hours"
            target_allocation = round(global_budget * (weight / 100.0), 4)
            target_unit = budget_unit
            budget_mode = auth_repository.get_setting("task_budget_mode", "fixed", conn=conn) or "fixed"
        else:
            target_allocation = manual_target
            global_budget = manual_target
            budget_mode = "manual"

        task_id = task_repository.insert_centered_task(
            {
                "name": name,
                "description": description,
                "weight": weight,
                "target_allocation": target_allocation,
                "target_unit": target_unit,
                "allocation_mode": allocation_mode,
                "allocation_finalized": 0,
                "start_date": start_date,
                "target_end_date": target_end_date,
                "priority": priority,
                "status": status,
                "background_image": bg_path,
                "background_mode": bg_mode,
                "font_family": font_family,
                "primary_color": primary_color,
                "accent_color": accent_color,
                "text_color": text_color,
                "metadata_json": metadata_json,
                "is_demo": 0,
                "completed_at": completed_at,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        task_repository.insert_status_history(
            {
                "entity_type": "centered_task",
                "centered_task_id": task_id,
                "task_item_id": None,
                "entity_name_snapshot": name,
                "from_status": "",
                "to_status": status,
                "reason": "Created centered task",
                "changed_at": now_utc,
            },
            conn=conn,
        )

        task_repository.insert_allocation_snapshot(
            {
                "snapshot_group_id": uuid.uuid4().hex[:12],
                "scope": "global_budget" if allocation_mode == "budgeted" else "manual_override",
                "centered_task_id": task_id,
                "centered_task_name_snapshot": name,
                "task_item_id": None,
                "task_item_name_snapshot": "",
                "budget_mode": budget_mode,
                "total_budget": global_budget,
                "budget_unit": target_unit,
                "weight_pct": weight,
                "allocated_target": target_allocation,
                "target_unit": target_unit,
                "reason": "Initial centered task allocation",
                "is_active": 1,
                "created_at": now_utc,
            },
            conn=conn,
        )

        auth_repository.insert_activity_log(
            "tasks", "centered_task_created", "centered_task", task_id, "Created '%s'" % name, now_utc, conn=conn
        )

    return task_id


def update_centered_task(task_id, form_data, bg_file=None):
    existing = task_repository.get_centered_task(task_id)
    if not existing:
        raise ValidationError("Centered task not found.")

    name = require_non_empty(form_data.get("name"), "Task name", max_len=140)
    description = clean_optional_text(form_data.get("description"), max_len=2000)
    weight = parse_float(form_data.get("weight"), "Weight (%)", min_val=0.0, max_val=100.0, default=existing["weight"])
    allocation_mode = validate_choice(
        form_data.get("allocation_mode"), ("budgeted", "manual"), "Allocation mode", default=existing["allocation_mode"]
    )
    target_unit = clean_optional_text(form_data.get("target_unit"), max_len=30) or existing["target_unit"]
    manual_target = parse_float(
        form_data.get("target_allocation"), "Target allocation", min_val=0.0, max_val=100000.0, default=existing["target_allocation"]
    )

    start_date = validate_date_str(form_data.get("start_date"), "Start date")
    target_end_date = validate_date_str(form_data.get("target_end_date"), "Target end date")
    validate_date_order(start_date, target_end_date, "Start date", "Target end date")

    priority = validate_choice(form_data.get("priority"), VALID_PRIORITIES, "Priority", default=existing["priority"])
    status = validate_choice(form_data.get("status"), VALID_TASK_STATUSES, "Status", default=existing["status"])
    font_family = validate_choice(form_data.get("font_family"), VALID_FONTS, "Font family", default=existing["font_family"])
    primary_color = validate_hex_color(form_data.get("primary_color"), default=existing["primary_color"])
    accent_color = validate_hex_color(form_data.get("accent_color"), default=existing["accent_color"])
    text_color = validate_hex_color(form_data.get("text_color"), default="")
    metadata_json = parse_metadata_json(
        form_data.get("metadata_json"),
        form_data.getlist("meta_key") if hasattr(form_data, "getlist") else None,
        form_data.getlist("meta_value") if hasattr(form_data, "getlist") else None,
    )

    bg_choice = form_data.get("background_preset", "__keep__")
    bg_path, bg_mode = resolve_background_choice(
        bg_file, bg_choice, current_bg=existing["background_image"], current_mode=existing["background_mode"]
    )
    now_utc = utc_now_iso()
    completed_at = existing["completed_at"]
    if status == "Completed" and existing["status"] != "Completed":
        completed_at = now_utc
    elif status != "Completed":
        completed_at = None

    with transaction() as conn:
        if allocation_mode == "budgeted":
            if existing.get("linked_parent_id"):
                target_allocation = existing["target_allocation"]
                global_budget = target_allocation
                budget_mode = "dynamic"
            else:
                if status != "Archived":
                    _validate_root_budget_weight(weight, exclude_task_id=task_id, conn=conn)
                global_budget = float(auth_repository.get_setting("task_total_budget", "40", conn=conn) or 40)
                budget_unit = auth_repository.get_setting("task_budget_unit", "hours", conn=conn) or "hours"
                target_allocation = round(global_budget * (weight / 100.0), 4)
                target_unit = budget_unit
                budget_mode = auth_repository.get_setting("task_budget_mode", "fixed", conn=conn) or "fixed"
        else:
            target_allocation = manual_target
            global_budget = manual_target
            budget_mode = "manual"

        task_repository.update_centered_task(
            task_id,
            {
                "name": name,
                "description": description,
                "weight": weight,
                "target_allocation": target_allocation,
                "target_unit": target_unit,
                "allocation_mode": allocation_mode,
                "start_date": start_date,
                "target_end_date": target_end_date,
                "priority": priority,
                "status": status,
                "background_image": bg_path,
                "background_mode": bg_mode,
                "font_family": font_family,
                "primary_color": primary_color,
                "accent_color": accent_color,
                "text_color": text_color,
                "metadata_json": metadata_json,
                "completed_at": completed_at,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        if name != existing["name"]:
            task_repository.sync_linked_item_names(task_id, name, now_utc, conn=conn)

        if status != existing["status"]:
            task_repository.insert_status_history(
                {
                    "entity_type": "centered_task",
                    "centered_task_id": task_id,
                    "task_item_id": None,
                    "entity_name_snapshot": name,
                    "from_status": existing["status"],
                    "to_status": status,
                    "reason": "Updated via task edit",
                    "changed_at": now_utc,
                },
                conn=conn,
            )

        target_changed = (
            abs(target_allocation - float(existing["target_allocation"])) > 0.0001
            or target_unit != existing["target_unit"]
        )
        if target_changed or abs(weight - float(existing["weight"])) > 0.0001:
            snap_group = uuid.uuid4().hex[:12]
            task_repository.deactivate_allocations("global_budget", centered_task_id=task_id, conn=conn)
            task_repository.insert_allocation_snapshot(
                {
                    "snapshot_group_id": snap_group,
                    "scope": "global_budget" if allocation_mode == "budgeted" else "manual_override",
                    "centered_task_id": task_id,
                    "centered_task_name_snapshot": name,
                    "task_item_id": None,
                    "task_item_name_snapshot": "",
                    "budget_mode": budget_mode,
                    "total_budget": global_budget,
                    "budget_unit": target_unit,
                    "weight_pct": weight,
                    "allocated_target": target_allocation,
                    "target_unit": target_unit,
                    "reason": "Updated centered task settings",
                    "is_active": 1,
                    "created_at": now_utc,
                },
                conn=conn,
            )
            if target_changed:
                allocation_service._cascade_internal_allocation(
                    task_id,
                    target_allocation,
                    target_unit,
                    budget_mode,
                    snap_group,
                    "Centered task target updated",
                    True,
                    now_utc,
                    conn,
                )

        auth_repository.insert_activity_log(
            "tasks", "centered_task_updated", "centered_task", task_id, "Updated '%s'" % name, now_utc, conn=conn
        )


def delete_centered_task(task_id, confirm_force=False, permanent=False):
    existing = task_repository.get_centered_task(task_id, include_deleted=permanent)
    if not existing:
        raise ValidationError("Centered task not found.")

    parent_link = task_repository.get_parent_link_for_centered_task(task_id)
    if parent_link is not None:
        raise ValidationError(
            "Cannot delete '%s' while it is linked inside '%s'. Unlink it from '%s' first."
            % (existing["name"], parent_link["parent_name"], parent_link["parent_name"])
        )

    progress_count = task_repository.count_centered_task_progress_entries(task_id)
    if progress_count > 0 and not confirm_force:
        raise ValidationError(
            "This centered task has %d progress entry/entries. Confirm deletion to move it to Trash or archive it instead."
            % progress_count
        )

    now_utc = utc_now_iso()
    with transaction() as conn:
        if permanent:
            task_repository.delete_centered_task(task_id, conn=conn)
            action = "centered_task_purged"
            detail = "Permanently deleted '%s' (progress entries removed: %d)" % (existing["name"], progress_count)
        else:
            task_repository.soft_delete_centered_task(task_id, now_utc, conn=conn)
            action = "centered_task_deleted"
            detail = "Moved '%s' to Trash (progress entries preserved: %d)" % (existing["name"], progress_count)

        auth_repository.insert_activity_log(
            "tasks",
            action,
            "centered_task",
            task_id,
            detail,
            now_utc,
            conn=conn,
        )


def restore_centered_task(task_id):
    existing = task_repository.get_centered_task(task_id, include_deleted=True)
    if not existing or not existing.get("is_deleted"):
        raise ValidationError("Deleted centered task not found in Trash.")

    now_utc = utc_now_iso()
    weight_adjusted = False
    with transaction() as conn:
        orig_deleted_at = existing.get("deleted_at")
        task_repository.restore_centered_task(task_id, orig_deleted_at, now_utc, conn=conn)
        if existing["allocation_mode"] == "budgeted" and existing["status"] != "Archived":
            roots = task_repository.list_root_centered_tasks(include_archived=False, conn=conn)
            other_sum = sum(
                float(r["weight"])
                for r in roots
                if r["allocation_mode"] == "budgeted" and r["id"] != task_id
            )
            if other_sum + float(existing["weight"]) > 100.001:
                allowed = max(0.0, round(100.0 - other_sum, 2))
                global_budget = float(auth_repository.get_setting("task_total_budget", "40", conn=conn) or 40)
                new_target = round(global_budget * (allowed / 100.0), 4)
                restored_data = dict(existing)
                restored_data["weight"] = allowed
                restored_data["target_allocation"] = new_target
                restored_data["updated_at"] = now_utc
                task_repository.update_centered_task(task_id, restored_data, conn=conn)
                weight_adjusted = True

        auth_repository.insert_activity_log(
            "tasks",
            "centered_task_restored",
            "centered_task",
            task_id,
            "Restored '%s' from Trash" % existing["name"],
            now_utc,
            conn=conn,
        )
    return weight_adjusted


def transition_centered_task_status(task_id, new_status, reason=""):
    existing = task_repository.get_centered_task(task_id)
    if not existing:
        raise ValidationError("Centered task not found.")
    target_status = validate_choice(new_status, VALID_TASK_STATUSES, "Status")
    if target_status == existing["status"]:
        return

    now_utc = utc_now_iso()
    completed_at = now_utc if target_status == "Completed" else None
    clean_reason = clean_optional_text(reason, max_len=300) or ("Status changed to %s" % target_status)

    with transaction() as conn:
        if (
            existing["status"] == "Archived"
            and target_status != "Archived"
            and existing["allocation_mode"] == "budgeted"
            and not existing.get("linked_parent_id")
        ):
            _validate_root_budget_weight(float(existing["weight"]), exclude_task_id=task_id, conn=conn)

        task_repository.update_centered_task_status(task_id, target_status, completed_at, now_utc, conn=conn)
        task_repository.insert_status_history(
            {
                "entity_type": "centered_task",
                "centered_task_id": task_id,
                "task_item_id": None,
                "entity_name_snapshot": existing["name"],
                "from_status": existing["status"],
                "to_status": target_status,
                "reason": clean_reason,
                "changed_at": now_utc,
            },
            conn=conn,
        )
        auth_repository.insert_activity_log(
            "tasks",
            "centered_task_status_changed",
            "centered_task",
            task_id,
            "%s: %s -> %s" % (existing["name"], existing["status"], target_status),
            now_utc,
            conn=conn,
        )


def add_internal_task_item(parent_centered_id, form_data):
    parent = task_repository.get_centered_task(parent_centered_id)
    if not parent:
        raise ValidationError("Parent centered task not found.")

    item_type = validate_choice(
        form_data.get("item_type"), ("standard", "linked_centered"), "Task type", default="standard"
    )
    weight_pct = parse_float(form_data.get("weight_pct"), "Weight percentage", min_val=0.0, max_val=100.0)
    priority = validate_choice(form_data.get("priority"), VALID_PRIORITIES, "Priority", default="Medium")
    status = validate_choice(form_data.get("status"), VALID_TASK_STATUSES, "Status", default="Not Started")
    start_date = validate_date_str(form_data.get("start_date"), "Start date")
    due_date = validate_date_str(form_data.get("due_date"), "Due date")
    validate_date_order(start_date, due_date, "Start date", "Due date")
    notes = clean_optional_text(form_data.get("notes"), max_len=2000)

    existing_items = task_repository.list_task_items_by_parent(parent_centered_id, include_archived=False)
    current_weight_sum = sum(float(i["weight_pct"]) for i in existing_items)
    if status != "Archived" and current_weight_sum + weight_pct > 100.001:
        remaining = max(0.0, round(100.0 - current_weight_sum, 2))
        raise ValidationError(
            "Adding %.2f%% would exceed 100%% (current total: %.2f%%, maximum remaining: %.2f%%)."
            % (weight_pct, current_weight_sum, remaining)
        )

    allocated_time_budget = round(float(parent["target_allocation"]) * (weight_pct / 100.0), 4)
    now_utc = utc_now_iso()

    with transaction() as conn:
        if item_type == "linked_centered":
            linked_id = int(form_data.get("linked_centered_task_id") or 0)
            if not linked_id:
                raise ValidationError("Please select an existing centered task to link.")
            ok, reason = validate_link_candidate(parent_centered_id, linked_id, conn=conn)
            if not ok:
                raise ValidationError(reason)
            linked_ct = task_repository.get_centered_task(linked_id, conn=conn)
            name = linked_ct["name"]
            description = clean_optional_text(form_data.get("description"), max_len=2000) or linked_ct["description"]
            target_unit = parent["target_unit"]
            target_quantity = allocated_time_budget
            status = linked_ct["status"] if linked_ct["status"] != "Archived" else "Active"
        else:
            linked_id = None
            name = require_non_empty(form_data.get("name"), "Internal task name", max_len=140)
            description = clean_optional_text(form_data.get("description"), max_len=2000)
            target_unit = clean_optional_text(form_data.get("target_unit"), max_len=30) or parent["target_unit"]
            raw_qty = (form_data.get("target_quantity") or "").strip()
            if raw_qty == "":
                target_quantity = allocated_time_budget
            else:
                target_quantity = parse_float(raw_qty, "Target quantity", min_val=0.0, max_val=1000000.0)

        completed_at = now_utc if status == "Completed" else None
        item_id = task_repository.insert_task_item(
            {
                "parent_centered_task_id": parent_centered_id,
                "item_type": item_type,
                "linked_centered_task_id": linked_id,
                "name": name,
                "description": description,
                "weight_pct": weight_pct,
                "target_quantity": target_quantity,
                "target_unit": target_unit,
                "allocated_time_budget": allocated_time_budget,
                "start_date": start_date,
                "due_date": due_date,
                "priority": priority,
                "status": status,
                "notes": notes,
                "sort_order": len(existing_items) + 1,
                "completed_at": completed_at,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        snap_group = uuid.uuid4().hex[:12]
        budget_mode = auth_repository.get_setting("task_budget_mode", "fixed", conn=conn) or "fixed"

        if item_type == "linked_centered" and linked_id:
            task_repository.update_centered_task_allocation_fields(
                linked_id, allocated_time_budget, parent["target_unit"], None, now_utc, conn=conn
            )
            allocation_service._cascade_internal_allocation(
                linked_id,
                allocated_time_budget,
                parent["target_unit"],
                budget_mode,
                snap_group,
                "Linked under '%s'" % parent["name"],
                True,
                now_utc,
                conn,
            )

        new_sum = round(current_weight_sum + (weight_pct if status != "Archived" else 0.0), 4)
        finalized_flag = 1 if abs(new_sum - 100.0) <= 0.01 else 0
        task_repository.update_centered_task_allocation_fields(
            parent_centered_id,
            parent["target_allocation"],
            parent["target_unit"],
            finalized_flag,
            now_utc,
            conn=conn,
        )

        task_repository.insert_status_history(
            {
                "entity_type": "task_item",
                "centered_task_id": parent_centered_id,
                "task_item_id": item_id,
                "entity_name_snapshot": name,
                "from_status": "",
                "to_status": status,
                "reason": "Added internal task (%s)" % item_type,
                "changed_at": now_utc,
            },
            conn=conn,
        )

        task_repository.insert_allocation_snapshot(
            {
                "snapshot_group_id": snap_group,
                "scope": "centered_internal",
                "centered_task_id": parent_centered_id,
                "centered_task_name_snapshot": parent["name"],
                "task_item_id": item_id,
                "task_item_name_snapshot": name,
                "budget_mode": budget_mode,
                "total_budget": float(parent["target_allocation"]),
                "budget_unit": parent["target_unit"],
                "weight_pct": weight_pct,
                "allocated_target": target_quantity,
                "target_unit": target_unit,
                "reason": "Added internal task",
                "is_active": 1,
                "created_at": now_utc,
            },
            conn=conn,
        )

        progress_service._propagate_parent_progress_and_completion(parent_centered_id, now_utc, conn)

        auth_repository.insert_activity_log(
            "tasks",
            "task_item_created",
            "task_item",
            item_id,
            "Added '%s' (%s%%) under '%s'" % (name, weight_pct, parent["name"]),
            now_utc,
            conn=conn,
        )
    return item_id


def update_task_item(item_id, form_data):
    existing = task_repository.get_task_item(item_id)
    if not existing:
        raise ValidationError("Internal task not found.")
    parent = task_repository.get_centered_task(existing["parent_centered_task_id"])

    name = (
        existing["linked_task_name"]
        if existing["item_type"] == "linked_centered" and existing.get("linked_task_name")
        else require_non_empty(form_data.get("name"), "Task name", max_len=140)
    )
    description = clean_optional_text(form_data.get("description"), max_len=2000)
    weight_pct = parse_float(
        form_data.get("weight_pct"), "Weight percentage", min_val=0.0, max_val=100.0, default=existing["weight_pct"]
    )
    target_unit = clean_optional_text(form_data.get("target_unit"), max_len=30) or existing["target_unit"]
    raw_qty = (form_data.get("target_quantity") or "").strip()
    allocated_time_budget = round(float(parent["target_allocation"]) * (weight_pct / 100.0), 4)
    if raw_qty == "":
        target_quantity = allocated_time_budget if target_unit == parent["target_unit"] else existing["target_quantity"]
    else:
        target_quantity = parse_float(raw_qty, "Target quantity", min_val=0.0, max_val=1000000.0)

    start_date = validate_date_str(form_data.get("start_date"), "Start date")
    due_date = validate_date_str(form_data.get("due_date"), "Due date")
    validate_date_order(start_date, due_date, "Start date", "Due date")
    priority = validate_choice(form_data.get("priority"), VALID_PRIORITIES, "Priority", default=existing["priority"])
    status = validate_choice(form_data.get("status"), VALID_TASK_STATUSES, "Status", default=existing["status"])
    notes = clean_optional_text(form_data.get("notes"), max_len=2000)

    siblings = task_repository.list_task_items_by_parent(existing["parent_centered_task_id"], include_archived=False)
    other_sum = sum(float(s["weight_pct"]) for s in siblings if s["id"] != existing["id"])
    if status != "Archived" and other_sum + weight_pct > 100.001:
        remaining = max(0.0, round(100.0 - other_sum, 2))
        raise ValidationError(
            "Setting weight to %.2f%% brings total to %.2f%% (maximum allowed without lowering sibling weights is %.2f%%)."
            % (weight_pct, other_sum + weight_pct, remaining)
        )

    now_utc = utc_now_iso()
    completed_at = existing["completed_at"]
    if status == "Completed" and existing["status"] != "Completed":
        completed_at = now_utc
    elif status != "Completed":
        completed_at = None

    with transaction() as conn:
        task_repository.update_task_item(
            item_id,
            {
                "name": name,
                "description": description,
                "weight_pct": weight_pct,
                "target_quantity": target_quantity,
                "target_unit": target_unit,
                "allocated_time_budget": allocated_time_budget,
                "start_date": start_date,
                "due_date": due_date,
                "priority": priority,
                "status": status,
                "notes": notes,
                "completed_at": completed_at,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        snap_group = uuid.uuid4().hex[:12]
        budget_mode = auth_repository.get_setting("task_budget_mode", "fixed", conn=conn) or "fixed"

        if existing["item_type"] == "linked_centered" and existing["linked_centered_task_id"]:
            task_repository.update_centered_task_allocation_fields(
                existing["linked_centered_task_id"],
                allocated_time_budget,
                parent["target_unit"],
                None,
                now_utc,
                conn=conn,
            )
            if abs(allocated_time_budget - float(existing["allocated_time_budget"])) > 0.0001:
                allocation_service._cascade_internal_allocation(
                    existing["linked_centered_task_id"],
                    allocated_time_budget,
                    parent["target_unit"],
                    budget_mode,
                    snap_group,
                    "Parent item weight updated",
                    True,
                    now_utc,
                    conn,
                )

        if status != existing["status"]:
            task_repository.insert_status_history(
                {
                    "entity_type": "task_item",
                    "centered_task_id": existing["parent_centered_task_id"],
                    "task_item_id": item_id,
                    "entity_name_snapshot": name,
                    "from_status": existing["status"],
                    "to_status": status,
                    "reason": "Updated internal task",
                    "changed_at": now_utc,
                },
                conn=conn,
            )

        if (
            abs(weight_pct - float(existing["weight_pct"])) > 0.0001
            or abs(target_quantity - float(existing["target_quantity"])) > 0.0001
        ):
            task_repository.insert_allocation_snapshot(
                {
                    "snapshot_group_id": snap_group,
                    "scope": "centered_internal",
                    "centered_task_id": existing["parent_centered_task_id"],
                    "centered_task_name_snapshot": parent["name"],
                    "task_item_id": item_id,
                    "task_item_name_snapshot": name,
                    "budget_mode": budget_mode,
                    "total_budget": float(parent["target_allocation"]),
                    "budget_unit": parent["target_unit"],
                    "weight_pct": weight_pct,
                    "allocated_target": target_quantity,
                    "target_unit": target_unit,
                    "reason": "Internal task updated",
                    "is_active": 1,
                    "created_at": now_utc,
                },
                conn=conn,
            )

        new_sum = other_sum + (weight_pct if status != "Archived" else 0.0)
        finalized = 1 if abs(new_sum - 100.0) <= 0.01 else 0
        task_repository.update_centered_task_allocation_fields(
            existing["parent_centered_task_id"],
            parent["target_allocation"],
            parent["target_unit"],
            finalized,
            now_utc,
            conn=conn,
        )

        progress_service._propagate_parent_progress_and_completion(existing["parent_centered_task_id"], now_utc, conn)

        auth_repository.insert_activity_log(
            "tasks", "task_item_updated", "task_item", item_id, "Updated '%s'" % name, now_utc, conn=conn
        )


def delete_task_item(item_id, confirm_force=False, permanent=False):
    existing = task_repository.get_task_item(item_id, include_deleted=permanent)
    if not existing:
        raise ValidationError("Internal task not found.")

    progress_cnt = task_repository.count_task_item_progress_entries(item_id)
    if existing["item_type"] == "standard" and progress_cnt > 0 and not confirm_force:
        raise ValidationError(
            "This task has %d progress entry/entries. Confirm deletion to move it to Trash or archive it instead."
            % progress_cnt
        )

    now_utc = utc_now_iso()
    parent_id = existing["parent_centered_task_id"]
    with transaction() as conn:
        if permanent:
            task_repository.delete_task_item(item_id, conn=conn)
        else:
            task_repository.soft_delete_task_item(item_id, now_utc, conn=conn)

        parent = task_repository.get_centered_task(parent_id, conn=conn)
        siblings = task_repository.list_task_items_by_parent(parent_id, include_archived=False, conn=conn)
        total_w = sum(float(s["weight_pct"]) for s in siblings)
        finalized = 1 if (len(siblings) > 0 and abs(total_w - 100.0) <= 0.01) else 0
        if parent:
            task_repository.update_centered_task_allocation_fields(
                parent_id, parent["target_allocation"], parent["target_unit"], finalized, now_utc, conn=conn
            )
            progress_service._propagate_parent_progress_and_completion(parent_id, now_utc, conn)

        action_label = "task_item_unlinked" if existing["item_type"] == "linked_centered" else (
            "task_item_purged" if permanent else "task_item_deleted"
        )
        auth_repository.insert_activity_log(
            "tasks",
            action_label,
            "task_item",
            item_id,
            "Removed '%s' from '%s'" % (existing["name"], existing["parent_name"]),
            now_utc,
            conn=conn,
        )


def restore_task_item(item_id):
    existing = task_repository.get_task_item(item_id, include_deleted=True)
    if not existing or not existing.get("is_deleted"):
        raise ValidationError("Deleted internal task not found in Trash.")

    parent = task_repository.get_centered_task(existing["parent_centered_task_id"])
    if not parent:
        raise ValidationError("Restore the parent centered task '%s' first." % existing["parent_name"])

    siblings = task_repository.list_task_items_by_parent(existing["parent_centered_task_id"], include_archived=False)
    other_sum = sum(float(s["weight_pct"]) for s in siblings)
    if existing["status"] != "Archived" and other_sum + float(existing["weight_pct"]) > 100.001:
        remaining = max(0.0, round(100.0 - other_sum, 2))
        raise ValidationError(
            "Cannot restore '%s' (%.2f%%): siblings currently allocate %.2f%% (only %.2f%% available)."
            % (existing["name"], float(existing["weight_pct"]), other_sum, remaining)
        )

    now_utc = utc_now_iso()
    with transaction() as conn:
        if existing["item_type"] == "linked_centered" and existing["linked_centered_task_id"]:
            ok, reason = validate_link_candidate(
                existing["parent_centered_task_id"], existing["linked_centered_task_id"], conn=conn
            )
            if not ok:
                raise ValidationError(reason)

        task_repository.restore_task_item(item_id, now_utc, conn=conn)
        updated_siblings = task_repository.list_task_items_by_parent(
            existing["parent_centered_task_id"], include_archived=False, conn=conn
        )
        total_w = sum(float(s["weight_pct"]) for s in updated_siblings)
        finalized = 1 if (len(updated_siblings) > 0 and abs(total_w - 100.0) <= 0.01) else 0
        task_repository.update_centered_task_allocation_fields(
            existing["parent_centered_task_id"],
            parent["target_allocation"],
            parent["target_unit"],
            finalized,
            now_utc,
            conn=conn,
        )
        progress_service._propagate_parent_progress_and_completion(existing["parent_centered_task_id"], now_utc, conn)
        auth_repository.insert_activity_log(
            "tasks",
            "task_item_restored",
            "task_item",
            item_id,
            "Restored '%s' to '%s'" % (existing["name"], parent["name"]),
            now_utc,
            conn=conn,
        )


def clone_centered_task_as_independent(source_id, new_name=None, include_hierarchy=True, preserve_progress=False):
    src = task_repository.get_centered_task(source_id)
    if not src:
        raise ValidationError("Source centered task not found.")
    root_clone_name = require_non_empty(new_name or (src["name"] + " (Copy)"), "Task name", max_len=140)
    now_utc = utc_now_iso()

    with transaction() as conn:
        cloned_map = {}
        visiting = set()

        def clone_ct_recursive(cur_src_id, override_name=None):
            if cur_src_id in cloned_map:
                return cloned_map[cur_src_id]
            s = task_repository.get_centered_task(cur_src_id, conn=conn)
            if not s:
                return None

            visiting.add(cur_src_id)
            ct_name = (override_name or (s["name"] + " (Copy)"))[:140]
            ct_status = s["status"] if preserve_progress else "Not Started"
            ct_completed = s["completed_at"] if preserve_progress else None

            new_ct_id = task_repository.insert_centered_task(
                {
                    "name": ct_name,
                    "description": s["description"],
                    "weight": 0.0,
                    "target_allocation": s["target_allocation"],
                    "target_unit": s["target_unit"],
                    "allocation_mode": s["allocation_mode"],
                    "allocation_finalized": s["allocation_finalized"],
                    "start_date": s["start_date"],
                    "target_end_date": s["target_end_date"],
                    "priority": s["priority"],
                    "status": ct_status,
                    "background_image": s["background_image"],
                    "background_mode": s["background_mode"],
                    "font_family": s["font_family"],
                    "primary_color": s["primary_color"],
                    "accent_color": s["accent_color"],
                    "text_color": s["text_color"],
                    "metadata_json": s["metadata_json"],
                    "is_demo": 0,
                    "completed_at": ct_completed,
                    "created_at": now_utc,
                    "updated_at": now_utc,
                },
                conn=conn,
            )
            cloned_map[cur_src_id] = new_ct_id

            task_repository.insert_status_history(
                {
                    "entity_type": "centered_task",
                    "centered_task_id": new_ct_id,
                    "task_item_id": None,
                    "entity_name_snapshot": ct_name,
                    "from_status": "",
                    "to_status": ct_status,
                    "reason": "Cloned independent centered task",
                    "changed_at": now_utc,
                },
                conn=conn,
            )

            src_items = task_repository.list_task_items_by_parent(cur_src_id, include_archived=False, conn=conn)
            copied_count = 0
            for idx, it in enumerate(src_items):
                if it["item_type"] == "linked_centered" and it["linked_centered_task_id"]:
                    linked_src_id = it["linked_centered_task_id"]
                    if not include_hierarchy or linked_src_id in visiting or linked_src_id in cloned_map:
                        continue
                    linked_ct_src = task_repository.get_centered_task(linked_src_id, conn=conn)
                    if not linked_ct_src or linked_ct_src["status"] == "Archived":
                        continue
                    sub_clone_name = "%s (Copy)" % linked_ct_src["name"]
                    child_clone_id = clone_ct_recursive(linked_src_id, override_name=sub_clone_name)
                    if child_clone_id:
                        it_status = it["status"] if preserve_progress else "Not Started"
                        it_comp = it["completed_at"] if preserve_progress else None
                        task_repository.insert_task_item(
                            {
                                "parent_centered_task_id": new_ct_id,
                                "item_type": "linked_centered",
                                "linked_centered_task_id": child_clone_id,
                                "name": sub_clone_name,
                                "description": it["description"],
                                "weight_pct": it["weight_pct"],
                                "target_quantity": it["target_quantity"],
                                "target_unit": it["target_unit"],
                                "allocated_time_budget": it["allocated_time_budget"],
                                "start_date": it["start_date"],
                                "due_date": it["due_date"],
                                "priority": it["priority"],
                                "status": it_status,
                                "notes": it["notes"],
                                "sort_order": copied_count + 1,
                                "completed_at": it_comp,
                                "created_at": now_utc,
                                "updated_at": now_utc,
                            },
                            conn=conn,
                        )
                        copied_count += 1
                else:
                    it_status = it["status"] if preserve_progress else "Not Started"
                    it_comp = it["completed_at"] if preserve_progress else None
                    new_item_id = task_repository.insert_task_item(
                        {
                            "parent_centered_task_id": new_ct_id,
                            "item_type": "standard",
                            "linked_centered_task_id": None,
                            "name": it["name"],
                            "description": it["description"],
                            "weight_pct": it["weight_pct"],
                            "target_quantity": it["target_quantity"],
                            "target_unit": it["target_unit"],
                            "allocated_time_budget": it["allocated_time_budget"],
                            "start_date": it["start_date"],
                            "due_date": it["due_date"],
                            "priority": it["priority"],
                            "status": it_status,
                            "notes": it["notes"],
                            "sort_order": copied_count + 1,
                            "completed_at": it_comp,
                            "created_at": now_utc,
                            "updated_at": now_utc,
                        },
                        conn=conn,
                    )
                    copied_count += 1
                    if preserve_progress:
                        entries = task_repository.list_progress_entries_for_item(it["id"], conn=conn)
                        for ent in entries:
                            task_repository.insert_progress_entry(
                                {
                                    "task_item_id": new_item_id,
                                    "quantity_completed": ent["quantity_completed"],
                                    "time_spent_minutes": ent["time_spent_minutes"],
                                    "entry_timestamp": ent["entry_timestamp"],
                                    "comments": ent["comments"],
                                    "update_source": ent["update_source"],
                                    "created_at": now_utc,
                                    "updated_at": now_utc,
                                },
                                conn=conn,
                            )

            # Recompute finalized flag based on copied active items
            cloned_items = task_repository.list_task_items_by_parent(new_ct_id, include_archived=False, conn=conn)
            cloned_w = sum(float(ci["weight_pct"]) for ci in cloned_items)
            fin = 1 if (len(cloned_items) > 0 and abs(cloned_w - 100.0) <= 0.01) else 0
            task_repository.update_centered_task_allocation_fields(
                new_ct_id, s["target_allocation"], s["target_unit"], fin, now_utc, conn=conn
            )
            visiting.discard(cur_src_id)
            return new_ct_id

        new_id = clone_ct_recursive(source_id, override_name=root_clone_name)
        auth_repository.insert_activity_log(
            "tasks",
            "centered_task_cloned",
            "centered_task",
            new_id,
            "Cloned independent task '%s' from '%s' (hierarchy=%s, progress=%s)"
            % (root_clone_name, src["name"], include_hierarchy, preserve_progress),
            now_utc,
            conn=conn,
        )
    return new_id


def list_completed_overview():
    metrics_idx = build_task_metrics_index()
    completed_centered = task_repository.list_completed_centered_tasks()
    for ct in completed_centered:
        ct["metrics"] = metrics_idx.get(ct["id"], {})

    completed_items = task_repository.list_completed_task_items()
    totals = task_repository.get_all_item_progress_totals()
    for it in completed_items:
        t = totals.get(it["id"], {"total_quantity": 0.0, "total_time_minutes": 0.0, "entry_count": 0})
        it["actual_quantity"] = round(t["total_quantity"], 2)
        it["actual_time_hours"] = round(t["total_time_minutes"] / 60.0, 2)
        it["entry_count"] = t["entry_count"]

    return {"centered_tasks": completed_centered, "task_items": completed_items}

