import os
import secrets
from datetime import timedelta


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _load_or_create_secret_key():
    env_key = os.environ.get("FOCUS_CONTROL_SECRET_KEY")
    if env_key:
        return env_key
    os.makedirs(INSTANCE_DIR, exist_ok=True)
    key_path = os.path.join(INSTANCE_DIR, ".secret_key")
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
            if key:
                return key
    key = secrets.token_hex(32)
    with open(key_path, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


class Config:
    APP_NAME = "Focus & Control"
    SECRET_KEY = _load_or_create_secret_key()
    DATABASE_PATH = os.environ.get(
        "FOCUS_CONTROL_DB", os.path.join(INSTANCE_DIR, "focus_control.db")
    )
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads", "backgrounds")
    PRESET_BG_FOLDER = os.path.join(BASE_DIR, "app", "static", "images", "presets")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB upload cap
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

    SESSION_COOKIE_NAME = "fc_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("FOCUS_CONTROL_HTTPS", "0") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
    DEFAULT_TIMEZONE = os.environ.get("FOCUS_CONTROL_TIMEZONE", "Asia/Kolkata")
    DEFAULT_SESSION_TIMEOUT_MINUTES = 30


class TestConfig(Config):
    TESTING = True
    DATABASE_PATH = ":memory:"
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)
