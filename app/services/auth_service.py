from datetime import timedelta
from werkzeug.security import check_password_hash, generate_password_hash
from app.database.transaction import transaction
from app.repositories import auth_repository
from app.utils.time_utils import list_common_timezones, parse_utc_iso, utc_now, utc_now_iso
from app.utils.validation import (
    VALID_THEMES,
    ValidationError,
    clean_optional_text,
    parse_float,
    parse_int,
    validate_choice,
)


MAX_FAILED_ATTEMPTS = 5
COOLDOWN_SECONDS = 60


def is_setup_complete():
    pwd_hash = auth_repository.get_setting("auth_password_hash")
    return bool(pwd_hash)


def get_app_settings():
    settings = auth_repository.get_all_settings()
    return {
        "theme": settings.get("theme", "light"),
        "timezone": settings.get("timezone", "Asia/Kolkata"),
        "session_timeout_minutes": int(settings.get("session_timeout_minutes", "30") or 30),
        "display_name": settings.get("display_name", "Focused User"),
        "task_budget_mode": settings.get("task_budget_mode", "fixed"),
        "task_total_budget": float(settings.get("task_total_budget", "40") or 40),
        "task_budget_unit": settings.get("task_budget_unit", "hours"),
        "auth_credential_type": settings.get("auth_credential_type", "pin"),
        "auth_lock_version": int(settings.get("auth_lock_version", "1") or 1),
    }


def _validate_credential(credential_type, credential, confirm_credential):
    ctype = validate_choice(credential_type, ("pin", "password"), "Credential type", default="pin")
    secret = (credential or "").strip()
    confirm = (confirm_credential or "").strip()

    if not secret:
        raise ValidationError("PIN or password is required.")
    if secret != confirm:
        raise ValidationError("Confirmation does not match.")

    if ctype == "pin":
        if not secret.isdigit():
            raise ValidationError("PIN must contain digits only (0-9).")
        if len(secret) < 4 or len(secret) > 12:
            raise ValidationError("PIN must be between 4 and 12 digits.")
    else:
        if len(secret) < 6 or len(secret) > 128:
            raise ValidationError("Password must be between 6 and 128 characters.")
    return ctype, secret


def setup_credentials(credential_type, credential, confirm_credential, display_name="Focused User", timezone_name="Asia/Kolkata"):
    if is_setup_complete():
        raise ValidationError("Application lock is already configured.")

    ctype, secret = _validate_credential(credential_type, credential, confirm_credential)
    clean_name = clean_optional_text(display_name, max_len=80) or "Focused User"
    valid_tzs = list_common_timezones()
    tz = timezone_name if timezone_name in valid_tzs else "UTC"
    pwd_hash = generate_password_hash(secret)
    now_utc = utc_now_iso()

    with transaction() as conn:
        auth_repository.upsert_setting("auth_credential_type", ctype, now_utc, conn=conn)
        auth_repository.upsert_setting("auth_password_hash", pwd_hash, now_utc, conn=conn)
        auth_repository.upsert_setting("auth_lock_version", "1", now_utc, conn=conn)
        auth_repository.upsert_setting("auth_failed_attempts", "0", now_utc, conn=conn)
        auth_repository.upsert_setting("auth_locked_until", "", now_utc, conn=conn)
        auth_repository.upsert_setting("display_name", clean_name, now_utc, conn=conn)
        auth_repository.upsert_setting("timezone", tz, now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "auth",
            "initial_setup",
            "app_settings",
            None,
            "Application lock initialized (%s)" % ctype,
            now_utc,
            conn=conn,
        )
    return get_app_settings()


