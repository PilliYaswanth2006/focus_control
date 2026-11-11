from datetime import datetime
from app.repositories import auth_repository, statistics_repository
from app.utils.time_utils import (
    format_local,
    format_local_date,
    local_date_range_to_utc_bounds,
    local_today_str,
    month_grid_dates,
    validate_month_str,
)


def _get_timezone():
    return auth_repository.get_setting("timezone", "UTC") or "UTC"


def _month_navigation(year, month):
    if month == 1:
        prev_m = "%04d-%02d" % (year - 1, 12)
    else:
        prev_m = "%04d-%02d" % (year, month - 1)
    if month == 12:
        next_m = "%04d-%02d" % (year + 1, 1)
    else:
        next_m = "%04d-%02d" % (year, month + 1)
    return prev_m, next_m


def get_calendar_month_data(month_str=None, selected_date=None, module_filter="all", include_demo=True):
    tz_name = _get_timezone()
    today_str = local_today_str(tz_name)

    year, month, clean_month = validate_month_str(month_str, tz_name)
    prev_month, next_month = _month_navigation(year, month)

    grid_dates, grid_start_str, grid_end_str = month_grid_dates(year, month, tz_name)
    start_utc, end_utc = local_date_range_to_utc_bounds(grid_start_str, grid_end_str, tz_name)

    if module_filter not in ("all", "tasks", "challenges"):
        module_filter = "all"

    entries = []
    completed_items = []
    completed_centered = []
    events = []
    reflections = []
    daily_records = []
    comments = []

    if module_filter in ("all", "tasks"):
        entries = statistics_repository.list_progress_entries_in_range(
            start_utc=start_utc, end_utc=end_utc, include_demo=include_demo
        )
        completed_items = statistics_repository.list_completed_items_in_range(
            start_utc=start_utc, end_utc=end_utc, include_demo=include_demo
        )
        completed_centered = statistics_repository.list_completed_centered_in_range(
            start_utc=start_utc, end_utc=end_utc, include_demo=include_demo
        )

    if module_filter in ("all", "challenges"):
        events = statistics_repository.list_urge_events_in_range(
            start_utc=start_utc, end_utc=end_utc, include_demo=include_demo
        )
        reflections = statistics_repository.list_reflections_in_range(
            start_date=grid_start_str, end_date=grid_end_str, include_demo=include_demo
        )
        daily_records = statistics_repository.list_daily_records_in_range(
            start_date=grid_start_str, end_date=grid_end_str, include_demo=include_demo
        )
        comments = statistics_repository.list_comments_in_range(
            start_date=grid_start_str, end_date=grid_end_str, include_demo=include_demo
        )

    day_map = {}
    for d in grid_dates:
        day_map[d] = {
            "date": d,
            "day_num": int(d.split("-")[2]),
            "in_month": d.startswith(clean_month),
            "is_today": d == today_str,
            "progress_entries": [],
            "completed_items": [],
            "completed_centered": [],
            "events": [],
            "reflections": [],
            "daily_records": [],
            "comments": [],
            "task_minutes": 0.0,
            "task_hours": 0.0,
            "thoughts": 0,
            "urges": 0,
            "resisted": 0,
            "gave_in": 0,
            "pending": 0,
            "actions": 0,
            "completed_count": 0,
            "note_count": 0,
            "total_activity": 0,
        }

    for e in entries:
        d_str = format_local_date(e["entry_timestamp"], tz_name)
        if d_str not in day_map:
            continue
        item = dict(e)
        item["local_time"] = format_local(e["entry_timestamp"], tz_name, "%I:%M %p")
        day_map[d_str]["progress_entries"].append(item)
        day_map[d_str]["task_minutes"] += float(e["time_spent_minutes"])
        day_map[d_str]["total_activity"] += 1

    for ci in completed_items:
        d_str = format_local_date(ci["completed_at"], tz_name)
        if d_str not in day_map:
            continue
        item = dict(ci)
        item["local_time"] = format_local(ci["completed_at"], tz_name, "%I:%M %p")
        day_map[d_str]["completed_items"].append(item)
        day_map[d_str]["completed_count"] += 1
        day_map[d_str]["total_activity"] += 1

    for cc in completed_centered:
        d_str = format_local_date(cc["completed_at"], tz_name)
        if d_str not in day_map:
            continue
        item = dict(cc)
        item["local_time"] = format_local(cc["completed_at"], tz_name, "%I:%M %p")
        day_map[d_str]["completed_centered"].append(item)
        day_map[d_str]["completed_count"] += 1
        day_map[d_str]["total_activity"] += 1

    for ev in events:
        d_str = format_local_date(ev["event_timestamp"], tz_name)
        if d_str not in day_map:
            continue
        item = dict(ev)
        item["local_time"] = format_local(ev["event_timestamp"], tz_name, "%I:%M %p")
        day_map[d_str]["events"].append(item)
        day_map[d_str]["total_activity"] += 1
        if ev["event_type"] == "THOUGHT":
            day_map[d_str]["thoughts"] += 1
        elif ev["event_type"] == "URGE":
            day_map[d_str]["urges"] += 1
            if ev["outcome"] == "Resisted":
                day_map[d_str]["resisted"] += 1
            elif ev["outcome"] == "Gave In":
                day_map[d_str]["gave_in"] += 1
            else:
                day_map[d_str]["pending"] += 1
        elif ev["event_type"] == "ACTION":
            day_map[d_str]["actions"] += 1

    for rf in reflections:
        d_str = rf["record_date"]
        if d_str not in day_map:
            continue
        item = dict(rf)
        item["local_time"] = format_local(rf["created_at"], tz_name, "%I:%M %p")
        day_map[d_str]["reflections"].append(item)
        day_map[d_str]["note_count"] += 1
        day_map[d_str]["total_activity"] += 1

    for rec in daily_records:
        d_str = rec["record_date"]
        if d_str not in day_map or not (rec.get("reflection") or rec.get("mood") or rec.get("context")):
            continue
        day_map[d_str]["daily_records"].append(dict(rec))
        day_map[d_str]["note_count"] += 1
        day_map[d_str]["total_activity"] += 1

    for cm in comments:
        d_str = cm["record_date"]
        if d_str not in day_map:
            continue
        item = dict(cm)
        item["local_time"] = format_local(cm["created_at"], tz_name, "%I:%M %p")
        day_map[d_str]["comments"].append(item)
        day_map[d_str]["note_count"] += 1
        day_map[d_str]["total_activity"] += 1

    for d_str, info in day_map.items():
        info["task_hours"] = round(info["task_minutes"] / 60.0, 2)

    weeks = []
    for idx in range(0, len(grid_dates), 7):
        weeks.append([day_map[d] for d in grid_dates[idx:idx + 7]])

    if selected_date and selected_date in day_map:
        sel_date = selected_date
    elif today_str in day_map and today_str.startswith(clean_month):
        sel_date = today_str
    else:
        sel_date = "%04d-%02d-01" % (year, month)

    month_label = datetime(year, month, 1).strftime("%B %Y")
    month_days = [day_map[d] for d in grid_dates if d.startswith(clean_month)]
    month_summary = {
        "active_days": len([d for d in month_days if d["total_activity"] > 0]),
        "task_hours": round(sum(d["task_minutes"] for d in month_days) / 60.0, 2),
        "completed_count": sum(d["completed_count"] for d in month_days),
        "total_urges": sum(d["urges"] for d in month_days),
        "resisted_urges": sum(d["resisted"] for d in month_days),
        "gave_in_urges": sum(d["gave_in"] for d in month_days),
        "reflections_count": sum(d["note_count"] for d in month_days),
    }

    return {
        "month": clean_month,
        "month_label": month_label,
        "prev_month": prev_month,
        "next_month": next_month,
        "today": today_str,
        "selected_date": sel_date,
        "selected_day": day_map.get(sel_date),
        "module_filter": module_filter,
        "include_demo": include_demo,
        "weeks": weeks,
        "summary": month_summary,
    }
