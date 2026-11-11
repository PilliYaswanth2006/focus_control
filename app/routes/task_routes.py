from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from app.repositories import task_repository
from app.services import allocation_service, progress_service, task_service
from app.utils.uploads import PRESET_BACKGROUNDS
from app.utils.validation import (
    VALID_FONTS,
    VALID_PRIORITIES,
    VALID_TASK_STATUSES,
    ValidationError,
    validate_date_order,
    validate_date_str,
)


task_bp = Blueprint("tasks", __name__)

TAB_STATUS_MAP = {
    "all": "All",
    "active": "Active",
    "in_progress": "In Progress",
    "completed": "Completed",
    "archived": "Archived",
}
VALID_SORT_OPTIONS = (
    "priority_updated",
    "priority",
    "weight",
    "completion",
    "deadline",
    "updated",
    "name",
)


def _wants_json():
    return request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest"


@task_bp.route("/tasks")
def index():
    tab = (request.args.get("tab") or "all").strip().lower()
    if tab not in TAB_STATUS_MAP:
        tab = "all"
    search = (request.args.get("search") or "").strip()
    priority = (request.args.get("priority") or "All").strip()
    if priority not in ("All",) + VALID_PRIORITIES:
        priority = "All"
    sort_by = (request.args.get("sort_by") or "priority_updated").strip().lower()
    if sort_by not in VALID_SORT_OPTIONS:
        sort_by = "priority_updated"
    overdue_only = request.args.get("overdue_only") in ("1", "true", "on")

    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    try:
        date_from = validate_date_str(date_from, "From date")
        date_to = validate_date_str(date_to, "To date")
        validate_date_order(date_from, date_to, "From date", "To date")
    except ValidationError as exc:
        flash(exc.message, "warning")
        date_from = ""
        date_to = ""

    all_tasks = task_service.list_centered_tasks_with_metrics(
        status=None,
        search=search or None,
        priority=None if priority == "All" else priority,
        sort_by=sort_by,
        date_from=date_from or None,
        date_to=date_to or None,
        overdue_only=overdue_only,
        include_archived=True,
    )
    tab_counts = {
        "all": len([t for t in all_tasks if t["status"] != "Archived"]),
        "active": len([t for t in all_tasks if t["status"] == "Active"]),
        "in_progress": len([t for t in all_tasks if t["status"] == "In Progress"]),
        "completed": len([t for t in all_tasks if t["status"] == "Completed"]),
        "archived": len([t for t in all_tasks if t["status"] == "Archived"]),
    }

    if tab == "all":
        filtered_tasks = [t for t in all_tasks if t["status"] != "Archived"]
    else:
        target_status = TAB_STATUS_MAP[tab]
        filtered_tasks = [t for t in all_tasks if t["status"] == target_status]

    budget = allocation_service.get_budget_overview()
    active_session = task_repository.get_active_session()

    return render_template(
        "tasks/index.html",
        tasks=filtered_tasks,
        tab=tab,
        tab_counts=tab_counts,
        search=search,
        priorities=VALID_PRIORITIES,
        filters={
            "priority": priority,
            "sort_by": sort_by,
            "date_from": date_from,
            "date_to": date_to,
            "overdue_only": overdue_only,
        },
        budget=budget,
        active_session=active_session,
    )


@task_bp.route("/tasks/completed")
def completed():
    overview = task_service.list_completed_overview()
    return render_template("tasks/completed.html", overview=overview)


@task_bp.route("/tasks/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            task_id = task_service.create_centered_task(request.form, bg_file=request.files.get("background_file"))
            flash("Centered task created.", "success")
            return redirect(url_for("tasks.details", task_id=task_id))
        except ValidationError as exc:
            flash(exc.message, "danger")

    budget = allocation_service.get_budget_overview()
    return render_template(
        "tasks/form.html",
        task=None,
        presets=PRESET_BACKGROUNDS,
        fonts=VALID_FONTS,
        priorities=VALID_PRIORITIES,
        statuses=VALID_TASK_STATUSES,
        budget=budget,
    )


@task_bp.route("/tasks/<int:task_id>")
def details(task_id):
    task = task_service.get_centered_task_details(task_id)
    if not task:
        flash("Centered task not found.", "warning")
        return redirect(url_for("tasks.index"))

    budget = allocation_service.get_budget_overview()
    active_session = task_repository.get_active_session()
    return render_template(
        "tasks/details.html",
        task=task,
        budget=budget,
        active_session=active_session,
        priorities=VALID_PRIORITIES,
        statuses=VALID_TASK_STATUSES,
    )


@task_bp.route("/tasks/<int:task_id>/edit", methods=["GET", "POST"])
def edit(task_id):
    task = task_service.get_centered_task_details(task_id)
    if not task:
        flash("Centered task not found.", "warning")
        return redirect(url_for("tasks.index"))

    if request.method == "POST":
        try:
            task_service.update_centered_task(task_id, request.form, bg_file=request.files.get("background_file"))
            flash("Centered task updated.", "success")
            return redirect(url_for("tasks.details", task_id=task_id))
        except ValidationError as exc:
            flash(exc.message, "danger")

    budget = allocation_service.get_budget_overview()
    return render_template(
        "tasks/form.html",
        task=task,
        presets=PRESET_BACKGROUNDS,
        fonts=VALID_FONTS,
        priorities=VALID_PRIORITIES,
        statuses=VALID_TASK_STATUSES,
        budget=budget,
    )


@task_bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
def delete(task_id):
    confirm_force = request.form.get("confirm_force") in ("1", "true", "on")
    permanent = request.form.get("permanent") in ("1", "true", "on")
    try:
        task_service.delete_centered_task(task_id, confirm_force=confirm_force, permanent=permanent)
        flash(
            "Centered task permanently deleted."
            if permanent
            else "Centered task moved to Trash (recoverable from Settings).",
            "success",
        )
        if permanent and request.referrer and "/settings" in request.referrer:
            return redirect(url_for("settings.index"))
        return redirect(url_for("tasks.index"))
    except ValidationError as exc:
        flash(exc.message, "danger")
        return redirect(request.referrer or url_for("tasks.details", task_id=task_id))


@task_bp.route("/tasks/<int:task_id>/restore", methods=["POST"])
def restore(task_id):
    try:
        weight_adjusted = task_service.restore_centered_task(task_id)
        if weight_adjusted:
            flash("Centered task restored from Trash (weight capped to fit remaining 100% top-level budget).", "info")
        else:
            flash("Centered task restored from Trash.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.details", task_id=task_id))


