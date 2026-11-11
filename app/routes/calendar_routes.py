from flask import Blueprint, flash, jsonify, render_template, request
from app.services import calendar_service, demo_service
from app.utils.validation import ValidationError, validate_date_str


calendar_bp = Blueprint("calendar", __name__, url_prefix="/calendar")


@calendar_bp.route("")
def index():
    month_str = (request.args.get("month") or "").strip()
    date_str = (request.args.get("date") or "").strip()
    module_filter = (request.args.get("module") or "all").strip().lower()
    include_demo = request.args.get("include_demo", "1") != "0"

    try:
        date_str = validate_date_str(date_str, "Date")
    except ValidationError as exc:
        flash(exc.message, "warning")
        date_str = ""

    if date_str and not month_str:
        month_str = date_str[:7]

    try:
        cal = calendar_service.get_calendar_month_data(
            month_str=month_str or None,
            selected_date=date_str or None,
            module_filter=module_filter,
            include_demo=include_demo,
        )
    except ValidationError as exc:
        flash(exc.message, "warning")
        cal = calendar_service.get_calendar_month_data(
            month_str=None,
            selected_date=None,
            module_filter=module_filter,
            include_demo=include_demo,
        )

    return render_template(
        "calendar/index.html",
        cal=cal,
        has_demo=demo_service.has_demo_data(),
    )


@calendar_bp.route("/day-details")
def day_details():
    month_str = (request.args.get("month") or "").strip()
    date_str = (request.args.get("date") or "").strip()
    module_filter = (request.args.get("module") or "all").strip().lower()
    include_demo = request.args.get("include_demo", "1") != "0"

    try:
        date_str = validate_date_str(date_str, "Date")
        if date_str and not month_str:
            month_str = date_str[:7]
        cal = calendar_service.get_calendar_month_data(
            month_str=month_str or None,
            selected_date=date_str or None,
            module_filter=module_filter,
            include_demo=include_demo,
        )
        return jsonify({
            "ok": True,
            "month": cal["month"],
            "selected_date": cal["selected_date"],
            "day": cal["selected_day"],
        })
    except ValidationError as exc:
        return jsonify({"ok": False, "error": exc.message}), 400
