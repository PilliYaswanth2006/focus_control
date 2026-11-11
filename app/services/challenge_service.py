import json
from collections import Counter, defaultdict
from app.database.transaction import transaction
from app.repositories import auth_repository, challenge_repository
from app.utils.time_utils import (
    calculate_inclusive_days,
    format_local_date,
    local_date_range_to_utc_bounds,
    local_input_to_utc,
    local_today_str,
    shift_date_str,
    to_local_dt,
    utc_now_iso,
)
from app.utils.uploads import resolve_background_choice
from app.utils.validation import (
    PREDEFINED_TRIGGERS,
    VALID_CARD_STYLES,
    VALID_EVENT_TYPES,
    VALID_FONTS,
    VALID_LAYOUT_STYLES,
    VALID_URGE_OUTCOMES,
    ValidationError,
    clean_optional_text,
    normalize_trigger,
    parse_float,
    parse_int,
    parse_metadata_json,
    require_non_empty,
    validate_choice,
    validate_date_order,
    validate_date_str,
    validate_hex_color,
)


VALID_FONT_SIZES = ("14px", "15px", "16px", "17px", "18px")


def _get_timezone():
    return auth_repository.get_setting("timezone", "UTC") or "UTC"


def _parse_metadata_dict(raw_json):
    try:
        parsed = json.loads(raw_json or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def compute_event_metrics(events):
    """
    Compute strict non-mixed metrics:
    - Resistance rate = Resisted Urges / (Resisted Urges + Gave-in Urges) * 100
    - Pending urges excluded from denominator.
    - Thoughts, Urges, and Actions are never mixed or double-counted.
    """
    total_thoughts = 0
    total_urges = 0
    resisted_urges = 0
    gave_in_urges = 0
    pending_urges = 0
    total_actions = 0

    for ev in events:
        etype = ev["event_type"]
        if etype == "THOUGHT":
            total_thoughts += 1
        elif etype == "URGE":
            total_urges += 1
            if ev["outcome"] == "Resisted":
                resisted_urges += 1
            elif ev["outcome"] == "Gave In":
                gave_in_urges += 1
            elif ev["outcome"] == "Pending":
                pending_urges += 1
        elif etype == "ACTION":
            total_actions += 1

    denom = resisted_urges + gave_in_urges
    if denom > 0:
        rate = round((resisted_urges / float(denom)) * 100.0, 1)
        rate_display = "%.1f%%" % rate
    else:
        rate = None
        rate_display = "N/A"

    return {
        "total_thoughts": total_thoughts,
        "total_urges": total_urges,
        "resisted_urges": resisted_urges,
        "gave_in_urges": gave_in_urges,
        "pending_urges": pending_urges,
        "total_actions": total_actions,
        "decided_urges": denom,
        "resistance_rate": rate,
        "resistance_rate_display": rate_display,
    }


def compute_trigger_analytics(events, tz_name="UTC"):
    """
    Aggregate trigger frequency, outcomes per trigger category, resistance rates,
    and daily frequency series for top triggers.
    """
    buckets = {}
    text_counter = Counter()
    date_trigger_counts = defaultdict(lambda: defaultdict(int))
    all_dates = set()

    for ev in events:
        raw_cat = (ev.get("trigger_category") or "").strip()
        raw_txt = (ev.get("trigger_text") or "").strip()
        if not raw_cat and not raw_txt:
            continue

        cat = raw_cat or normalize_trigger("", raw_txt)[0] or "Other"
        b = buckets.setdefault(
            cat,
            {
                "trigger": cat,
                "total": 0,
                "thoughts": 0,
                "urges": 0,
                "resisted": 0,
                "gave_in": 0,
                "pending": 0,
                "actions": 0,
            },
        )
        b["total"] += 1
        etype = ev["event_type"]
        if etype == "THOUGHT":
            b["thoughts"] += 1
        elif etype == "URGE":
            b["urges"] += 1
            if ev["outcome"] == "Resisted":
                b["resisted"] += 1
            elif ev["outcome"] == "Gave In":
                b["gave_in"] += 1
            else:
                b["pending"] += 1
        elif etype == "ACTION":
            b["actions"] += 1

        display_label = raw_txt if raw_txt else cat
        text_counter[display_label] += 1

        ldt = to_local_dt(ev["event_timestamp"], tz_name)
        if ldt:
            d_str = ldt.strftime("%Y-%m-%d")
            all_dates.add(d_str)
            date_trigger_counts[d_str][cat] += 1

    rows = []
    for cat, b in buckets.items():
        decided = b["resisted"] + b["gave_in"]
        rate = round((b["resisted"] / float(decided)) * 100.0, 1) if decided > 0 else None
        b["decided_urges"] = decided
        b["resistance_rate"] = rate
        b["resistance_rate_display"] = ("%.1f%%" % rate) if rate is not None else "N/A"
        rows.append(b)

    rows.sort(key=lambda r: (-r["total"], -r["urges"], r["trigger"]))

    sorted_dates = sorted(all_dates)
    top_cats = [r["trigger"] for r in rows[:5]]
    trend_series = {cat: [date_trigger_counts[d].get(cat, 0) for d in sorted_dates] for cat in top_cats}

    return {
        "categories": rows,
        "top_custom_texts": [{"trigger": k, "count": v} for k, v in text_counter.most_common(10)],
        "trend_dates": sorted_dates,
        "trend_categories": top_cats,
        "trend_series": trend_series,
    }


def list_challenges_with_metrics(status=None, search=None, include_archived=True):
    challenges = challenge_repository.list_challenges(
        status=status, search=search, include_archived=include_archived
    )
    all_events = challenge_repository.list_all_events()
    events_by_challenge = {}
    for ev in all_events:
        events_by_challenge.setdefault(ev["challenge_id"], []).append(ev)

    for ch in challenges:
        ch_events = events_by_challenge.get(ch["id"], [])
        cur_cycle_events = [e for e in ch_events if e["cycle_id"] == ch["current_cycle_id"]]
        ch["metrics"] = compute_event_metrics(cur_cycle_events)
        ch["all_time_metrics"] = compute_event_metrics(ch_events)
        ch["metadata"] = _parse_metadata_dict(ch.get("metadata_json"))
        if ch.get("planned_duration_days") is None and ch.get("start_date") and ch.get("end_date"):
            ch["planned_duration_days"] = calculate_inclusive_days(ch["start_date"], ch["end_date"])
    return challenges


def get_challenge_details(challenge_id, cycle_id=None, start_date=None, end_date=None):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        return None

    tz_name = _get_timezone()
    ch["metadata"] = _parse_metadata_dict(ch.get("metadata_json"))
    if ch.get("planned_duration_days") is None and ch.get("start_date") and ch.get("end_date"):
        ch["planned_duration_days"] = calculate_inclusive_days(ch["start_date"], ch["end_date"])

    cycles = challenge_repository.list_cycles_for_challenge(challenge_id)
    valid_cycle_ids = {c["id"] for c in cycles}
    all_events = challenge_repository.list_events_for_challenge(challenge_id, limit=2000)

    if cycle_id == "all":
        selected_cycle_id = None
    elif cycle_id:
        try:
            parsed_cid = int(cycle_id)
            selected_cycle_id = parsed_cid if parsed_cid in valid_cycle_ids else ch["current_cycle_id"]
        except (ValueError, TypeError):
            selected_cycle_id = ch["current_cycle_id"]
    else:
        selected_cycle_id = ch["current_cycle_id"]

    start_utc, end_utc = local_date_range_to_utc_bounds(start_date, end_date, tz_name)
    filtered_events = []
    for ev in all_events:
        if selected_cycle_id and ev["cycle_id"] != selected_cycle_id:
            continue
        if start_utc and ev["event_timestamp"] < start_utc:
            continue
        if end_utc and ev["event_timestamp"] > end_utc:
            continue
        filtered_events.append(ev)

    events_by_cycle = {}
    for ev in all_events:
        events_by_cycle.setdefault(ev["cycle_id"], []).append(ev)

    cycle_comparisons = []
    for cyc in cycles:
        cyc_events = events_by_cycle.get(cyc["id"], [])
        cyc_copy = dict(cyc)
        cyc_copy["metrics"] = compute_event_metrics(cyc_events)
        cycle_comparisons.append(cyc_copy)

    ch["cycles"] = cycle_comparisons
    ch["selected_cycle_id"] = selected_cycle_id
    ch["events"] = filtered_events
    ch["metrics"] = compute_event_metrics(filtered_events)
    ch["all_time_metrics"] = compute_event_metrics(all_events)
    ch["pending_urge_list"] = [
        e for e in all_events if e["event_type"] == "URGE" and e["outcome"] == "Pending"
    ]
    ch["linkable_urges_list"] = [
        e for e in all_events if e["event_type"] == "URGE" and e["outcome"] in ("Pending", "Gave In")
    ]
    ch["trigger_analytics"] = compute_trigger_analytics(filtered_events, tz_name)
    ch["predefined_triggers"] = PREDEFINED_TRIGGERS
    ch["analytics"] = _build_challenge_charts(filtered_events, tz_name)
    return ch


def _build_challenge_charts(events, tz_name):
    daily_map = {}
    hour_counts = [{"hour": "%02d:00" % h, "thoughts": 0, "urges": 0, "actions": 0} for h in range(24)]
    trigger_counter = Counter()

    for ev in events:
        local_dt = to_local_dt(ev["event_timestamp"], tz_name)
        if local_dt is None:
            continue
        day_str = local_dt.strftime("%Y-%m-%d")
        bucket = daily_map.setdefault(
            day_str, {"thoughts": 0, "urges": 0, "resisted": 0, "gave_in": 0, "actions": 0}
        )
        hr = local_dt.hour
        etype = ev["event_type"]
        if etype == "THOUGHT":
            bucket["thoughts"] += 1
            hour_counts[hr]["thoughts"] += 1
        elif etype == "URGE":
            bucket["urges"] += 1
            hour_counts[hr]["urges"] += 1
            if ev["outcome"] == "Resisted":
                bucket["resisted"] += 1
            elif ev["outcome"] == "Gave In":
                bucket["gave_in"] += 1
        elif etype == "ACTION":
            bucket["actions"] += 1
            hour_counts[hr]["actions"] += 1

        label = (ev.get("trigger_category") or ev.get("trigger_text") or "").strip()
        if label:
            trigger_counter[label] += 1

    sorted_days = sorted(daily_map.keys())
    daily_series = []
    for d in sorted_days:
        row = daily_map[d]
        daily_series.append({"date": d, **row})

    top_triggers = [{"trigger": k, "count": v} for k, v in trigger_counter.most_common(8)]
    return {
        "daily_series": daily_series,
        "hourly_distribution": hour_counts,
        "top_triggers": top_triggers,
    }


def _extract_challenge_settings(form_data, bg_file=None, existing=None):
    font_family = validate_choice(
        form_data.get("font_family"), VALID_FONTS, "Font family",
        default=(existing["font_family"] if existing else "Inter")
    )
    font_size = validate_choice(
        form_data.get("font_size"), VALID_FONT_SIZES, "Font size",
        default=(existing["font_size"] if existing else "16px")
    )
    accent_color = validate_hex_color(
        form_data.get("accent_color"), default=(existing["accent_color"] if existing else "#0D9488")
    )
    text_color = validate_hex_color(form_data.get("text_color"), default="")
    card_style = validate_choice(
        form_data.get("card_style"), VALID_CARD_STYLES, "Card style",
        default=(existing["card_style"] if existing else "elevated")
    )
    layout_style = validate_choice(
        form_data.get("layout_style"), VALID_LAYOUT_STYLES, "Layout style",
        default=(existing["layout_style"] if existing else "comfortable")
    )
    metadata_json = parse_metadata_json(
        form_data.get("metadata_json"),
        form_data.getlist("meta_key") if hasattr(form_data, "getlist") else None,
        form_data.getlist("meta_value") if hasattr(form_data, "getlist") else None,
    )
    bg_choice = form_data.get("background_preset", "__keep__" if existing else "")
    bg_path, bg_mode = resolve_background_choice(
        bg_file,
        bg_choice,
        current_bg=(existing["background_image"] if existing else ""),
        current_mode=(existing["background_mode"] if existing else "none"),
    )
    return {
        "background_image": bg_path,
        "background_mode": bg_mode,
        "font_family": font_family,
        "font_size": font_size,
        "text_color": text_color,
        "accent_color": accent_color,
        "card_style": card_style,
        "layout_style": layout_style,
        "metadata_json": metadata_json,
    }


def create_challenge(form_data, bg_file=None):
    name = require_non_empty(form_data.get("name"), "Challenge name", max_len=140)
    description = clean_optional_text(form_data.get("description"), max_len=2000)
    behaviour = require_non_empty(form_data.get("behaviour_to_avoid"), "Behaviour to avoid", max_len=200)
    objective = clean_optional_text(form_data.get("objective"), max_len=500)
    start_date = validate_date_str(form_data.get("start_date"), "Start date") or local_today_str(_get_timezone())
    end_date = validate_date_str(form_data.get("end_date"), "End date")
    validate_date_order(start_date, end_date, "Start date", "End date")

    raw_duration = (form_data.get("planned_duration_days") or "").strip()
    if raw_duration:
        planned_duration_days = parse_int(raw_duration, "Planned duration (days)", min_val=1, max_val=36500)
    else:
        planned_duration_days = calculate_inclusive_days(start_date, end_date)

    target_value = parse_float(form_data.get("target_value"), "Target value", min_val=0.0, max_val=1000000.0, default=0.0)
    target_unit = clean_optional_text(form_data.get("target_unit"), max_len=40)

    start_immediately = str(form_data.get("start_immediately", "1")).lower() in ("1", "true", "on", "yes")
    status = "Active" if start_immediately else "Not Started"
    settings_data = _extract_challenge_settings(form_data, bg_file=bg_file, existing=None)
    now_utc = utc_now_iso()
    settings_data["updated_at"] = now_utc

    with transaction() as conn:
        challenge_id = challenge_repository.insert_challenge(
            {
                "name": name,
                "description": description,
                "behaviour_to_avoid": behaviour,
                "objective": objective,
                "start_date": start_date,
                "end_date": end_date,
                "planned_duration_days": planned_duration_days,
                "target_value": target_value,
                "target_unit": target_unit,
                "status": status,
                "current_cycle_id": None,
                "is_demo": 0,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        cycle_id = challenge_repository.insert_cycle(
            {
                "challenge_id": challenge_id,
                "cycle_number": 1,
                "status": status,
                "started_at": now_utc,
                "ended_at": None,
                "reset_reason": "",
                "created_at": now_utc,
            },
            conn=conn,
        )
        challenge_repository.update_challenge_status_and_cycle(
            challenge_id, status, cycle_id, None, now_utc, conn=conn
        )
        challenge_repository.upsert_challenge_settings(challenge_id, settings_data, conn=conn)
        auth_repository.insert_activity_log(
            "challenges",
            "challenge_created",
            "challenge",
            challenge_id,
            "Created challenge '%s' (%s)" % (name, status),
            now_utc,
            conn=conn,
        )
    return challenge_id


def update_challenge(challenge_id, form_data, bg_file=None):
    existing = challenge_repository.get_challenge(challenge_id)
    if not existing:
        raise ValidationError("Challenge not found.")

    name = require_non_empty(form_data.get("name"), "Challenge name", max_len=140)
    description = clean_optional_text(form_data.get("description"), max_len=2000)
    behaviour = require_non_empty(form_data.get("behaviour_to_avoid"), "Behaviour to avoid", max_len=200)
    objective = clean_optional_text(form_data.get("objective"), max_len=500)
    start_date = validate_date_str(form_data.get("start_date"), "Start date")
    end_date = validate_date_str(form_data.get("end_date"), "End date")
    validate_date_order(start_date, end_date, "Start date", "End date")

    raw_duration = (form_data.get("planned_duration_days") or "").strip()
    if raw_duration:
        planned_duration_days = parse_int(raw_duration, "Planned duration (days)", min_val=1, max_val=36500)
    else:
        planned_duration_days = calculate_inclusive_days(start_date, end_date)

    target_value = parse_float(
        form_data.get("target_value"), "Target value", min_val=0.0, max_val=1000000.0,
        default=existing.get("target_value") or 0.0
    )
    target_unit = (
        clean_optional_text(form_data.get("target_unit"), max_len=40)
        if "target_unit" in form_data
        else existing.get("target_unit", "")
    )

    settings_data = _extract_challenge_settings(form_data, bg_file=bg_file, existing=existing)
    now_utc = utc_now_iso()
    settings_data["updated_at"] = now_utc

    with transaction() as conn:
        challenge_repository.update_challenge(
            challenge_id,
            {
                "name": name,
                "description": description,
                "behaviour_to_avoid": behaviour,
                "objective": objective,
                "start_date": start_date,
                "end_date": end_date,
                "planned_duration_days": planned_duration_days,
                "target_value": target_value,
                "target_unit": target_unit,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        challenge_repository.upsert_challenge_settings(challenge_id, settings_data, conn=conn)
        auth_repository.insert_activity_log(
            "challenges", "challenge_updated", "challenge", challenge_id, "Updated '%s'" % name, now_utc, conn=conn
        )


def start_challenge(challenge_id):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    if ch["status"] not in ("Not Started", "Paused"):
        raise ValidationError("Only Not Started or Paused challenges can be started.")

    now_utc = utc_now_iso()
    with transaction() as conn:
        cycle_id = ch["current_cycle_id"]
        if not cycle_id:
            next_num = challenge_repository.get_max_cycle_number(challenge_id, conn=conn) + 1
            cycle_id = challenge_repository.insert_cycle(
                {
                    "challenge_id": challenge_id,
                    "cycle_number": next_num,
                    "status": "Active",
                    "started_at": now_utc,
                    "ended_at": None,
                    "reset_reason": "",
                    "created_at": now_utc,
                },
                conn=conn,
            )
        else:
            challenge_repository.update_cycle_status(cycle_id, "Active", started_at=now_utc, conn=conn)

        challenge_repository.update_challenge_status_and_cycle(
            challenge_id, "Active", cycle_id, None, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges", "challenge_started", "challenge", challenge_id, "Started '%s'" % ch["name"], now_utc, conn=conn
        )


def pause_challenge(challenge_id):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    if ch["status"] != "Active":
        raise ValidationError("Only Active challenges can be paused.")

    now_utc = utc_now_iso()
    with transaction() as conn:
        if ch["current_cycle_id"]:
            challenge_repository.update_cycle_status(ch["current_cycle_id"], "Paused", conn=conn)
        challenge_repository.update_challenge_status_and_cycle(
            challenge_id, "Paused", ch["current_cycle_id"], None, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges", "challenge_paused", "challenge", challenge_id, "Paused '%s'" % ch["name"], now_utc, conn=conn
        )


def resume_challenge(challenge_id):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    if ch["status"] != "Paused":
        raise ValidationError("Only Paused challenges can be resumed.")

    now_utc = utc_now_iso()
    with transaction() as conn:
        if ch["current_cycle_id"]:
            challenge_repository.update_cycle_status(ch["current_cycle_id"], "Active", conn=conn)
        challenge_repository.update_challenge_status_and_cycle(
            challenge_id, "Active", ch["current_cycle_id"], None, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges", "challenge_resumed", "challenge", challenge_id, "Resumed '%s'" % ch["name"], now_utc, conn=conn
        )


def reset_challenge(challenge_id, reason=""):
    """Archive/close the current cycle preserving all historical records, and start a fresh cycle."""
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    if ch["status"] == "Archived":
        raise ValidationError("Unarchive challenge before resetting.")

    clean_reason = clean_optional_text(reason, max_len=400) or "User reset challenge for a new cycle"
    now_utc = utc_now_iso()

    with transaction() as conn:
        if ch["current_cycle_id"]:
            challenge_repository.update_cycle_status(
                ch["current_cycle_id"], "Reset", ended_at=now_utc, reset_reason=clean_reason, conn=conn
            )
        next_num = challenge_repository.get_max_cycle_number(challenge_id, conn=conn) + 1
        new_cycle_id = challenge_repository.insert_cycle(
            {
                "challenge_id": challenge_id,
                "cycle_number": next_num,
                "status": "Active",
                "started_at": now_utc,
                "ended_at": None,
                "reset_reason": "",
                "created_at": now_utc,
            },
            conn=conn,
        )
        challenge_repository.update_challenge_status_and_cycle(
            challenge_id, "Active", new_cycle_id, None, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges",
            "challenge_reset",
            "challenge",
            challenge_id,
            "Reset '%s' -> started Cycle #%d (previous records preserved)" % (ch["name"], next_num),
            now_utc,
            conn=conn,
        )
    return new_cycle_id


def complete_challenge(challenge_id):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")

    now_utc = utc_now_iso()
    with transaction() as conn:
        if ch["current_cycle_id"]:
            challenge_repository.update_cycle_status(
                ch["current_cycle_id"], "Completed", ended_at=now_utc, conn=conn
            )
        challenge_repository.update_challenge_status_and_cycle(
            challenge_id, "Completed", ch["current_cycle_id"], now_utc, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges", "challenge_completed", "challenge", challenge_id, "Completed '%s'" % ch["name"], now_utc, conn=conn
        )


def archive_challenge(challenge_id, unarchive=False):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    now_utc = utc_now_iso()
    new_status = "Paused" if unarchive else "Archived"
    with transaction() as conn:
        challenge_repository.update_challenge_status_and_cycle(
            challenge_id, new_status, ch["current_cycle_id"], None, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges",
            "challenge_unarchived" if unarchive else "challenge_archived",
            "challenge",
            challenge_id,
            "%s '%s'" % (new_status, ch["name"]),
            now_utc,
            conn=conn,
        )


def delete_challenge(challenge_id, confirm_force=False, permanent=False):
    ch = challenge_repository.get_challenge(challenge_id, include_deleted=permanent)
    if not ch:
        raise ValidationError("Challenge not found.")
    ev_count = challenge_repository.count_events_for_challenge(challenge_id)
    if ev_count > 0 and not confirm_force:
        raise ValidationError(
            "This challenge has %d historical event(s). Archive it or confirm moving it to Trash."
            % ev_count
        )
    now_utc = utc_now_iso()
    with transaction() as conn:
        if permanent:
            challenge_repository.delete_challenge_full(challenge_id, conn=conn)
            action = "challenge_purged"
            detail = "Permanently deleted challenge '%s' (events removed: %d)" % (ch["name"], ev_count)
        else:
            challenge_repository.soft_delete_challenge(challenge_id, now_utc, conn=conn)
            action = "challenge_deleted"
            detail = "Moved challenge '%s' to Trash (events preserved: %d)" % (ch["name"], ev_count)

        auth_repository.insert_activity_log(
            "challenges",
            action,
            "challenge",
            challenge_id,
            detail,
            now_utc,
            conn=conn,
        )


def restore_challenge(challenge_id):
    ch = challenge_repository.get_challenge(challenge_id, include_deleted=True)
    if not ch or not ch.get("is_deleted"):
        raise ValidationError("Deleted challenge not found in Trash.")
    now_utc = utc_now_iso()
    with transaction() as conn:
        challenge_repository.restore_challenge(challenge_id, ch.get("deleted_at"), now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "challenges",
            "challenge_restored",
            "challenge",
            challenge_id,
            "Restored challenge '%s' from Trash" % ch["name"],
            now_utc,
            conn=conn,
        )


def _normalize_event_type_and_outcome(event_type_raw, outcome_raw):
    etype = validate_choice((event_type_raw or "").upper(), VALID_EVENT_TYPES, "Event type")
    if etype == "THOUGHT":
        outcome = "Observed"
    elif etype == "URGE":
        outcome = validate_choice(outcome_raw, VALID_URGE_OUTCOMES, "Urge outcome", default="Pending")
    else:
        outcome = "Occurred"
    return etype, outcome


def record_event(challenge_id, form_data):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    if ch["status"] == "Archived":
        raise ValidationError("Cannot record events on an archived challenge.")

    etype, outcome = _normalize_event_type_and_outcome(
        form_data.get("event_type"), form_data.get("outcome")
    )
    tz_name = _get_timezone()
    raw_ts = (form_data.get("event_timestamp") or "").strip()
    event_ts_utc = local_input_to_utc(raw_ts, tz_name) if raw_ts else utc_now_iso()

    trigger_category, trigger_text = normalize_trigger(
        form_data.get("trigger_category"), form_data.get("trigger_text")
    )
    context = clean_optional_text(form_data.get("context"), max_len=300)
    duration_seconds = parse_int(
        form_data.get("duration_seconds"), "Duration (seconds)", min_val=0, max_val=86400, default=0
    )
    comments = clean_optional_text(form_data.get("comments"), max_len=2000)
    tags = clean_optional_text(form_data.get("tags"), max_len=300)

    raw_related_urge = (form_data.get("related_urge_id") or "").strip()
    related_urge_id = int(raw_related_urge) if raw_related_urge else None

    now_utc = utc_now_iso()
    with transaction() as conn:
        cycle_id = ch["current_cycle_id"]
        if not cycle_id:
            cycle_id = challenge_repository.insert_cycle(
                {
                    "challenge_id": challenge_id,
                    "cycle_number": 1,
                    "status": "Active",
                    "started_at": now_utc,
                    "ended_at": None,
                    "reset_reason": "",
                    "created_at": now_utc,
                },
                conn=conn,
            )
            challenge_repository.update_challenge_status_and_cycle(
                challenge_id, "Active", cycle_id, None, now_utc, conn=conn
            )
        elif ch["status"] == "Not Started":
            challenge_repository.update_cycle_status(cycle_id, "Active", started_at=now_utc, conn=conn)
            challenge_repository.update_challenge_status_and_cycle(
                challenge_id, "Active", cycle_id, None, now_utc, conn=conn
            )

        if etype == "ACTION" and related_urge_id is not None:
            rel_ev = challenge_repository.get_event(related_urge_id, conn=conn)
            if not rel_ev or rel_ev["challenge_id"] != int(challenge_id) or rel_ev["event_type"] != "URGE":
                raise ValidationError("Linked urge event is invalid for this challenge.")
            if rel_ev["outcome"] == "Pending":
                challenge_repository.update_event_outcome(related_urge_id, "Gave In", now_utc, conn=conn)
        else:
            related_urge_id = None

        event_id = challenge_repository.insert_event(
            {
                "challenge_id": challenge_id,
                "cycle_id": cycle_id,
                "event_type": etype,
                "outcome": outcome,
                "related_urge_id": related_urge_id,
                "event_timestamp": event_ts_utc,
                "trigger_category": trigger_category,
                "trigger_text": trigger_text,
                "context": context,
                "duration_seconds": duration_seconds,
                "comments": comments,
                "tags": tags,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        auth_repository.insert_activity_log(
            "challenges",
            "event_recorded",
            "urge_event",
            event_id,
            "%s (%s) on '%s'" % (etype, outcome, ch["name"]),
            now_utc,
            conn=conn,
        )
    return event_id


def update_event(event_id, form_data):
    existing = challenge_repository.get_event(event_id)
    if not existing:
        raise ValidationError("Event not found.")

    etype, outcome = _normalize_event_type_and_outcome(
        form_data.get("event_type", existing["event_type"]),
        form_data.get("outcome", existing["outcome"]),
    )
    tz_name = _get_timezone()
    raw_ts = (form_data.get("event_timestamp") or "").strip()
    event_ts_utc = local_input_to_utc(raw_ts, tz_name) if raw_ts else existing["event_timestamp"]

    if "trigger_category" in form_data or "trigger_text" in form_data:
        raw_cat = form_data.get("trigger_category", existing.get("trigger_category", ""))
        raw_txt = form_data.get("trigger_text", existing.get("trigger_text", ""))
        trigger_category, trigger_text = normalize_trigger(raw_cat, raw_txt)
    else:
        trigger_category = existing.get("trigger_category", "")
        trigger_text = existing.get("trigger_text", "")

    context = clean_optional_text(form_data.get("context", existing["context"]), max_len=300)
    duration_seconds = parse_int(
        form_data.get("duration_seconds"), "Duration (seconds)", min_val=0, max_val=86400,
        default=existing["duration_seconds"]
    )
    comments = clean_optional_text(form_data.get("comments", existing["comments"]), max_len=2000)
    tags = clean_optional_text(form_data.get("tags", existing["tags"]), max_len=300)

    if etype == "ACTION":
        if "related_urge_id" in form_data:
            raw_rel = (form_data.get("related_urge_id") or "").strip()
            related_urge_id = int(raw_rel) if raw_rel else None
        else:
            related_urge_id = existing["related_urge_id"]
    else:
        related_urge_id = None

    now_utc = utc_now_iso()

    with transaction() as conn:
        if etype == "ACTION" and related_urge_id is not None:
            rel_ev = challenge_repository.get_event(related_urge_id, conn=conn)
            if not rel_ev or rel_ev["challenge_id"] != existing["challenge_id"] or rel_ev["event_type"] != "URGE":
                raise ValidationError("Linked urge event is invalid for this challenge.")
            if rel_ev["outcome"] == "Pending":
                challenge_repository.update_event_outcome(related_urge_id, "Gave In", now_utc, conn=conn)

        challenge_repository.update_event(
            event_id,
            {
                "event_type": etype,
                "outcome": outcome,
                "related_urge_id": related_urge_id,
                "event_timestamp": event_ts_utc,
                "trigger_category": trigger_category,
                "trigger_text": trigger_text,
                "context": context,
                "duration_seconds": duration_seconds,
                "comments": comments,
                "tags": tags,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        auth_repository.insert_activity_log(
            "challenges",
            "event_updated",
            "urge_event",
            event_id,
            "Edited %s event #%d on '%s'" % (etype, event_id, existing["challenge_name"]),
            now_utc,
            conn=conn,
        )


def resolve_pending_urge(event_id, outcome):
    existing = challenge_repository.get_event(event_id)
    if not existing:
        raise ValidationError("Urge event not found.")
    if existing["event_type"] != "URGE":
        raise ValidationError("Only URGE events have Resisted / Gave In outcomes.")
    clean_outcome = validate_choice(outcome, ("Resisted", "Gave In"), "Outcome")
    now_utc = utc_now_iso()
    with transaction() as conn:
        challenge_repository.update_event_outcome(event_id, clean_outcome, now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "challenges",
            "urge_resolved",
            "urge_event",
            event_id,
            "Marked urge #%d as %s" % (event_id, clean_outcome),
            now_utc,
            conn=conn,
        )


def delete_event(event_id, permanent=False):
    existing = challenge_repository.get_event(event_id, include_deleted=permanent)
    if not existing:
        raise ValidationError("Event not found.")
    now_utc = utc_now_iso()
    with transaction() as conn:
        if permanent:
            challenge_repository.delete_event(event_id, conn=conn)
            action = "event_purged"
        else:
            challenge_repository.soft_delete_event(event_id, now_utc, conn=conn)
            action = "event_deleted"
        auth_repository.insert_activity_log(
            "challenges",
            action,
            "urge_event",
            event_id,
            "Deleted %s event #%d from '%s'" % (existing["event_type"], event_id, existing["challenge_name"]),
            now_utc,
            conn=conn,
        )


def restore_event(event_id):
    existing = challenge_repository.get_event(event_id, include_deleted=True)
    if not existing or not existing.get("is_deleted"):
        raise ValidationError("Deleted event not found in Trash.")
    parent_ch = challenge_repository.get_challenge(existing["challenge_id"])
    if not parent_ch:
        raise ValidationError("Restore the parent challenge '%s' first." % existing["challenge_name"])

    now_utc = utc_now_iso()
    with transaction() as conn:
        challenge_repository.restore_event(event_id, now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "challenges",
            "event_restored",
            "urge_event",
            event_id,
            "Restored %s event #%d on '%s'" % (existing["event_type"], event_id, existing["challenge_name"]),
            now_utc,
            conn=conn,
        )


# ============================================================================
# DAILY RECORDS, MULTI-REFLECTIONS & COMMENTS
# ============================================================================

def get_daily_tracking_data(challenge_id, selected_date=None):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        return None
    tz_name = _get_timezone()
    today_str = local_today_str(tz_name)
    sel_date = validate_date_str(selected_date, "Selected date") if selected_date else today_str
    if not sel_date:
        sel_date = today_str

    all_events = challenge_repository.list_events_for_challenge(challenge_id, limit=5000)
    daily_records = challenge_repository.list_daily_records(challenge_id)
    reflections = challenge_repository.list_daily_reflections(challenge_id)
    comments = challenge_repository.list_comments_for_challenge(challenge_id)

    events_by_date = {}
    for ev in all_events:
        d_str = format_local_date(ev["event_timestamp"], tz_name)
        events_by_date.setdefault(d_str, []).append(ev)

    records_by_date = {r["record_date"]: r for r in daily_records}
    reflections_by_date = {}
    for r in reflections:
        reflections_by_date.setdefault(r["record_date"], []).append(r)

    comments_by_date = {}
    for c in comments:
        comments_by_date.setdefault(c["record_date"], []).append(c)

    all_dates = sorted(
        set(events_by_date.keys())
        | set(records_by_date.keys())
        | set(reflections_by_date.keys())
        | set(comments_by_date.keys())
        | {today_str, sel_date},
        reverse=True,
    )

    daily_rows = []
    selected_day = None
    for d in all_dates:
        d_events = events_by_date.get(d, [])
        d_timeline = sorted(d_events, key=lambda e: (e["event_timestamp"], e["id"]))
        metrics = compute_event_metrics(d_events)
        rec = records_by_date.get(d, {})
        d_reflections = reflections_by_date.get(d, [])
        d_comments = comments_by_date.get(d, [])
        eff_reflection = rec.get("reflection", "") or (d_reflections[0]["reflection_text"] if d_reflections else "")
        eff_mood = rec.get("mood", "") or (d_reflections[0]["mood"] if d_reflections else "")
        eff_context = rec.get("context", "") or (d_reflections[0]["context"] if d_reflections else "")
        row = {
            "date": d,
            "is_today": d == today_str,
            "metrics": metrics,
            "events": d_events,
            "timeline_events": d_timeline,
            "reflection": eff_reflection,
            "mood": eff_mood,
            "context": eff_context,
            "record_updated_at": rec.get("updated_at", ""),
            "reflections": d_reflections,
            "comments": d_comments,
            "has_activity": bool(d_events or d_reflections or d_comments or rec.get("reflection") or rec.get("mood")),
        }
        daily_rows.append(row)
        if d == sel_date:
            selected_day = row

    active_dates = [r for r in daily_rows if r["has_activity"] or r["date"] == today_str]

    return {
        "challenge": ch,
        "today": today_str,
        "selected_date": sel_date,
        "prev_date": shift_date_str(sel_date, -1),
        "next_date": shift_date_str(sel_date, 1),
        "selected_day": selected_day,
        "active_dates": active_dates,
        "daily_rows": daily_rows,
        "predefined_triggers": PREDEFINED_TRIGGERS,
    }


def save_daily_record(challenge_id, record_date, reflection, mood, context):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    d_str = validate_date_str(record_date, "Record date")
    if not d_str:
        raise ValidationError("Record date is required.")

    clean_reflection = clean_optional_text(reflection, max_len=4000)
    clean_mood = clean_optional_text(mood, max_len=80)
    clean_context = clean_optional_text(context, max_len=300)
    now_utc = utc_now_iso()

    with transaction() as conn:
        challenge_repository.upsert_daily_record(
            challenge_id, d_str, clean_reflection, clean_mood, clean_context, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges",
            "daily_record_saved",
            "challenge_daily_record",
            challenge_id,
            "Saved daily reflection summary for %s (%s)" % (ch["name"], d_str),
            now_utc,
            conn=conn,
        )


def add_daily_reflection(challenge_id, record_date, title, reflection_text, mood="", context=""):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    d_str = validate_date_str(record_date, "Record date") or local_today_str(_get_timezone())
    clean_title = clean_optional_text(title, max_len=140) or "Reflection"
    text = require_non_empty(reflection_text, "Reflection note", max_len=4000)
    clean_mood = clean_optional_text(mood, max_len=80)
    clean_context = clean_optional_text(context, max_len=300)
    now_utc = utc_now_iso()

    with transaction() as conn:
        rid = challenge_repository.insert_daily_reflection(
            challenge_id, ch["current_cycle_id"], d_str, clean_title, text, clean_mood, clean_context, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges",
            "daily_reflection_added",
            "challenge_daily_reflection",
            rid,
            "Added reflection '%s' for %s (%s)" % (clean_title, ch["name"], d_str),
            now_utc,
            conn=conn,
        )
    return rid


def edit_daily_reflection(reflection_id, title, reflection_text, mood="", context=""):
    existing = challenge_repository.get_daily_reflection(reflection_id)
    if not existing:
        raise ValidationError("Reflection not found.")
    clean_title = clean_optional_text(title, max_len=140) or "Reflection"
    text = require_non_empty(reflection_text, "Reflection note", max_len=4000)
    clean_mood = clean_optional_text(mood, max_len=80)
    clean_context = clean_optional_text(context, max_len=300)
    now_utc = utc_now_iso()

    with transaction() as conn:
        challenge_repository.update_daily_reflection(
            reflection_id, clean_title, text, clean_mood, clean_context, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges",
            "daily_reflection_edited",
            "challenge_daily_reflection",
            reflection_id,
            "Edited daily reflection #%d" % reflection_id,
            now_utc,
            conn=conn,
        )


def delete_daily_reflection(reflection_id):
    existing = challenge_repository.get_daily_reflection(reflection_id)
    if not existing:
        raise ValidationError("Reflection not found.")
    now_utc = utc_now_iso()
    with transaction() as conn:
        challenge_repository.delete_daily_reflection(reflection_id, conn=conn)
        auth_repository.insert_activity_log(
            "challenges",
            "daily_reflection_deleted",
            "challenge_daily_reflection",
            reflection_id,
            "Deleted daily reflection #%d" % reflection_id,
            now_utc,
            conn=conn,
        )


def add_daily_comment(challenge_id, record_date, comment_text):
    ch = challenge_repository.get_challenge(challenge_id)
    if not ch:
        raise ValidationError("Challenge not found.")
    d_str = validate_date_str(record_date, "Record date") or local_today_str(_get_timezone())
    text = require_non_empty(comment_text, "Comment", max_len=2000)
    now_utc = utc_now_iso()

    with transaction() as conn:
        cid = challenge_repository.insert_comment(
            challenge_id, ch["current_cycle_id"], d_str, text, now_utc, conn=conn
        )
        auth_repository.insert_activity_log(
            "challenges", "daily_comment_added", "challenge_comment", cid, "Added daily comment (%s)" % d_str, now_utc, conn=conn
        )
    return cid


def edit_daily_comment(comment_id, comment_text):
    existing = challenge_repository.get_comment(comment_id)
    if not existing:
        raise ValidationError("Comment not found.")
    text = require_non_empty(comment_text, "Comment", max_len=2000)
    now_utc = utc_now_iso()

    with transaction() as conn:
        challenge_repository.update_comment(comment_id, text, now_utc, conn=conn)
        auth_repository.insert_activity_log(
            "challenges", "daily_comment_edited", "challenge_comment", comment_id, "Edited daily comment #%d" % comment_id, now_utc, conn=conn
        )


def delete_daily_comment(comment_id):
    existing = challenge_repository.get_comment(comment_id)
    if not existing:
        raise ValidationError("Comment not found.")
    now_utc = utc_now_iso()
    with transaction() as conn:
        challenge_repository.delete_comment(comment_id, conn=conn)
        auth_repository.insert_activity_log(
            "challenges", "daily_comment_deleted", "challenge_comment", comment_id, "Deleted daily comment #%d" % comment_id, now_utc, conn=conn
        )