@task_bp.route("/tasks/<int:task_id>/status", methods=["POST"])
def change_status(task_id):
    try:
        task_service.transition_centered_task_status(
            task_id, request.form.get("status"), request.form.get("reason", "")
        )
        flash("Task status updated.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.details", task_id=task_id))


@task_bp.route("/tasks/<int:task_id>/reopen", methods=["POST"])
def reopen_centered(task_id):
    try:
        progress_service.reopen_centered_task(task_id, request.form.get("reason", ""))
        flash("Centered task reopened with historical status record.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.details", task_id=task_id))


@task_bp.route("/tasks/<int:task_id>/clone", methods=["POST"])
def clone_centered(task_id):
    if "include_hierarchy_submitted" in request.form:
        include_hierarchy = "include_hierarchy" in request.form
    else:
        include_hierarchy = str(request.form.get("include_hierarchy", "1")).lower() in ("1", "true", "on", "yes")
    preserve_progress = str(request.form.get("preserve_progress", "0")).lower() in ("1", "true", "on", "yes")
    try:
        new_id = task_service.clone_centered_task_as_independent(
            task_id,
            new_name=request.form.get("new_name"),
            include_hierarchy=include_hierarchy,
            preserve_progress=preserve_progress,
        )
        flash("Created a new independent copy of this centered task.", "success")
        return redirect(url_for("tasks.details", task_id=new_id))
    except ValidationError as exc:
        flash(exc.message, "danger")
        return redirect(url_for("tasks.details", task_id=task_id))


@task_bp.route("/tasks/budget", methods=["POST"])
def update_budget():
    try:
        action_type = request.form.get("action_type", "apply_budget")
        confirm_comp = request.form.get("confirm_redistribute_completed") in ("1", "true", "on")
        if action_type == "finalize_root_weights":
            weights_map = {}
            for key, val in request.form.items():
                if key.startswith("weight_"):
                    weights_map[key.replace("weight_", "", 1)] = val
            allocation_service.update_root_centered_weights_and_finalize(
                weights_map,
                request.form.get("budget_mode", "fixed"),
                request.form.get("total_budget"),
                request.form.get("budget_unit", "hours"),
                confirm_redistribute_completed=confirm_comp,
            )
            flash("Top-level weights finalized (100%) and budget targets recalculated.", "success")
        else:
            policy = "recalculate" if confirm_comp else request.form.get("completed_policy", "preserve")
            allocation_service.apply_global_budget(
                request.form.get("budget_mode", "fixed"),
                request.form.get("total_budget"),
                request.form.get("budget_unit", "hours"),
                completed_policy=policy,
                confirm_redistribute_completed=confirm_comp,
                reason=request.form.get("reason", ""),
            )
            flash("Time budget allocation updated and historical snapshot saved.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.index"))


