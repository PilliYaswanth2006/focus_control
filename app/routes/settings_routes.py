import time
from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for
from app.services import auth_service, data_management_service, demo_service
from app.utils.time_utils import list_common_timezones
from app.utils.validation import ValidationError


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.route("", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        try:
            auth_service.update_app_settings(request.form)
            flash("Settings saved successfully.", "success")
            return redirect(url_for("settings.index"))
        except ValidationError as exc:
            flash(exc.message, "danger")

    settings = auth_service.get_app_settings()
    logs = auth_service.get_activity_logs(limit=40)
    trash = data_management_service.get_trash_overview()
    return render_template(
        "settings/index.html",
        settings=settings,
        timezones=list_common_timezones(),
        logs=logs,
        demo_loaded=demo_service.has_demo_data(),
        trash=trash,
    )


@settings_bp.route("/credentials", methods=["POST"])
def change_credentials():
    try:
        new_ver = auth_service.change_credentials(
            request.form.get("current_credential"),
            request.form.get("new_credential_type"),
            request.form.get("new_credential"),
            request.form.get("confirm_credential"),
        )
        session["lock_version"] = new_ver
        session["last_active_ts"] = time.time()
        flash("Application lock credentials updated.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("settings.index"))


@settings_bp.route("/toggle-theme", methods=["POST"])
def toggle_theme():
    payload = request.get_json(silent=True) if request.is_json else request.form
    preferred = payload.get("theme") if payload else None
    new_theme = auth_service.toggle_theme(preferred_theme=preferred)
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "theme": new_theme})
    return redirect(request.referrer or url_for("dashboard.index"))


@settings_bp.route("/demo/load", methods=["POST"])
def load_demo():
    loaded = demo_service.seed_demo_data()
    if loaded:
        flash("Demo workspace data loaded (tagged separately with DEMO badges).", "success")
    else:
        flash("Demo data is already present.", "info")
    return redirect(request.referrer or url_for("settings.index"))


@settings_bp.route("/demo/clear", methods=["POST"])
def clear_demo():
    demo_service.clear_demo_data()
    flash("All demo workspace records removed. Your personal records remain intact.", "success")
    return redirect(request.referrer or url_for("settings.index"))


@settings_bp.route("/backup/download")
def download_backup():
    data_bytes, filename = data_management_service.create_sqlite_backup_bytes()
    return Response(
        data_bytes,
        mimetype="application/x-sqlite3",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


@settings_bp.route("/backup/restore", methods=["POST"])
def restore_backup():
    try:
        new_lock_ver = data_management_service.restore_sqlite_backup(request.files.get("backup_file"))
        session["lock_version"] = new_lock_ver
        session["last_active_ts"] = time.time()
        flash("SQLite backup restored successfully. A safety pre-restore snapshot was created automatically.", "success")
    except ValidationError as exc:
        flash(exc.message, "danger")
    return redirect(url_for("settings.index"))


@settings_bp.route("/export/json")
def export_json():
    include_demo = request.args.get("include_demo", "1") != "0"
    data_bytes, filename = data_management_service.export_json_bytes(include_demo=include_demo)
    return Response(
        data_bytes,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


@settings_bp.route("/export/csv")
def export_csv():
    dataset = (request.args.get("dataset") or "all").strip().lower()
    include_demo = request.args.get("include_demo", "1") != "0"
    try:
        data_bytes, filename, mimetype = data_management_service.export_csv_download(
            dataset, include_demo=include_demo
        )
        return Response(
            data_bytes,
            mimetype=mimetype,
            headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
        )
    except ValidationError as exc:
        flash(exc.message, "danger")
        return redirect(url_for("settings.index"))
