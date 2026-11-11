import json
import re
from datetime import datetime


VALID_THEMES = ("light", "dark", "system")
VALID_TASK_STATUSES = ("Not Started", "Active", "In Progress", "Completed", "Archived")
VALID_PRIORITIES = ("Low", "Medium", "High", "Critical")
VALID_CHALLENGE_STATUSES = ("Not Started", "Active", "Paused", "Completed", "Archived")
VALID_EVENT_TYPES = ("THOUGHT", "URGE", "ACTION")
VALID_URGE_OUTCOMES = ("Resisted", "Gave In", "Pending")
VALID_CARD_STYLES = ("elevated", "bordered", "glass", "minimal")
VALID_LAYOUT_STYLES = ("comfortable", "compact", "focused")
PREDEFINED_TRIGGERS = (
    "Boredom",
    "Stress",
    "Loneliness",
    "Procrastination",
    "Habit",
    "Notifications",
    "Entertainment",
    "Social pressure",
    "Other",
)
PREDEFINED_TRIGGER_MAP = {t.lower(): t for t in PREDEFINED_TRIGGERS}
VALID_FONTS = (
    "Inter",
    "Plus Jakarta Sans",
    "Merriweather",
    "JetBrains Mono",
    "Georgia",
    "System UI",
)

HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ValidationError(Exception):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field


def require_non_empty(value, label, max_len=200):
    text = (value or "").strip()
    if not text:
        raise ValidationError("%s is required." % label)
    if len(text) > max_len:
        raise ValidationError("%s must be %d characters or fewer." % (label, max_len))
    return text


def clean_optional_text(value, max_len=5000):
    text = (value or "").strip()
    if len(text) > max_len:
        raise ValidationError("Text exceeds maximum length of %d characters." % max_len)
    return text


def parse_float(value, label, min_val=None, max_val=None, default=None):
    if value is None or str(value).strip() == "":
        if default is not None:
            return float(default)
        raise ValidationError("%s is required." % label)
    try:
        num = float(str(value).strip())
    except (ValueError, TypeError):
        raise ValidationError("%s must be a valid number." % label)
    if min_val is not None and num < min_val:
        raise ValidationError("%s cannot be less than %s." % (label, min_val))
    if max_val is not None and num > max_val:
        raise ValidationError("%s cannot exceed %s." % (label, max_val))
    return round(num, 4)


def parse_int(value, label, min_val=None, max_val=None, default=None):
    if value is None or str(value).strip() == "":
        if default is not None:
            return int(default)
        raise ValidationError("%s is required." % label)
    try:
        num = int(float(str(value).strip()))
    except (ValueError, TypeError):
        raise ValidationError("%s must be a valid integer." % label)
    if min_val is not None and num < min_val:
        raise ValidationError("%s cannot be less than %s." % (label, min_val))
    if max_val is not None and num > max_val:
        raise ValidationError("%s cannot exceed %s." % (label, max_val))
    return num


def validate_date_str(value, label="Date"):
    text = (value or "").strip()
    if not text:
        return ""
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("%s must be in YYYY-MM-DD format." % label)
    return text


def validate_date_order(start_date, end_date, start_label="Start date", end_label="End date"):
    if start_date and end_date and end_date < start_date:
        raise ValidationError("%s cannot be earlier than %s." % (end_label, start_label))


def validate_choice(value, choices, label, default=None):
    text = (value or "").strip()
    if not text and default is not None:
        return default
    if text not in choices:
        raise ValidationError("%s must be one of: %s." % (label, ", ".join(choices)))
    return text


def validate_hex_color(value, default=""):
    text = (value or "").strip()
    if not text:
        return default
    if not HEX_COLOR_RE.match(text):
        raise ValidationError("Color '%s' must be a valid 6-digit hex code (e.g. #4F46E5)." % text)
    return text


def parse_metadata_json(raw_text, kv_keys=None, kv_values=None):
    """Support either JSON text or key/value pair arrays from forms."""
    data = {}
    if raw_text and raw_text.strip():
        try:
            parsed = json.loads(raw_text.strip())
            if not isinstance(parsed, dict):
                raise ValidationError("Additional metadata must be a JSON object.")
            data.update(parsed)
        except json.JSONDecodeError:
            raise ValidationError("Additional metadata contains invalid JSON.")
    if kv_keys and kv_values:
        for k, v in zip(kv_keys, kv_values):
            key = (k or "").strip()
            val = (v or "").strip()
            if key:
                data[key] = val
    return json.dumps(data, ensure_ascii=False)


def normalize_trigger(raw_category, raw_text):
    cat_in = clean_optional_text(raw_category, max_len=80)
    txt_in = clean_optional_text(raw_text, max_len=200)

    if cat_in:
        matched = PREDEFINED_TRIGGER_MAP.get(cat_in.lower())
        if not matched:
            raise ValidationError("Trigger category must be one of: %s." % ", ".join(PREDEFINED_TRIGGERS))
        cat_clean = matched
    elif txt_in:
        cat_clean = PREDEFINED_TRIGGER_MAP.get(txt_in.lower(), "Other")
    else:
        cat_clean = ""

    return cat_clean, txt_in