@task_bp.route("/tasks/<int:task_id>/items/add", methods=["POST"])
def add_item(task_id):
    try:
        task_service.add_internal_task_item(task_id, request.form)
        flash("Internal task added.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("tasks.details", task_id=task_id))


@task_bp.route("/tasks/<int:task_id>/finalize-weights", methods=["POST"])
def finalize_weights(task_id):
    weights_map = {}
    for key, val in request.form.items():
        if key.startswith("item_weight_"):
            weights_map[key.replace("item_weight_", "", 1)] = val
    confirm_comp = request.form.get("confirm_update_completed") in ("1", "true", "on")
    try:
        allocation_service.finalize_internal_allocation(
            task_id,
            weights_by_item_id=weights_map or None,
            confirm_update_completed=confirm_comp,
            reason=request.form.get("reason", ""),
        )
        flash("Internal weights finalized at 100% and snapshot recorded.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("tasks.details", task_id=task_id))


# ============================================================================
# INTERNAL TASK ITEMS & PROGRESS ENTRIES
# ============================================================================

@task_bp.route("/task-items/<int:item_id>")
def item_details(item_id):
    item = task_service.get_task_item_details(item_id)
    if not item:
        flash("Internal task not found.", "warning")
        return redirect(url_for("tasks.index"))
    return render_template(
        "tasks/item_details.html",
        item=item,
        priorities=VALID_PRIORITIES,
        statuses=VALID_TASK_STATUSES,
    )


@task_bp.route("/task-items/<int:item_id>/edit", methods=["POST"])
def edit_item(item_id):
    item = task_repository.get_task_item(item_id)
    if not item:
        flash("Internal task not found.", "warning")
        return redirect(url_for("tasks.index"))
    try:
        task_service.update_task_item(item_id, request.form)
        flash("Internal task updated.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.item_details", item_id=item_id))


@task_bp.route("/task-items/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id):
    permanent = request.form.get("permanent") in ("1", "true", "on")
    item = task_repository.get_task_item(item_id, include_deleted=permanent)
    if not item:
        flash("Internal task not found.", "warning")
        return redirect(url_for("tasks.index"))
    parent_id = item["parent_centered_task_id"]
    confirm_force = request.form.get("confirm_force") in ("1", "true", "on")
    try:
        task_service.delete_task_item(item_id, confirm_force=confirm_force, permanent=permanent)
        flash(
            "Internal task permanently deleted."
            if permanent
            else "Internal task moved to Trash (recoverable from Settings).",
            "success",
        )
        if permanent and request.referrer and "/settings" in request.referrer:
            return redirect(url_for("settings.index"))
        return redirect(url_for("tasks.details", task_id=parent_id))
    except ValidationError as exc:
        flash(exc.message, "danger")
        return redirect(request.referrer or url_for("tasks.item_details", item_id=item_id))


@task_bp.route("/task-items/<int:item_id>/restore", methods=["POST"])
def restore_item(item_id):
    item = task_repository.get_task_item(item_id, include_deleted=True)
    if not item:
        flash("Internal task not found in Trash.", "warning")
        return redirect(url_for("settings.index"))
    try:
        task_service.restore_task_item(item_id)
        flash("Internal task restored from Trash.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.item_details", item_id=item_id))


@task_bp.route("/task-items/<int:item_id>/reopen", methods=["POST"])
def reopen_item(item_id):
    try:
        progress_service.reopen_task_item(
            item_id,
            reason=request.form.get("reason", ""),
            new_target_quantity=request.form.get("new_target_quantity"),
        )
        flash("Task reopened and historical status logged.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.item_details", item_id=item_id))


@task_bp.route("/task-items/<int:item_id>/progress", methods=["POST"])
def add_progress(item_id):
    payload = request.get_json(silent=True) if request.is_json else request.form
    try:
        entry_id = progress_service.add_progress_entry(item_id, payload)
        if _wants_json():
            return jsonify({"ok": True, "entry_id": entry_id})
        flash("Progress recorded.", "success")
    except ValidationError as exc:
        if _wants_json():
            return jsonify({"ok": False, "error": exc.message}), 400
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.item_details", item_id=item_id))


@task_bp.route("/progress-entries/<int:entry_id>/edit", methods=["POST"])
def edit_progress(entry_id):
    entry = task_repository.get_progress_entry(entry_id)
    if not entry:
        flash("Progress entry not found.", "warning")
        return redirect(url_for("tasks.index"))
    try:
        progress_service.update_progress_entry(entry_id, request.form)
        flash("Progress entry updated.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.item_details", item_id=entry["task_item_id"]))


@task_bp.route("/progress-entries/<int:entry_id>/delete", methods=["POST"])
def delete_progress(entry_id):
    entry = task_repository.get_progress_entry(entry_id)
    if not entry:
        flash("Progress entry not found.", "warning")
        return redirect(url_for("tasks.index"))
    item_id = entry["task_item_id"]
    try:
        progress_service.delete_progress_entry(entry_id)
        flash("Progress entry deleted.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.item_details", item_id=item_id))


@task_bp.route("/task-items/<int:item_id>/sessions/start", methods=["POST"])
def start_session(item_id):
    try:
        progress_service.start_focus_session(item_id, request.form.get("notes", ""))
        flash("Focus session timer started.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.item_details", item_id=item_id))


@task_bp.route("/task-sessions/<int:session_id>/stop", methods=["POST"])
def stop_session(session_id):
    cancel = request.form.get("cancel") in ("1", "true")
    log_progress = request.form.get("log_progress", "1") in ("1", "true", "on")
    try:
        progress_service.stop_focus_session(
            session_id,
            quantity_completed=request.form.get("quantity_completed"),
            notes=request.form.get("notes", ""),
            log_progress=log_progress,
            cancel=cancel,
        )
        flash("Focus session cancelled." if cancel else "Focus session saved.", "info" if cancel else "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("tasks.index"))
