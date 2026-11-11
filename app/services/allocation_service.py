import uuid
from app.database.transaction import transaction
from app.repositories import auth_repository, task_repository
from app.utils.time_utils import utc_now_iso
from app.utils.validation import ValidationError, parse_float, validate_choice


def get_budget_overview():
    mode = auth_repository.get_setting("task_budget_mode", "fixed") or "fixed"
    total_budget = float(auth_repository.get_setting("task_total_budget", "40") or 40)
    budget_unit = auth_repository.get_setting("task_budget_unit", "hours") or "hours"
    roots = task_repository.list_root_centered_tasks(include_archived=False)
    budgeted_roots = [r for r in roots if r["allocation_mode"] == "budgeted"]
    manual_roots = [r for r in roots if r["allocation_mode"] != "budgeted"]
    total_weight = round(sum(float(r["weight"]) for r in budgeted_roots), 2)
    remaining_weight = round(max(0.0, 100.0 - total_weight), 2)
    over_weight = round(max(0.0, total_weight - 100.0), 2)
    allocated_budget = round(total_budget * (total_weight / 100.0), 2)
    available_budget = round(max(0.0, total_budget - allocated_budget), 2)
    completed_roots = [r for r in budgeted_roots if r["status"] == "Completed"]
    return {
        "mode": mode,
        "total_budget": total_budget,
        "budget_unit": budget_unit,
        "root_tasks": roots,
        "budgeted_roots": budgeted_roots,
        "manual_roots": manual_roots,
        "budgeted_root_weight_sum": total_weight,
        "remaining_unallocated_weight": remaining_weight,
        "over_allocated_weight": over_weight,
        "allocated_budget": allocated_budget,
        "available_budget": available_budget,
        "weights_exact_100": len(budgeted_roots) > 0 and abs(total_weight - 100.0) <= 0.01,
        "completed_root_names": [r["name"] for r in completed_roots],
    }



def _cascade_internal_allocation(centered_task_id, parent_target, budget_unit, budget_mode, snap_group,
                                 reason, preserve_completed, now_utc, conn, visited=None):
    if visited is None:
        visited = set()
    if centered_task_id in visited:
        return
    visited.add(centered_task_id)

    parent = task_repository.get_centered_task(centered_task_id, conn=conn)
    if not parent:
        return

    items = task_repository.list_task_items_by_parent(centered_task_id, include_archived=False, conn=conn)
    if not items:
        return

    task_repository.deactivate_allocations("centered_internal", centered_task_id=centered_task_id, conn=conn)
    for item in items:
        if preserve_completed and item["status"] == "Completed":
            # Preserve completed item target untouched, still record active snapshot of preserved state
            alloc_time = float(item["allocated_time_budget"])
            target_qty = float(item["target_quantity"])
            snap_reason = reason + " (completed target preserved)"
        else:
            alloc_time = round(float(parent_target) * (float(item["weight_pct"]) / 100.0), 4)
            target_qty = alloc_time if item["target_unit"] == budget_unit else float(item["target_quantity"])
            task_repository.update_task_item_allocation(
                item["id"], float(item["weight_pct"]), alloc_time, target_qty, now_utc, conn=conn
            )
            snap_reason = reason

        task_repository.insert_allocation_snapshot(
            {
                "snapshot_group_id": snap_group,
                "scope": "centered_internal",
                "centered_task_id": centered_task_id,
                "centered_task_name_snapshot": parent["name"],
                "task_item_id": item["id"],
                "task_item_name_snapshot": item["name"],
                "budget_mode": budget_mode,
                "total_budget": float(parent_target),
                "budget_unit": budget_unit,
                "weight_pct": float(item["weight_pct"]),
                "allocated_target": target_qty,
                "target_unit": item["target_unit"],
                "reason": snap_reason,
                "is_active": 1,
                "created_at": now_utc,
            },
            conn=conn,
        )

        if item["item_type"] == "linked_centered" and item["linked_centered_task_id"]:
            linked_ct = task_repository.get_centered_task(item["linked_centered_task_id"], conn=conn)
            if linked_ct and not (preserve_completed and linked_ct["status"] == "Completed"):
                task_repository.update_centered_task_allocation_fields(
                    linked_ct["id"], alloc_time, budget_unit, None, now_utc, conn=conn
                )
                _cascade_internal_allocation(
                    linked_ct["id"], alloc_time, budget_unit, budget_mode, snap_group,
                    reason, preserve_completed, now_utc, conn, visited
                )


