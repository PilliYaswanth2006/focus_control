import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"


def get_zoneinfo(tz_name):
    if not tz_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def utc_now():
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().strftime(UTC_FMT)


def parse_utc_iso(ts_str):
    if not ts_str:
        return None
    val = ts_str.strip()
    if val.endswith("Z"):
        val = val[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(val)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_local_dt(utc_iso, tz_name="UTC"):
    dt = parse_utc_iso(utc_iso)
    if dt is None:
        return None
    return dt.astimezone(get_zoneinfo(tz_name))


def format_local(utc_iso, tz_name="UTC", fmt="%b %d, %Y %I:%M %p"):
    local_dt = to_local_dt(utc_iso, tz_name)
    if local_dt is None:
        return ""
    return local_dt.strftime(fmt)


def format_local_date(utc_iso, tz_name="UTC"):
    local_dt = to_local_dt(utc_iso, tz_name)
    if local_dt is None:
        return ""
    return local_dt.strftime("%Y-%m-%d")


def local_today_str(tz_name="UTC"):
    return utc_now().astimezone(get_zoneinfo(tz_name)).strftime("%Y-%m-%d")


def local_input_to_utc(local_dt_str, tz_name="UTC"):
    """Convert YYYY-MM-DDTHH:MM (from HTML datetime-local) in local tz to UTC ISO string."""
    if not local_dt_str:
        return utc_now_iso()
    cleaned = local_dt_str.strip()
    if cleaned.endswith("Z"):
        parsed = parse_utc_iso(cleaned)
        if parsed is not None:
            return parsed.strftime(UTC_FMT)
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = datetime.strptime(cleaned, fmt)
            aware = naive.replace(tzinfo=get_zoneinfo(tz_name))
            return aware.astimezone(timezone.utc).strftime(UTC_FMT)
        except ValueError:
            continue
    raise ValueError("Invalid date/time format. Expected YYYY-MM-DDTHH:MM.")


def utc_to_local_input(utc_iso, tz_name="UTC"):
    local_dt = to_local_dt(utc_iso, tz_name)
    if local_dt is None:
        return ""
    return local_dt.strftime("%Y-%m-%dT%H:%M")


def local_date_range_to_utc_bounds(start_date_str, end_date_str, tz_name="UTC"):
    """Convert inclusive local YYYY-MM-DD bounds to (start_utc_iso, end_utc_iso)."""
    tz = get_zoneinfo(tz_name)
    start_utc = None
    end_utc = None
    if start_date_str:
        d_start = datetime.strptime(start_date_str.strip(), "%Y-%m-%d")
        local_start = d_start.replace(hour=0, minute=0, second=0, tzinfo=tz)
        start_utc = local_start.astimezone(timezone.utc).strftime(UTC_FMT)
    if end_date_str:
        d_end = datetime.strptime(end_date_str.strip(), "%Y-%m-%d")
        local_end = (d_end + timedelta(days=1)).replace(hour=0, minute=0, second=0, tzinfo=tz) - timedelta(seconds=1)
        end_utc = local_end.astimezone(timezone.utc).strftime(UTC_FMT)
    return start_utc, end_utc


def list_common_timezones():
    return [
        "UTC",
        "Asia/Kolkata",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "Europe/London",
        "Europe/Berlin",
        "Europe/Paris",
        "Asia/Tokyo",
        "Asia/Singapore",
        "Asia/Dubai",
        "Australia/Sydney",
    ]


def calculate_inclusive_days(start_date_str, end_date_str):
    if not start_date_str or not end_date_str:
        return None
    try:
        d1 = datetime.strptime(start_date_str.strip(), "%Y-%m-%d").date()
        d2 = datetime.strptime(end_date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None
    if d2 < d1:
        return None
    return (d2 - d1).days + 1


def shift_date_str(date_str, delta_days):
    d = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    return (d + timedelta(days=int(delta_days))).strftime("%Y-%m-%d")


def resolve_period_preset(preset, start_date_str=None, end_date_str=None, tz_name="UTC"):
    today_s = local_today_str(tz_name)
    today_d = datetime.strptime(today_s, "%Y-%m-%d").date()
    clean_preset = (preset or "").strip().lower()

    preset_spans = {
        "today": 1,
        "7d": 7,
        "30d": 30,
        "90d": 90,
    }
    if clean_preset in preset_spans:
        span_days = preset_spans[clean_preset]
        end_d = today_d
        start_d = today_d - timedelta(days=span_days - 1)
        return start_d.strftime("%Y-%m-%d"), end_d.strftime("%Y-%m-%d"), clean_preset

    if clean_preset in ("month", "this_month"):
        start_d = today_d.replace(day=1)
        return start_d.strftime("%Y-%m-%d"), today_d.strftime("%Y-%m-%d"), "month"

    if clean_preset == "all":
        return None, None, "all"

    if start_date_str or end_date_str:
        return (start_date_str or None), (end_date_str or None), "custom"

    return None, None, "all"


def validate_month_str(month_str, tz_name="UTC"):
    raw = (month_str or "").strip()
    if not raw:
        raw = local_today_str(tz_name)[:7]
    try:
        dt = datetime.strptime(raw, "%Y-%m")
        return dt.year, dt.month, "%04d-%02d" % (dt.year, dt.month)
    except ValueError:
        from app.utils.validation import ValidationError
        raise ValidationError("Month must be in YYYY-MM format.")


def month_grid_dates(year, month, tz_name="UTC"):
    cal = calendar.Calendar(firstweekday=0)
    dates = [
        d.strftime("%Y-%m-%d")
        for wk in cal.monthdatescalendar(int(year), int(month))
        for d in wk
    ]
    return dates, dates[0], dates[-1]

