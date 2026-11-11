from flask import Blueprint, render_template
from app.services import statistics_service


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    summary = statistics_service.get_dashboard_summary()
    return render_template("dashboard.html", summary=summary)