def apply_global_budget(mode, total_budget_val, budget_unit, completed_policy="preserve",
                        confirm_redistribute_completed=False, reason=""):
    mode_clean = validate_choice(mode, ("fixed", "dynamic"), "Budget mode", default="fixed")
    total_budget = parse_float(total_budget_val, "Total budget", min_val=0.0, max_val=100000.0)
    unit_clean = (budget_unit or "hours").strip() or "hours"
    policy = validate_choice(completed_policy, ("preserve", "recalculate", "ask"), "Completed policy", default="preserve")

    roots = task_repository.list_root_centered_tasks(include_archived=False)
    budgeted_roots = [r for r in roots if r["allocation_mode"] == "budgeted"]
    completed_roots = [r for r in budgeted_roots if r["status"] == "Completed"]

    if completed_roots and policy == "ask" and not confirm_redistribute_completed:
        raise ValidationError(
            "Completed task(s) detected (%s). Confirm whether to preserve completed targets or recalculate all."
            % ", ".join(r["name"] for r in completed_roots)
        )

    preserve_completed = not (policy == "recalculate" and confirm_redistribute_completed)
    now_utc = utc_now_iso()
    snap_group = uuid.uuid4().hex[:12]
    reason_text = (reason or "").strip() or ("Global %s budget set to %s %s" % (mode_clean, total_budget, unit_clean))

    with transaction() as conn:
        auth_repository.upsert_setting("task_budget_mode", mode_clean, now_utc, conn=conn)
        auth_repository.upsert_setting("task_total_budget", str(total_budget), now_utc, conn=conn)
        auth_repository.upsert_setting("task_budget_unit", unit_clean, now_utc, conn=conn)

        task_repository.deactivate_allocations("global_budget", centered_task_id=None, conn=conn)

        for ct in budgeted_roots:
            if preserve_completed and ct["status"] == "Completed":
                new_target = float(ct["target_allocation"])
                ct_reason = reason_text + " (completed target preserved)"
            else:
                new_target = round(total_budget * (float(ct["weight"]) / 100.0), 4)
                task_repository.update_centered_task_allocation_fields(
                    ct["id"], new_target, unit_clean, None, now_utc, conn=conn
                )
                ct_reason = reason_text

            task_repository.insert_allocation_snapshot(
                {
                    "snapshot_group_id": snap_group,
                    "scope": "global_budget",
                    "centered_task_id": ct["id"],
                    "centered_task_name_snapshot": ct["name"],
                    "task_item_id": None,
                    "task_item_name_snapshot": "",
                    "budget_mode": mode_clean,
                    "total_budget": total_budget,
                    "budget_unit": unit_clean,
                    "weight_pct": float(ct["weight"]),
                    "allocated_target": new_target,
                    "target_unit": unit_clean,
                    "reason": ct_reason,
                    "is_active": 1,
                    "created_at": now_utc,
                },
                conn=conn,
            )

            _cascade_internal_allocation(
                ct["id"], new_target, unit_clean, mode_clean, snap_group,
                reason_text, preserve_completed, now_utc, conn
            )

        auth_repository.insert_activity_log(
            "tasks",
            "budget_recalculated",
            "app_settings",
            None,
            "%s (preserve_completed=%s)" % (reason_text, preserve_completed),
            now_utc,
            conn=conn,
        )

    return get_budget_overview()


