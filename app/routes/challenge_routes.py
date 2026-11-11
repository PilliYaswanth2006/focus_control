from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from app.repositories import challenge_repository
from app.services import challenge_service
from app.services.challenge_service import VALID_FONT_SIZES
from app.utils.uploads import PRESET_BACKGROUNDS
from app.utils.validation import (
    PREDEFINED_TRIGGERS,
    VALID_CARD_STYLES,
    VALID_CHALLENGE_STATUSES,
    VALID_FONTS,
    VALID_LAYOUT_STYLES,
    ValidationError,
    validate_date_order,
    validate_date_str,
)


challenge_bp = Blueprint("challenges", __name__)


def _wants_json():
    return request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest"


@challenge_bp.route("/challenges")
def index():
    status = (request.args.get("status") or "All").strip()
    if status not in ("All",) + VALID_CHALLENGE_STATUSES:
        status = "All"
    search = (request.args.get("search") or "").strip()

    all_challenges = challenge_service.list_challenges_with_metrics(
        status=None, search=search or None, include_archived=True
    )
    counts = {
        "All": len([c for c in all_challenges if c["status"] != "Archived"]),
        "Active": len([c for c in all_challenges if c["status"] == "Active"]),
        "Paused": len([c for c in all_challenges if c["status"] == "Paused"]),
        "Not Started": len([c for c in all_challenges if c["status"] == "Not Started"]),
        "Completed": len([c for c in all_challenges if c["status"] == "Completed"]),
        "Archived": len([c for c in all_challenges if c["status"] == "Archived"]),
    }

    if status == "All":
        visible = [c for c in all_challenges if c["status"] != "Archived"]
    else:
        visible = [c for c in all_challenges if c["status"] == status]

    return render_template(
        "challenges/index.html",
        challenges=visible,
        status=status,
        counts=counts,
        search=search,
    )


