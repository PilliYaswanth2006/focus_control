import os
import time
from datetime import timedelta
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from config import Config
from app.database.connection import init_db
from app.services import auth_service
from app.utils.time_utils import format_local, format_local_date, utc_to_local_input


def create_app(config_class=Config):
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(config_class)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    init_db(app)

    # Register blueprints
    from app.routes.auth_routes import auth_bp
    from app.routes.dashboard_routes import dashboard_bp
    from app.routes.task_routes import task_bp
    from app.routes.challenge_routes import challenge_bp
    from app.routes.calendar_routes import calendar_bp
    from app.routes.statistics_routes import statistics_bp
    from app.routes.settings_routes import settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(task_bp)
    app.register_blueprint(challenge_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(statistics_bp)
    app.register_blueprint(settings_bp)

    @app.before_request
    def enforce_application_lock():
        endpoint = request.endpoint or ""
        if endpoint == "static" or request.path.startswith("/static/"):
            return None

        setup_done = auth_service.is_setup_complete()
        if not setup_done:
            if endpoint == "auth.setup":
                return None
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"ok": False, "error": "Application setup required.", "redirect": url_for("auth.setup")}), 401
            return redirect(url_for("auth.setup"))

        if endpoint in ("auth.lock",):
            return None

        settings = auth_service.get_app_settings()
        is_auth = bool(session.get("authenticated"))
        ver_match = session.get("lock_version") == settings["auth_lock_version"]
        timeout_secs = max(60, int(settings["session_timeout_minutes"]) * 60)
        last_active = float(session.get("last_active_ts", 0) or 0)
        not_expired = (time.time() - last_active) <= timeout_secs

        if not (is_auth and ver_match and not_expired):
            session.clear()
            if endpoint == "auth.setup":
                return redirect(url_for("auth.lock"))
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"ok": False, "error": "Session locked or expired.", "redirect": url_for("auth.lock")}), 401
            next_target = request.full_path.rstrip("?") if request.method == "GET" else ""
            if next_target and next_target != "/lock":
                return redirect(url_for("auth.lock", next=next_target))
            return redirect(url_for("auth.lock"))

        app.permanent_session_lifetime = timedelta(minutes=int(settings["session_timeout_minutes"]))
        session["last_active_ts"] = time.time()
        g.app_settings = settings
        return None

    @app.context_processor
    def inject_globals():
        settings = getattr(g, "app_settings", None)
        if settings is None:
            try:
                settings = auth_service.get_app_settings()
            except Exception:
                settings = {"theme": "light", "timezone": "UTC", "display_name": "Focused User"}
        return {
            "app_name": app.config["APP_NAME"],
            "app_settings": settings,
        }

    @app.template_filter("local_dt")
    def filter_local_dt(utc_iso, fmt="%b %d, %Y %I:%M %p"):
        settings = getattr(g, "app_settings", None) or {}
        tz = settings.get("timezone", "UTC")
        return format_local(utc_iso, tz_name=tz, fmt=fmt)

    @app.template_filter("local_date")
    def filter_local_date(utc_iso):
        settings = getattr(g, "app_settings", None) or {}
        tz = settings.get("timezone", "UTC")
        return format_local_date(utc_iso, tz_name=tz)

    @app.template_filter("local_input")
    def filter_local_input(utc_iso):
        settings = getattr(g, "app_settings", None) or {}
        tz = settings.get("timezone", "UTC")
        return utc_to_local_input(utc_iso, tz_name=tz)

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def file_too_large(error):
        return render_template("errors/500.html", message="Uploaded file exceeds the 5 MB maximum limit."), 413

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/500.html", message="An unexpected internal error occurred."), 500

    return app
