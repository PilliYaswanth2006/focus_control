import time
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from app.services import auth_service
from app.utils.time_utils import list_common_timezones
from app.utils.validation import ValidationError


auth_bp = Blueprint("auth", __name__)


def _is_safe_next_url(next_url):
    return bool(next_url and next_url.startswith("/") and not next_url.startswith("//"))


@auth_bp.route("/setup", methods=["GET", "POST"])
def setup():
    if auth_service.is_setup_complete():
        if session.get("authenticated"):
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.lock"))

    if request.method == "POST":
        try:
            settings = auth_service.setup_credentials(
                request.form.get("credential_type"),
                request.form.get("credential"),
                request.form.get("confirm_credential"),
                request.form.get("display_name", "Focused User"),
                request.form.get("timezone", "Asia/Kolkata"),
            )
            session.clear()
            session.permanent = True
            session["authenticated"] = True
            session["lock_version"] = settings["auth_lock_version"]
            session["last_active_ts"] = time.time()
            flash("Application lock configured. Welcome to Focus & Control!", "success")
            return redirect(url_for("dashboard.index"))
        except ValidationError as exc:
            flash(exc.message, "danger")

    return render_template(
        "setup.html",
        timezones=list_common_timezones(),
        default_tz="Asia/Kolkata",
    )


@auth_bp.route("/lock", methods=["GET", "POST"])
def lock():
    if not auth_service.is_setup_complete():
        return redirect(url_for("auth.setup"))

    if session.get("authenticated") and request.method == "GET":
        settings = auth_service.get_app_settings()
        if session.get("lock_version") == settings["auth_lock_version"]:
            return redirect(url_for("dashboard.index"))

    settings = auth_service.get_app_settings()
    if request.method == "POST":
        try:
            lock_version = auth_service.verify_unlock(request.form.get("credential"))
            session.clear()
            session.permanent = True
            session["authenticated"] = True
            session["lock_version"] = lock_version
            session["last_active_ts"] = time.time()
            next_url = request.form.get("next") or request.args.get("next")
            if _is_safe_next_url(next_url):
                return redirect(next_url)
            return redirect(url_for("dashboard.index"))
        except ValidationError as exc:
            flash(exc.message, "danger")

    return render_template(
        "lock.html",
        credential_type=settings["auth_credential_type"],
        display_name=settings["display_name"],
        theme=settings["theme"],
        next_url=request.args.get("next", ""),
    )


@auth_bp.route("/auth/relock", methods=["POST"])
def relock():
    auth_service.record_lock_event("User locked application")
    session.clear()
    flash("Application locked.", "info")
    return redirect(url_for("auth.lock"))