@challenge_bp.route("/challenges/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            cid = challenge_service.create_challenge(request.form, bg_file=request.files.get("background_file"))
            flash("Challenge created.", "success")
            return redirect(url_for("challenges.details", challenge_id=cid))
        except ValidationError as exc:
            flash(exc.message, "danger")

    return render_template(
        "challenges/form.html",
        challenge=None,
        presets=PRESET_BACKGROUNDS,
        fonts=VALID_FONTS,
        font_sizes=VALID_FONT_SIZES,
        card_styles=VALID_CARD_STYLES,
        layout_styles=VALID_LAYOUT_STYLES,
    )


@challenge_bp.route("/challenges/<int:challenge_id>")
def details(challenge_id):
    cycle_id = (request.args.get("cycle_id") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    try:
        start_date = validate_date_str(start_date, "Start date")
        end_date = validate_date_str(end_date, "End date")
        validate_date_order(start_date, end_date, "Start date", "End date")
    except ValidationError as exc:
        flash(exc.message, "warning")
        start_date = ""
        end_date = ""

    ch = challenge_service.get_challenge_details(
        challenge_id,
        cycle_id=cycle_id or None,
        start_date=start_date or None,
        end_date=end_date or None,
    )
    if not ch:
        flash("Challenge not found.", "warning")
        return redirect(url_for("challenges.index"))

    return render_template(
        "challenges/details.html",
        challenge=ch,
        predefined_triggers=PREDEFINED_TRIGGERS,
        cycle_filter=cycle_id,
        start_date=start_date,
        end_date=end_date,
    )


@challenge_bp.route("/challenges/<int:challenge_id>/edit", methods=["GET", "POST"])
def edit(challenge_id):
    ch = challenge_service.get_challenge_details(challenge_id)
    if not ch:
        flash("Challenge not found.", "warning")
        return redirect(url_for("challenges.index"))

    if request.method == "POST":
        try:
            challenge_service.update_challenge(challenge_id, request.form, bg_file=request.files.get("background_file"))
            flash("Challenge updated.", "success")
            return redirect(url_for("challenges.details", challenge_id=challenge_id))
        except ValidationError as exc:
            flash(exc.message, "danger")

    return render_template(
        "challenges/form.html",
        challenge=ch,
        presets=PRESET_BACKGROUNDS,
        fonts=VALID_FONTS,
        font_sizes=VALID_FONT_SIZES,
        card_styles=VALID_CARD_STYLES,
        layout_styles=VALID_LAYOUT_STYLES,
    )


@challenge_bp.route("/challenges/<int:challenge_id>/start", methods=["POST"])
def start(challenge_id):
    try:
        challenge_service.start_challenge(challenge_id)
        flash("Challenge started.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/challenges/<int:challenge_id>/pause", methods=["POST"])
def pause(challenge_id):
    try:
        challenge_service.pause_challenge(challenge_id)
        flash("Challenge paused.", "info")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/challenges/<int:challenge_id>/resume", methods=["POST"])
def resume(challenge_id):
    try:
        challenge_service.resume_challenge(challenge_id)
        flash("Challenge resumed.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/challenges/<int:challenge_id>/reset", methods=["POST"])
def reset(challenge_id):
    try:
        challenge_service.reset_challenge(challenge_id, request.form.get("reset_reason", ""))
        flash("New challenge cycle started. All previous historical records remain preserved.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/challenges/<int:challenge_id>/complete", methods=["POST"])
def complete(challenge_id):
    try:
        challenge_service.complete_challenge(challenge_id)
        flash("Challenge marked as Completed!", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/challenges/<int:challenge_id>/archive", methods=["POST"])
def archive(challenge_id):
    unarchive = request.form.get("unarchive") in ("1", "true")
    try:
        challenge_service.archive_challenge(challenge_id, unarchive=unarchive)
        flash("Challenge unarchived." if unarchive else "Challenge archived.", "info")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.index"))


@challenge_bp.route("/challenges/<int:challenge_id>/delete", methods=["POST"])
def delete(challenge_id):
    confirm_force = request.form.get("confirm_force") in ("1", "true", "on")
    permanent = request.form.get("permanent") in ("1", "true", "on")
    try:
        challenge_service.delete_challenge(challenge_id, confirm_force=confirm_force, permanent=permanent)
        flash(
            "Challenge permanently deleted."
            if permanent
            else "Challenge moved to Trash (recoverable from Settings).",
            "success",
        )
        if permanent and request.referrer and "/settings" in request.referrer:
            return redirect(url_for("settings.index"))
        return redirect(url_for("challenges.index"))
    except ValidationError as exc:
        flash(exc.message, "danger")
        return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/challenges/<int:challenge_id>/restore", methods=["POST"])
def restore(challenge_id):
    try:
        challenge_service.restore_challenge(challenge_id)
        flash("Challenge restored from Trash.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/challenges/<int:challenge_id>/events", methods=["POST"])
def record_event(challenge_id):
    payload = request.get_json(silent=True) if request.is_json else request.form
    try:
        event_id = challenge_service.record_event(challenge_id, payload)
        if _wants_json():
            return jsonify({"ok": True, "event_id": event_id})
        flash("Event recorded.", "success")
    except ValidationError as exc:
        if _wants_json():
            return jsonify({"ok": False, "error": exc.message}), 400
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=challenge_id))


@challenge_bp.route("/events/<int:event_id>/edit", methods=["POST"])
def edit_event(event_id):
    ev = challenge_repository.get_event(event_id)
    if not ev:
        flash("Event not found.", "warning")
        return redirect(url_for("challenges.index"))
    try:
        challenge_service.update_event(event_id, request.form)
        flash("Event updated (historical timestamps preserved unless modified).", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=ev["challenge_id"]))


@challenge_bp.route("/events/<int:event_id>/resolve", methods=["POST"])
def resolve_event(event_id):
    ev = challenge_repository.get_event(event_id)
    if not ev:
        if _wants_json():
            return jsonify({"ok": False, "error": "Event not found."}), 404
        flash("Event not found.", "warning")
        return redirect(url_for("challenges.index"))
    payload = request.get_json(silent=True) if request.is_json else request.form
    try:
        challenge_service.resolve_pending_urge(event_id, payload.get("outcome"))
        if _wants_json():
            return jsonify({"ok": True})
        flash("Urge outcome updated.", "success")
    except ValidationError as exc:
        if _wants_json():
            return jsonify({"ok": False, "error": exc.message}), 400
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=ev["challenge_id"]))