def update_root_centered_weights_and_finalize(weights_by_id, mode, total_budget_val, budget_unit,
                                              confirm_redistribute_completed=False):
    """Bulk update root centered task weights, validate they equal 100%, and apply budget."""
    roots = task_repository.list_root_centered_tasks(include_archived=False)
    budgeted_roots = [r for r in roots if r["allocation_mode"] == "budgeted"]
    if not budgeted_roots:
        raise ValidationError("No budgeted root centered tasks found to finalize.")

    parsed_weights = {}
    total_w = 0.0
    for ct in budgeted_roots:
        w = parse_float(weights_by_id.get(str(ct["id"]), ct["weight"]), "Weight for %s" % ct["name"], min_val=0.0, max_val=100.0)
        parsed_weights[ct["id"]] = w
        total_w += w

    if abs(total_w - 100.0) > 0.01:
        diff = round(100.0 - total_w, 2)
        explain = "%.2f%% remaining" % diff if diff > 0 else "%.2f%% over 100%%" % abs(diff)
        raise ValidationError(
            "Top-level budgeted task weights must total exactly 100%%. Current total is %.2f%% (%s)."
            % (total_w, explain)
        )

    now_utc = utc_now_iso()
    with transaction() as conn:
        for ct in budgeted_roots:
            ct_data = dict(ct)
            ct_data["weight"] = parsed_weights[ct["id"]]
            ct_data["updated_at"] = now_utc
            task_repository.update_centered_task(ct["id"], ct_data, conn=conn)

        apply_global_budget(
            mode,
            total_budget_val,
            budget_unit,
            completed_policy="recalculate" if confirm_redistribute_completed else "preserve",
            confirm_redistribute_completed=confirm_redistribute_completed,
            reason="Finalized top-level weights (100%)",
        )


def finalize_internal_allocation(centered_task_id, weights_by_item_id=None,
                                 confirm_update_completed=False, reason=""):
    parent = task_repository.get_centered_task(centered_task_id)
    if not parent:
        raise ValidationError("Centered task not found.")

    items = task_repository.list_task_items_by_parent(centered_task_id, include_archived=False)
    if not items:
        raise ValidationError("Add at least one internal task before finalizing weight allocation.")

    new_weights = {}
    total_w = 0.0
    for it in items:
        raw_w = weights_by_item_id.get(str(it["id"]), it["weight_pct"]) if weights_by_item_id else it["weight_pct"]
        w = parse_float(raw_w, "Weight for '%s'" % it["name"], min_val=0.0, max_val=100.0)
        new_weights[it["id"]] = w
        total_w += w

    if abs(total_w - 100.0) > 0.01:
        diff = round(100.0 - total_w, 2)
        explain = "%.2f%% remaining to allocate" % diff if diff > 0 else "%.2f%% over 100%%" % abs(diff)
        raise ValidationError(
            "Cannot finalize allocation: internal task weights must total exactly 100%%. Current total is %.2f%% (%s)."
            % (total_w, explain)
        )

    completed_affected = [
        it for it in items
        if it["status"] == "Completed" and abs(new_weights[it["id"]] - float(it["weight_pct"])) > 0.001
    ]
    if completed_affected and not confirm_update_completed:
        raise ValidationError(
            "Completed task(s) (%s) would have their weight/target altered. Please confirm updating completed tasks or keep their existing weights."
            % ", ".join(it["name"] for it in completed_affected)
        )

    now_utc = utc_now_iso()
    snap_group = uuid.uuid4().hex[:12]
    budget_mode = auth_repository.get_setting("task_budget_mode", "fixed") or "fixed"
    reason_text = (reason or "").strip() or "Finalized 100% internal weight allocation"
    preserve_completed = not confirm_update_completed

    with transaction() as conn:
        for it in items:
            w = new_weights[it["id"]]
            if preserve_completed and it["status"] == "Completed":
                alloc_time = float(it["allocated_time_budget"])
                target_qty = float(it["target_quantity"])
            else:
                alloc_time = round(float(parent["target_allocation"]) * (w / 100.0), 4)
                target_qty = alloc_time if it["target_unit"] == parent["target_unit"] else float(it["target_quantity"])
            task_repository.update_task_item_allocation(it["id"], w, alloc_time, target_qty, now_utc, conn=conn)

        task_repository.update_centered_task_allocation_fields(
            centered_task_id, float(parent["target_allocation"]), parent["target_unit"], 1, now_utc, conn=conn
        )

        _cascade_internal_allocation(
            centered_task_id,
            float(parent["target_allocation"]),
            parent["target_unit"],
            budget_mode,
            snap_group,
            reason_text,
            preserve_completed,
            now_utc,
            conn,
        )

        auth_repository.insert_activity_log(
            "tasks",
            "internal_allocation_finalized",
            "centered_task",
            centered_task_id,
            "Finalized 100%% allocation for '%s'" % parent["name"],
            now_utc,
            conn=conn,
        )