def verify_unlock(credential):
    settings = auth_repository.get_all_settings()
    pwd_hash = settings.get("auth_password_hash", "")
    if not pwd_hash:
        raise ValidationError("Application is not set up yet.")

    now_dt = utc_now()
    now_utc = utc_now_iso()

    locked_until_str = settings.get("auth_locked_until", "")
    if locked_until_str:
        locked_until = parse_utc_iso(locked_until_str)
        if locked_until and locked_until > now_dt:
            remaining = int((locked_until - now_dt).total_seconds()) + 1
            raise ValidationError("Too many failed attempts. Try again in %d seconds." % remaining)

    secret = (credential or "").strip()
    if not secret:
        raise ValidationError("Please enter your PIN or password.")

    if check_password_hash(pwd_hash, secret):
        with transaction() as conn:
            auth_repository.upsert_setting("auth_failed_attempts", "0", now_utc, conn=conn)
            auth_repository.upsert_setting("auth_locked_until", "", now_utc, conn=conn)
            auth_repository.insert_activity_log(
                "auth", "unlock_success", "session", None, "Application unlocked", now_utc, conn=conn
            )
        return int(settings.get("auth_lock_version", "1") or 1)

    failed = int(settings.get("auth_failed_attempts", "0") or 0) + 1
    locked_until_val = ""
    if failed >= MAX_FAILED_ATTEMPTS:
        locked_until_val = (now_dt + timedelta(seconds=COOLDOWN_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with transaction() as conn:
        auth_repository.upsert_setting("auth_failed_attempts", str(failed), now_utc, conn=conn)
        auth_repository.upsert_setting("auth_locked_until", locked_until_val, now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "auth",
            "unlock_failed",
            "session",
            None,
            "Failed unlock attempt #%d" % failed,
            now_utc,
            conn=conn,
        )

    if locked_until_val:
        raise ValidationError("Incorrect credentials. Cooldown activated for %d seconds." % COOLDOWN_SECONDS)
    remaining_tries = MAX_FAILED_ATTEMPTS - failed
    raise ValidationError("Incorrect PIN or password (%d attempt(s) remaining before cooldown)." % remaining_tries)


def change_credentials(current_credential, new_credential_type, new_credential, confirm_credential):
    pwd_hash = auth_repository.get_setting("auth_password_hash", "")
    if not pwd_hash or not check_password_hash(pwd_hash, (current_credential or "").strip()):
        raise ValidationError("Current PIN or password is incorrect.")

    ctype, secret = _validate_credential(new_credential_type, new_credential, confirm_credential)
    new_hash = generate_password_hash(secret)
    current_ver = int(auth_repository.get_setting("auth_lock_version", "1") or 1)
    next_ver = current_ver + 1
    now_utc = utc_now_iso()

    with transaction() as conn:
        auth_repository.upsert_setting("auth_credential_type", ctype, now_utc, conn=conn)
        auth_repository.upsert_setting("auth_password_hash", new_hash, now_utc, conn=conn)
        auth_repository.upsert_setting("auth_lock_version", str(next_ver), now_utc, conn=conn)
        auth_repository.upsert_setting("auth_failed_attempts", "0", now_utc, conn=conn)
        auth_repository.upsert_setting("auth_locked_until", "", now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "auth",
            "credentials_changed",
            "app_settings",
            None,
            "Updated application lock (%s)" % ctype,
            now_utc,
            conn=conn,
        )
    return next_ver


def record_lock_event(reason="User locked application"):
    now_utc = utc_now_iso()
    with transaction() as conn:
        auth_repository.insert_activity_log(
            "auth", "app_locked", "session", None, reason, now_utc, conn=conn
        )


def update_app_settings(data):
    theme = validate_choice(data.get("theme"), VALID_THEMES, "Theme", default="light")
    timezone_name = (data.get("timezone") or "UTC").strip()
    if timezone_name not in list_common_timezones():
        raise ValidationError("Unsupported timezone selected.")

    timeout_mins = parse_int(
        data.get("session_timeout_minutes"),
        "Session timeout (minutes)",
        min_val=5,
        max_val=1440,
        default=30,
    )
    display_name = clean_optional_text(data.get("display_name"), max_len=80) or "Focused User"
    budget_mode = validate_choice(
        data.get("task_budget_mode"), ("fixed", "dynamic"), "Budget mode", default="fixed"
    )
    total_budget = parse_float(
        data.get("task_total_budget"), "Total time budget", min_val=0.0, max_val=10000.0, default=40.0
    )
    budget_unit = clean_optional_text(data.get("task_budget_unit"), max_len=30) or "hours"

    now_utc = utc_now_iso()
    with transaction() as conn:
        auth_repository.upsert_setting("theme", theme, now_utc, conn=conn)
        auth_repository.upsert_setting("timezone", timezone_name, now_utc, conn=conn)
        auth_repository.upsert_setting("session_timeout_minutes", str(timeout_mins), now_utc, conn=conn)
        auth_repository.upsert_setting("display_name", display_name, now_utc, conn=conn)
        auth_repository.upsert_setting("task_budget_mode", budget_mode, now_utc, conn=conn)
        auth_repository.upsert_setting("task_total_budget", str(total_budget), now_utc, conn=conn)
        auth_repository.upsert_setting("task_budget_unit", budget_unit, now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "settings",
            "settings_updated",
            "app_settings",
            None,
            "Theme=%s, TZ=%s, Budget=%s %s (%s)" % (theme, timezone_name, total_budget, budget_unit, budget_mode),
            now_utc,
            conn=conn,
        )
    return get_app_settings()


def toggle_theme(preferred_theme=None):
    current = auth_repository.get_setting("theme", "light")
    if preferred_theme in VALID_THEMES:
        nxt = preferred_theme
    else:
        nxt = "dark" if current == "light" else "light"
    now_utc = utc_now_iso()
    with transaction() as conn:
        auth_repository.upsert_setting("theme", nxt, now_utc, conn=conn)
    return nxt


def get_activity_logs(limit=50, module=None):
    return auth_repository.list_activity_logs(limit=limit, module=module)
