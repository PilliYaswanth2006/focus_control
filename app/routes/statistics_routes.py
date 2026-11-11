from flask import Blueprint, jsonify, render_template, request
from app.services import demo_service, statistics_service
from app.utils.validation import ValidationError, validate_date_order, validate_date_str


statistics_bp = Blueprint("statistics", __name__, url_prefix="/statistics")


@statistics_bp.route("")
def index():
    preset = (request.args.get("preset") or "").strip().lower()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()
    include_demo = request.args.get("include_demo", "1") != "0"
    error_msg = None
    try:
        start_date = validate_date_str(start_date, "Start date")
        end_date = validate_date_str(end_date, "End date")
        validate_date_order(start_date, end_date, "Start date", "End date")
    except ValidationError as exc:
        error_msg = exc.message
        start_date = ""
        end_date = ""
        preset = "all"

    stats = statistics_service.get_global_statistics(
        start_date=start_date or None,
        end_date=end_date or None,
        include_demo=include_demo,
        preset=preset or None,
    )
    return render_template(
        "statistics/index.html",
        stats=stats,
        preset=stats["preset"],
        start_date=stats["start_date"] or "",
        end_date=stats["end_date"] or "",
        include_demo=include_demo,
        has_demo=demo_service.has_demo_data(),
        error_msg=error_msg,
    )


@statistics_bp.route("/api")
def api_data():
    preset = (request.args.get("preset") or "").strip().lower()
    start_date = validate_date_str(request.args.get("start_date", ""), "Start date")
    end_date = validate_date_str(request.args.get("end_date", ""), "End date")
    validate_date_order(start_date, end_date, "Start date", "End date")
    include_demo = request.args.get("include_demo", "1") != "0"
    stats = statistics_service.get_global_statistics(
        start_date=start_date or None,
        end_date=end_date or None,
        include_demo=include_demo,
        preset=preset or None,
    )
    return jsonify(stats)
