import io
import os
import uuid
from PIL import Image, UnidentifiedImageError
from flask import current_app
from app.utils.validation import ValidationError


PRESET_BACKGROUNDS = [
    {"id": "", "label": "None (Clean Surface)", "path": ""},
    {"id": "preset:slate-grid.svg", "label": "Slate Blueprint Grid", "path": "images/presets/slate-grid.svg"},
    {"id": "preset:cobalt-waves.svg", "label": "Cobalt Horizon Waves", "path": "images/presets/cobalt-waves.svg"},
    {"id": "preset:emerald-horizon.svg", "label": "Emerald Calm Geometry", "path": "images/presets/emerald-horizon.svg"},
    {"id": "preset:amber-mesh.svg", "label": "Warm Amber Mesh", "path": "images/presets/amber-mesh.svg"},
    {"id": "preset:nordic-dots.svg", "label": "Nordic Minimal Dots", "path": "images/presets/nordic-dots.svg"},
    {"id": "preset:midnight-contours.svg", "label": "Midnight Contours", "path": "images/presets/midnight-contours.svg"},
]


def save_uploaded_background(file_storage):
    if not file_storage or not file_storage.filename:
        return None

    filename = file_storage.filename.strip()
    if "." not in filename:
        raise ValidationError("Uploaded background must have a valid image extension (.png, .jpg, .jpeg, .webp).")

    ext = filename.rsplit(".", 1)[1].lower()
    allowed = current_app.config.get("ALLOWED_IMAGE_EXTENSIONS", {"png", "jpg", "jpeg", "webp"})
    if ext not in allowed:
        raise ValidationError("Unsupported image format '.%s'. Allowed formats: PNG, JPG, JPEG, WEBP." % ext)

    raw_bytes = file_storage.read()
    max_bytes = current_app.config.get("MAX_CONTENT_LENGTH", 5 * 1024 * 1024)
    if len(raw_bytes) == 0:
        raise ValidationError("Uploaded image file is empty.")
    if len(raw_bytes) > max_bytes:
        raise ValidationError("Uploaded image exceeds the 5 MB limit.")

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.verify()
        img2 = Image.open(io.BytesIO(raw_bytes))
        fmt = (img2.format or "").upper()
        if fmt not in ("PNG", "JPEG", "WEBP"):
            raise ValidationError("Uploaded file is not a valid PNG, JPEG, or WEBP image.")
    except ValidationError:
        raise
    except (UnidentifiedImageError, Exception):
        raise ValidationError("Uploaded file could not be verified as a valid image.")

    upload_dir = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = "%s.%s" % (uuid.uuid4().hex, ext)
    dest_path = os.path.join(upload_dir, safe_name)
    with open(dest_path, "wb") as fh:
        fh.write(raw_bytes)

    return "uploads/backgrounds/" + safe_name


def resolve_background_choice(file_storage, bg_choice, current_bg="", current_mode="none"):
    uploaded_rel = save_uploaded_background(file_storage)
    if uploaded_rel:
        return uploaded_rel, "upload"

    choice = (bg_choice or "").strip()
    if choice == "__keep__":
        return current_bg, current_mode
    if not choice:
        return "", "none"
    if choice.startswith("preset:"):
        preset_file = choice.split(":", 1)[1]
        valid_ids = {p["id"] for p in PRESET_BACKGROUNDS if p["id"]}
        if choice not in valid_ids:
            raise ValidationError("Invalid background preset selected.")
        return "images/presets/" + preset_file, "preset"
    if choice.startswith("uploads/backgrounds/"):
        return choice, "upload"
    if choice.startswith("images/presets/"):
        return choice, "preset"
    return "", "none"