@challenge_bp.route("/events/<int:event_id>/delete", methods=["POST"])
def delete_event(event_id):
    permanent = request.form.get("permanent") in ("1", "true", "on")
    ev = challenge_repository.get_event(event_id, include_deleted=permanent)
    if not ev:
        flash("Event not found.", "warning")
        return redirect(url_for("challenges.index"))
    cid = ev["challenge_id"]
    try:
        challenge_service.delete_event(event_id, permanent=permanent)
        flash("Event permanently deleted." if permanent else "Event moved to Trash.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=cid))


@challenge_bp.route("/events/<int:event_id>/restore", methods=["POST"])
def restore_event(event_id):
    ev = challenge_repository.get_event(event_id, include_deleted=True)
    if not ev:
        flash("Event not found in Trash.", "warning")
        return redirect(url_for("challenges.index"))
    cid = ev["challenge_id"]
    try:
        challenge_service.restore_event(event_id)
        flash("Event restored from Trash.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(request.referrer or url_for("challenges.details", challenge_id=cid))


@challenge_bp.route("/challenges/<int:challenge_id>/daily")
def daily_tracking(challenge_id):
    sel_date = (request.args.get("date") or "").strip()
    try:
        sel_date = validate_date_str(sel_date, "Selected date")
    except ValidationError as exc:
        flash(exc.message, "warning")
        sel_date = ""
    data = challenge_service.get_daily_tracking_data(challenge_id, selected_date=sel_date or None)
    if not data:
        flash("Challenge not found.", "warning")
        return redirect(url_for("challenges.index"))
    return render_template("challenges/daily_tracking.html", data=data)


@challenge_bp.route("/challenges/<int:challenge_id>/daily/record", methods=["POST"])
def save_daily_record(challenge_id):
    rec_date = (request.form.get("record_date") or "").strip()
    try:
        challenge_service.save_daily_record(
            challenge_id,
            rec_date,
            request.form.get("reflection"),
            request.form.get("mood"),
            request.form.get("context"),
        )
        flash("Daily summary saved.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(
        request.referrer or url_for("challenges.daily_tracking", challenge_id=challenge_id, date=rec_date or None)
    )


@challenge_bp.route("/challenges/<int:challenge_id>/daily/reflections", methods=["POST"])
def add_daily_reflection(challenge_id):
    rec_date = (request.form.get("record_date") or "").strip()
    try:
        challenge_service.add_daily_reflection(
            challenge_id,
            rec_date,
            request.form.get("title"),
            request.form.get("reflection_text"),
            request.form.get("mood"),
            request.form.get("context"),
        )
        flash("Reflection entry added.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(
        request.referrer or url_for("challenges.daily_tracking", challenge_id=challenge_id, date=rec_date or None)
    )


@challenge_bp.route("/daily-reflections/<int:reflection_id>/edit", methods=["POST"])
def edit_daily_reflection(reflection_id):
    rf = challenge_repository.get_daily_reflection(reflection_id)
    if not rf:
        flash("Reflection not found.", "warning")
        return redirect(url_for("challenges.index"))
    try:
        challenge_service.edit_daily_reflection(
            reflection_id,
            request.form.get("title"),
            request.form.get("reflection_text"),
            request.form.get("mood"),
            request.form.get("context"),
        )
        flash("Reflection updated.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(
        request.referrer
        or url_for("challenges.daily_tracking", challenge_id=rf["challenge_id"], date=rf["record_date"])
    )


@challenge_bp.route("/daily-reflections/<int:reflection_id>/delete", methods=["POST"])
def delete_daily_reflection(reflection_id):
    rf = challenge_repository.get_daily_reflection(reflection_id)
    if not rf:
        flash("Reflection not found.", "warning")
        return redirect(url_for("challenges.index"))
    cid = rf["challenge_id"]
    rec_date = rf["record_date"]
    try:
        challenge_service.delete_daily_reflection(reflection_id)
        flash("Reflection deleted.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(
        request.referrer or url_for("challenges.daily_tracking", challenge_id=cid, date=rec_date)
    )


@challenge_bp.route("/challenges/<int:challenge_id>/daily/comments", methods=["POST"])
def add_daily_comment(challenge_id):
    rec_date = (request.form.get("record_date") or "").strip()
    try:
        challenge_service.add_daily_comment(
            challenge_id,
            rec_date,
            request.form.get("comment_text"),
        )
        flash("Daily comment added.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(
        request.referrer or url_for("challenges.daily_tracking", challenge_id=challenge_id, date=rec_date or None)
    )


@challenge_bp.route("/challenge-comments/<int:comment_id>/edit", methods=["POST"])
def edit_daily_comment(comment_id):
    cmt = challenge_repository.get_comment(comment_id)
    if not cmt:
        flash("Comment not found.", "warning")
        return redirect(url_for("challenges.index"))
    try:
        challenge_service.edit_daily_comment(comment_id, request.form.get("comment_text"))
        flash("Comment updated.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(
        request.referrer
        or url_for("challenges.daily_tracking", challenge_id=cmt["challenge_id"], date=cmt["record_date"])
    )


@challenge_bp.route("/challenge-comments/<int:comment_id>/delete", methods=["POST"])
def delete_daily_comment(comment_id):
    cmt = challenge_repository.get_comment(comment_id)
    if not cmt:
        flash("Comment not found.", "warning")
        return redirect(url_for("challenges.index"))
    cid = cmt["challenge_id"]
    rec_date = cmt["record_date"]
    try:
        challenge_service.delete_daily_comment(comment_id)
        flash("Comment deleted.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(
        request.referrer or url_for("challenges.daily_tracking", challenge_id=cid, date=rec_date)
    )
