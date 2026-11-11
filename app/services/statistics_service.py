from collections import Counter, defaultdict
from datetime import timedelta
from app.repositories import auth_repository, challenge_repository, statistics_repository, task_repository
from app.services import allocation_service, challenge_service, task_service
from app.utils.time_utils import (
    calculate_inclusive_days,
    format_local,
    format_local_date,
    local_date_range_to_utc_bounds,
    local_today_str,
    resolve_period_preset,
    shift_date_str,
    to_local_dt,
    utc_now,
)


def _get_timezone():
    return auth_repository.get_setting("timezone", "UTC") or "UTC"


def _root_owner_map():
    """Map every centered_task_id to its top-level root centered_task_id without double counting."""
    edges = task_repository.list_all_linked_edges()
    parent_of = {e["linked_centered_task_id"]: e["parent_centered_task_id"] for e in edges}

    def find_root(ct_id):
        curr = ct_id
        seen = set()
        while curr in parent_of and curr not in seen:
            seen.add(curr)
            curr = parent_of[curr]
        return curr

    all_cts = task_repository.list_centered_tasks(include_archived=True)
    return {ct["id"]: find_root(ct["id"]) for ct in all_cts}, {ct["id"]: ct for ct in all_cts}


def get_dashboard_summary():
    tz_name = _get_timezone()
    today_str = local_today_str(tz_name)
    upcoming_end_str = shift_date_str(today_str, 7)

    root_tasks = task_repository.list_root_centered_tasks(include_archived=False)
    all_tasks = task_service.list_centered_tasks_with_metrics(include_archived=False)
    metrics_idx = task_service.build_task_metrics_index()
    budget = allocation_service.get_budget_overview()

    overall_task_pct = task_service.compute_workspace_task_progress(root_tasks, metrics_idx)

    # Non-duplicated actual time logged from raw progress entries
    all_entries = statistics_repository.list_progress_entries_in_range(include_demo=True)
    total_time_minutes = sum(float(e["time_spent_minutes"]) for e in all_entries)
    seven_days_ago = (utc_now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    week_time_minutes = 0.0
    today_time_minutes = 0.0
    today_progress_count = 0

    week_dates = [shift_date_str(today_str, -offset) for offset in range(6, -1, -1)]
    week_daily_map = {d: {"minutes": 0.0, "entries": 0} for d in week_dates}

    for e in all_entries:
        mins = float(e["time_spent_minutes"])
        if e["entry_timestamp"] >= seven_days_ago:
            week_time_minutes += mins
        local_d = format_local_date(e["entry_timestamp"], tz_name)
        if local_d == today_str:
            today_time_minutes += mins
            today_progress_count += 1
        if local_d in week_daily_map:
            week_daily_map[local_d]["minutes"] += mins
            week_daily_map[local_d]["entries"] += 1

    weekly_task_hours_series = [
        {"date": d, "hours": round(week_daily_map[d]["minutes"] / 60.0, 2), "entries": week_daily_map[d]["entries"]}
        for d in week_dates
    ]

    overdue_items = task_repository.list_overdue_task_items(today_str)
    upcoming_deadlines = task_repository.list_upcoming_task_items(today_str, upcoming_end_str)[:6]
    completed_tasks_cnt = len(task_repository.list_completed_centered_tasks())
    completed_items_cnt = len(task_repository.list_completed_task_items())
    recent_tasks = task_service.list_centered_tasks_with_metrics(
        sort_by="updated", include_archived=False
    )[:5]
    active_session = task_repository.get_active_session()

    challenges = challenge_service.list_challenges_with_metrics(include_archived=False)
    active_challenges = [c for c in challenges if c["status"] == "Active"]
    all_urge_events = challenge_repository.list_all_events()
    urge_metrics = challenge_service.compute_event_metrics(all_urge_events)
    today_urge_events = [
        e for e in all_urge_events if format_local_date(e["event_timestamp"], tz_name) == today_str
    ]
    today_urge_metrics = challenge_service.compute_event_metrics(today_urge_events)
    pending_urges = [
        e for e in all_urge_events if e["event_type"] == "URGE" and e["outcome"] == "Pending"
    ][:6]

    root_chart_data = []
    for r in root_tasks:
        m = metrics_idx.get(r["id"], {})
        root_chart_data.append(
            {
                "name": r["name"],
                "completion_pct": m.get("completion_pct", 0.0),
                "allocated": float(r["target_allocation"]),
                "actual_hours": m.get("total_time_hours", 0.0),
                "color": r["primary_color"],
            }
        )

    daily_urge_trend = _build_urge_daily_series(all_urge_events, tz_name)[-14:]

    return {
        "today": today_str,
        "overall_task_pct": overall_task_pct,
        "total_centered_tasks": len(all_tasks),
        "total_time_hours": round(total_time_minutes / 60.0, 2),
        "week_time_hours": round(week_time_minutes / 60.0, 2),
        "today_time_hours": round(today_time_minutes / 60.0, 2),
        "today_progress_count": today_progress_count,
        "overdue_count": len(overdue_items),
        "overdue_items": overdue_items[:5],
        "upcoming_deadlines": upcoming_deadlines,
        "completed_count": completed_tasks_cnt + completed_items_cnt,
        "recent_tasks": recent_tasks,
        "active_session": active_session,
        "challenges_count": len(challenges),
        "active_challenges": active_challenges[:5],
        "urge_metrics": urge_metrics,
        "today_urge_metrics": today_urge_metrics,
        "pending_urges": pending_urges,
        "root_chart_data": root_chart_data,
        "weekly_task_hours_series": weekly_task_hours_series,
        "daily_urge_trend": daily_urge_trend,
        "budget_total": budget["total_budget"],
        "budget_unit": budget["budget_unit"],
        "budget_mode": budget["mode"],
        "budget_allocated": budget["allocated_budget"],
        "budget_available": budget["available_budget"],
        "budget_allocated_weight_pct": budget["budgeted_root_weight_sum"],
        "budget_remaining_weight_pct": budget["remaining_unallocated_weight"],
    }


def _build_urge_daily_series(events, tz_name):
    daily_map = {}
    for ev in events:
        ldt = to_local_dt(ev["event_timestamp"], tz_name)
        if not ldt:
            continue
        d = ldt.strftime("%Y-%m-%d")
        row = daily_map.setdefault(
            d, {"thoughts": 0, "urges": 0, "resisted": 0, "gave_in": 0, "pending": 0, "actions": 0}
        )
        if ev["event_type"] == "THOUGHT":
            row["thoughts"] += 1
        elif ev["event_type"] == "URGE":
            row["urges"] += 1
            if ev["outcome"] == "Resisted":
                row["resisted"] += 1
            elif ev["outcome"] == "Gave In":
                row["gave_in"] += 1
            else:
                row["pending"] += 1
        elif ev["event_type"] == "ACTION":
            row["actions"] += 1

    series = []
    for d in sorted(daily_map.keys()):
        r = daily_map[d]
        denom = r["resisted"] + r["gave_in"]
        rate = round((r["resisted"] / float(denom)) * 100.0, 1) if denom > 0 else None
        series.append({"date": d, "resistance_rate": rate, **r})
    return series


def get_global_statistics(start_date=None, end_date=None, include_demo=True, preset=None):
    tz_name = _get_timezone()
    today_str = local_today_str(tz_name)
    start_date, end_date, clean_preset = resolve_period_preset(preset, start_date, end_date, tz_name)
    start_utc, end_utc = local_date_range_to_utc_bounds(start_date, end_date, tz_name)
    budget = allocation_service.get_budget_overview()

    # ------------------------------------------------------------------------
    # MODULE 1: WEIGHTED TASK MANAGER STATS
    # ------------------------------------------------------------------------
    all_centered = task_service.list_centered_tasks_with_metrics(include_archived=False)
    if not include_demo:
        all_centered = [t for t in all_centered if not t.get("is_demo")]

    root_tasks = [t for t in all_centered if not t.get("linked_parent_id")]
    metrics_idx = task_service.build_task_metrics_index()
    root_owner_by_ct, ct_by_id = _root_owner_map()

    overall_progress = task_service.compute_workspace_task_progress(root_tasks, metrics_idx)

    entries = statistics_repository.list_progress_entries_in_range(
        start_utc=start_utc, end_utc=end_utc, include_demo=include_demo
    )
    completed_items_range = statistics_repository.list_completed_items_in_range(
        start_utc=start_utc, end_utc=end_utc, include_demo=include_demo
    )

    total_logged_minutes = 0.0
    time_by_root = defaultdict(float)
    daily_task_map = defaultdict(lambda: {"minutes": 0.0, "entries": 0})
    weekly_task_map = defaultdict(lambda: {"minutes": 0.0, "entries": 0})
    item_range_qty = defaultdict(float)
    drilldown_entries = []

    for e in entries:
        mins = float(e["time_spent_minutes"])
        total_logged_minutes += mins
        root_id = root_owner_by_ct.get(e["parent_centered_task_id"], e["parent_centered_task_id"])
        time_by_root[root_id] += mins
        item_range_qty[e["task_item_id"]] += float(e["quantity_completed"])

        ldt = to_local_dt(e["entry_timestamp"], tz_name)
        d_str = ldt.strftime("%Y-%m-%d") if ldt else ""
        if ldt:
            iso_yr, iso_wk, _ = ldt.isocalendar()
            w_str = "%d-W%02d" % (iso_yr, iso_wk)
            daily_task_map[d_str]["minutes"] += mins
            daily_task_map[d_str]["entries"] += 1
            weekly_task_map[w_str]["minutes"] += mins
            weekly_task_map[w_str]["entries"] += 1

        drilldown_entries.append(
            {
                "date": d_str,
                "timestamp": format_local(e["entry_timestamp"], tz_name),
                "centered_task": e["centered_task_name"],
                "task_item_id": e["task_item_id"],
                "task_item": e["task_item_name"],
                "quantity": round(float(e["quantity_completed"]), 2),
                "unit": e["target_unit"],
                "minutes": round(mins, 1),
                "comments": e.get("comments", ""),
            }
        )

    task_distribution = []
    total_allocated = 0.0
    for r in root_tasks:
        m = metrics_idx.get(r["id"], {})
        alloc_val = float(r["target_allocation"])
        total_allocated += alloc_val
        actual_hrs = round(time_by_root.get(r["id"], 0.0) / 60.0, 2)
        task_distribution.append(
            {
                "id": r["id"],
                "name": r["name"],
                "weight": float(r["weight"]),
                "completion_pct": m.get("completion_pct", 0.0),
                "allocated_target": round(alloc_val, 2),
                "target_unit": r["target_unit"],
                "actual_hours": actual_hrs,
                "color": r["primary_color"],
                "status": r["status"],
            }
        )

    all_items = task_repository.list_all_task_items()
    target_vs_actual_items = []
    for it in all_items:
        if it["item_type"] != "standard" or it["status"] == "Archived":
            continue
        parent_ct = ct_by_id.get(it["parent_centered_task_id"])
        if not parent_ct or parent_ct["status"] == "Archived":
            continue
        if not include_demo and parent_ct.get("is_demo"):
            continue
        totals = task_repository.get_item_progress_totals(it["id"])
        qty_actual = item_range_qty[it["id"]] if (start_utc or end_utc) else totals["total_quantity"]
        target_vs_actual_items.append(
            {
                "id": it["id"],
                "name": it["name"],
                "parent_name": it["parent_name"],
                "target_quantity": round(float(it["target_quantity"]), 2),
                "actual_quantity": round(qty_actual, 2),
                "target_unit": it["target_unit"],
                "status": it["status"],
            }
        )

    completion_trend_map = Counter()
    for ci in completed_items_range:
        ldt = to_local_dt(ci["completed_at"], tz_name)
        if ldt:
            completion_trend_map[ldt.strftime("%Y-%m-%d")] += 1

    overdue_tasks = task_repository.list_overdue_task_items(today_str)
    if not include_demo:
        overdue_tasks = [o for o in overdue_tasks if not ct_by_id.get(o["parent_centered_task_id"], {}).get("is_demo")]

    daily_task_series = [
        {"date": d, "hours": round(daily_task_map[d]["minutes"] / 60.0, 2), "entries": daily_task_map[d]["entries"]}
        for d in sorted(daily_task_map.keys())
    ]
    weekly_task_series = [
        {"week": w, "hours": round(weekly_task_map[w]["minutes"] / 60.0, 2), "entries": weekly_task_map[w]["entries"]}
        for w in sorted(weekly_task_map.keys())
    ]
    completion_trend = [
        {"date": d, "completed": completion_trend_map[d]} for d in sorted(completion_trend_map.keys())
    ]

    # ------------------------------------------------------------------------
    # MODULE 2: URGE & RESISTANCE STATS
    # ------------------------------------------------------------------------
    urge_events = statistics_repository.list_urge_events_in_range(
        start_utc=start_utc, end_utc=end_utc, include_demo=include_demo
    )
    urge_summary = challenge_service.compute_event_metrics(urge_events)
    trigger_analytics = challenge_service.compute_trigger_analytics(urge_events, tz_name)

    hourly_map = [{"hour": "%02d:00" % h, "thoughts": 0, "urges": 0, "actions": 0} for h in range(24)]
    weekly_urge_map = defaultdict(lambda: {"thoughts": 0, "urges": 0, "resisted": 0, "gave_in": 0, "actions": 0})
    monthly_urge_map = defaultdict(lambda: {"thoughts": 0, "urges": 0, "resisted": 0, "gave_in": 0, "actions": 0})
    events_by_challenge = defaultdict(list)
    drilldown_events = []

    for ev in urge_events:
        events_by_challenge[ev["challenge_id"]].append(ev)
        ldt = to_local_dt(ev["event_timestamp"], tz_name)
        d_str = ldt.strftime("%Y-%m-%d") if ldt else ""
        if ldt:
            hr = ldt.hour
            iso_yr, iso_wk, _ = ldt.isocalendar()
            w_key = "%d-W%02d" % (iso_yr, iso_wk)
            m_key = ldt.strftime("%Y-%m")
            etype = ev["event_type"]
            if etype == "THOUGHT":
                hourly_map[hr]["thoughts"] += 1
                weekly_urge_map[w_key]["thoughts"] += 1
                monthly_urge_map[m_key]["thoughts"] += 1
            elif etype == "URGE":
                hourly_map[hr]["urges"] += 1
                weekly_urge_map[w_key]["urges"] += 1
                monthly_urge_map[m_key]["urges"] += 1
                if ev["outcome"] == "Resisted":
                    weekly_urge_map[w_key]["resisted"] += 1
                    monthly_urge_map[m_key]["resisted"] += 1
                elif ev["outcome"] == "Gave In":
                    weekly_urge_map[w_key]["gave_in"] += 1
                    monthly_urge_map[m_key]["gave_in"] += 1
            elif etype == "ACTION":
                hourly_map[hr]["actions"] += 1
                weekly_urge_map[w_key]["actions"] += 1
                monthly_urge_map[m_key]["actions"] += 1

        trig_label = ev.get("trigger_category") or ev.get("trigger_text") or ""
        drilldown_events.append(
            {
                "date": d_str,
                "timestamp": format_local(ev["event_timestamp"], tz_name),
                "challenge_id": ev["challenge_id"],
                "challenge_name": ev["challenge_name"],
                "event_type": ev["event_type"],
                "outcome": ev["outcome"],
                "trigger_category": trig_label,
                "trigger_text": ev.get("trigger_text", ""),
                "comments": ev.get("comments", ""),
            }
        )

    daily_urge_series = _build_urge_daily_series(urge_events, tz_name)
    weekly_urge_series = [{"week": k, **weekly_urge_map[k]} for k in sorted(weekly_urge_map.keys())]
    monthly_urge_series = [{"month": k, **monthly_urge_map[k]} for k in sorted(monthly_urge_map.keys())]

    top_triggers = [
        {"trigger": r["trigger"], "count": r["total"], "resisted": r["resisted"], "gave_in": r["gave_in"]}
        for r in trigger_analytics["categories"][:10]
    ]

    all_challenges = challenge_repository.list_challenges(include_archived=False)
    if not include_demo:
        all_challenges = [c for c in all_challenges if not c.get("is_demo")]

    challenge_comparison = []
    for ch in all_challenges:
        ch_evs = events_by_challenge.get(ch["id"], [])
        m = challenge_service.compute_event_metrics(ch_evs)
        challenge_comparison.append(
            {
                "id": ch["id"],
                "name": ch["name"],
                "status": ch["status"],
                "accent_color": ch.get("accent_color", "#0D9488"),
                **m,
            }
        )

    # ------------------------------------------------------------------------
    # PERIOD COMPARISON (when a bounded range / preset is active)
    # ------------------------------------------------------------------------
    total_logged_hours = round(total_logged_minutes / 60.0, 2)
    comparison = {"has_comparison": False}
    if start_date and end_date:
        span_days = calculate_inclusive_days(start_date, end_date) or 1
        prev_end = shift_date_str(start_date, -1)
        prev_start = shift_date_str(prev_end, -(span_days - 1))
        prev_s_utc, prev_e_utc = local_date_range_to_utc_bounds(prev_start, prev_end, tz_name)

        prev_entries = statistics_repository.list_progress_entries_in_range(
            start_utc=prev_s_utc, end_utc=prev_e_utc, include_demo=include_demo
        )
        prev_comp = statistics_repository.list_completed_items_in_range(
            start_utc=prev_s_utc, end_utc=prev_e_utc, include_demo=include_demo
        )
        prev_events = statistics_repository.list_urge_events_in_range(
            start_utc=prev_s_utc, end_utc=prev_e_utc, include_demo=include_demo
        )
        prev_hours = round(sum(float(p["time_spent_minutes"]) for p in prev_entries) / 60.0, 2)
        prev_urge_metrics = challenge_service.compute_event_metrics(prev_events)
        rate_delta = None
        if urge_summary["resistance_rate"] is not None and prev_urge_metrics["resistance_rate"] is not None:
            rate_delta = round(urge_summary["resistance_rate"] - prev_urge_metrics["resistance_rate"], 1)

        comparison = {
            "has_comparison": True,
            "prev_start": prev_start,
            "prev_end": prev_end,
            "span_days": span_days,
            "prev_logged_hours": prev_hours,
            "logged_hours_delta": round(total_logged_hours - prev_hours, 2),
            "prev_completed_items": len(prev_comp),
            "completed_items_delta": len(completed_items_range) - len(prev_comp),
            "prev_total_urges": prev_urge_metrics["total_urges"],
            "total_urges_delta": urge_summary["total_urges"] - prev_urge_metrics["total_urges"],
            "prev_resistance_rate": prev_urge_metrics["resistance_rate"],
            "resistance_rate_delta": rate_delta,
        }

    return {
        "preset": clean_preset,
        "start_date": start_date,
        "end_date": end_date,
        "comparison": comparison,
        "tasks": {
            "overall_progress": overall_progress,
            "total_allocated": round(total_allocated, 2),
            "total_budget": budget["total_budget"],
            "available_budget": budget["available_budget"],
            "allocated_weight_pct": budget["budgeted_root_weight_sum"],
            "remaining_weight_pct": budget["remaining_unallocated_weight"],
            "total_logged_hours": total_logged_hours,
            "budget_unit": budget["budget_unit"],
            "completed_items_count": len(completed_items_range),
            "overdue_tasks": overdue_tasks,
            "distribution": task_distribution,
            "target_vs_actual_items": target_vs_actual_items[:15],
            "daily_series": daily_task_series,
            "weekly_series": weekly_task_series,
            "completion_trend": completion_trend,
            "drilldown_entries": list(reversed(drilldown_entries[-250:])),
        },
        "challenges": {
            "summary": urge_summary,
            "top_triggers": top_triggers,
            "trigger_analytics": trigger_analytics,
            "hourly_distribution": hourly_map,
            "daily_series": daily_urge_series,
            "weekly_series": weekly_urge_series,
            "monthly_series": monthly_urge_series,
            "comparison": challenge_comparison,
            "drilldown_events": list(reversed(drilldown_events[-250:])),
        },
    }

