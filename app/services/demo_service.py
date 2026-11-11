import uuid
from datetime import timedelta
from app.database.connection import get_db
from app.database.transaction import transaction
from app.repositories import auth_repository, challenge_repository, task_repository
from app.utils.time_utils import local_today_str, utc_now, utc_now_iso


def has_demo_data(conn=None):
    db = conn or get_db()
    t_row = db.execute("SELECT COUNT(*) AS cnt FROM centered_tasks WHERE is_demo = 1").fetchone()
    c_row = db.execute("SELECT COUNT(*) AS cnt FROM challenges WHERE is_demo = 1").fetchone()
    return (int(t_row["cnt"]) + int(c_row["cnt"])) > 0


def clear_demo_data():
    now_utc = utc_now_iso()
    with transaction() as conn:
        demo_cts = conn.execute("SELECT id FROM centered_tasks WHERE is_demo = 1").fetchall()
        demo_ct_ids = [r["id"] for r in demo_cts]
        if demo_ct_ids:
            placeholders = ",".join("?" for _ in demo_ct_ids)
            # Clear linked items pointing into demo centered tasks first
            conn.execute(
                "DELETE FROM task_items WHERE linked_centered_task_id IN (%s)" % placeholders,
                tuple(demo_ct_ids),
            )
            conn.execute(
                "DELETE FROM centered_tasks WHERE id IN (%s)" % placeholders,
                tuple(demo_ct_ids),
            )

        demo_chs = conn.execute("SELECT id FROM challenges WHERE is_demo = 1").fetchall()
        for row in demo_chs:
            challenge_repository.delete_challenge_full(row["id"], conn=conn)

        auth_repository.insert_activity_log(
            "settings", "demo_data_cleared", "system", None, "Removed all demo records", now_utc, conn=conn
        )


def seed_demo_data():
    if has_demo_data():
        return False

    tz_name = auth_repository.get_setting("timezone", "UTC") or "UTC"
    today = local_today_str(tz_name)
    now_dt = utc_now()
    now_utc = utc_now_iso()

    def ts_days_ago(days, hour_offset=0):
        return (now_dt - timedelta(days=days, hours=hour_offset)).strftime("%Y-%m-%dT%H:%M:%SZ")

    with transaction() as conn:
        # 1. Demo Centered Tasks (total root weight = 100% of 40h budget)
        ml_proj_id = task_repository.insert_centered_task(
            {
                "name": "ML Projects",
                "description": "End-to-end applied machine learning portfolio build.",
                "weight": 0.0,
                "target_allocation": 1.6,
                "target_unit": "hours",
                "allocation_mode": "budgeted",
                "allocation_finalized": 1,
                "start_date": today,
                "target_end_date": "",
                "priority": "High",
                "status": "In Progress",
                "background_image": "images/presets/slate-grid.svg",
                "background_mode": "preset",
                "font_family": "Inter",
                "primary_color": "#4F46E5",
                "accent_color": "#0EA5E9",
                "text_color": "",
                "metadata_json": '{"track": "Applied AI", "source": "demo"}',
                "is_demo": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        dp_id = task_repository.insert_task_item(
            {
                "parent_centered_task_id": ml_proj_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Data Preprocessing",
                "description": "Clean features, impute missing values, and build pipelines.",
                "weight_pct": 40.0,
                "target_quantity": 0.64,
                "target_unit": "hours",
                "allocated_time_budget": 0.64,
                "start_date": today,
                "due_date": "",
                "priority": "High",
                "status": "Completed",
                "notes": "Completed feature pipeline",
                "sort_order": 1,
                "completed_at": ts_days_ago(1),
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        md_id = task_repository.insert_task_item(
            {
                "parent_centered_task_id": ml_proj_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Model Development",
                "description": "Train baseline and tuned gradient boosted models.",
                "weight_pct": 40.0,
                "target_quantity": 0.64,
                "target_unit": "hours",
                "allocated_time_budget": 0.64,
                "start_date": today,
                "due_date": "",
                "priority": "Medium",
                "status": "In Progress",
                "notes": "",
                "sort_order": 2,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        task_repository.insert_task_item(
            {
                "parent_centered_task_id": ml_proj_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Model Evaluation",
                "description": "Cross-validation metrics and error analysis.",
                "weight_pct": 20.0,
                "target_quantity": 0.32,
                "target_unit": "hours",
                "allocated_time_budget": 0.32,
                "start_date": today,
                "due_date": "",
                "priority": "Medium",
                "status": "Not Started",
                "notes": "",
                "sort_order": 3,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        ml_id = task_repository.insert_centered_task(
            {
                "name": "Machine Learning",
                "description": "Core ML mastery track combining math, coding, algorithms, and projects.",
                "weight": 40.0,
                "target_allocation": 16.0,
                "target_unit": "hours",
                "allocation_mode": "budgeted",
                "allocation_finalized": 1,
                "start_date": today,
                "target_end_date": "",
                "priority": "Critical",
                "status": "In Progress",
                "background_image": "images/presets/cobalt-waves.svg",
                "background_mode": "preset",
                "font_family": "Plus Jakarta Sans",
                "primary_color": "#4F46E5",
                "accent_color": "#0EA5E9",
                "text_color": "",
                "metadata_json": '{"quarter": "Q4", "source": "demo"}',
                "is_demo": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        math_id = task_repository.insert_task_item(
            {
                "parent_centered_task_id": ml_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Mathematics",
                "description": "Linear algebra, gradients, and probability exercises.",
                "weight_pct": 40.0,
                "target_quantity": 6.4,
                "target_unit": "hours",
                "allocated_time_budget": 6.4,
                "start_date": today,
                "due_date": "",
                "priority": "High",
                "status": "In Progress",
                "notes": "",
                "sort_order": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        py_id = task_repository.insert_task_item(
            {
                "parent_centered_task_id": ml_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Python Practice",
                "description": "NumPy vectorization & clean data utilities.",
                "weight_pct": 30.0,
                "target_quantity": 4.8,
                "target_unit": "hours",
                "allocated_time_budget": 4.8,
                "start_date": today,
                "due_date": "",
                "priority": "High",
                "status": "In Progress",
                "notes": "",
                "sort_order": 2,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        task_repository.insert_task_item(
            {
                "parent_centered_task_id": ml_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "ML Algorithms",
                "description": "Implement decision trees and gradient descent from scratch.",
                "weight_pct": 20.0,
                "target_quantity": 3.2,
                "target_unit": "hours",
                "allocated_time_budget": 3.2,
                "start_date": today,
                "due_date": "",
                "priority": "Medium",
                "status": "Active",
                "notes": "",
                "sort_order": 3,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        task_repository.insert_task_item(
            {
                "parent_centered_task_id": ml_id,
                "item_type": "linked_centered",
                "linked_centered_task_id": ml_proj_id,
                "name": "ML Projects",
                "description": "Linked nested centered task.",
                "weight_pct": 10.0,
                "target_quantity": 1.6,
                "target_unit": "hours",
                "allocated_time_budget": 1.6,
                "start_date": today,
                "due_date": "",
                "priority": "High",
                "status": "In Progress",
                "notes": "",
                "sort_order": 4,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        college_id = task_repository.insert_centered_task(
            {
                "name": "College Studies",
                "description": "Core coursework, lecture reviews, and problem sets.",
                "weight": 35.0,
                "target_allocation": 14.0,
                "target_unit": "hours",
                "allocation_mode": "budgeted",
                "allocation_finalized": 1,
                "start_date": today,
                "target_end_date": "",
                "priority": "High",
                "status": "In Progress",
                "background_image": "images/presets/nordic-dots.svg",
                "background_mode": "preset",
                "font_family": "Inter",
                "primary_color": "#0284C7",
                "accent_color": "#6366F1",
                "text_color": "",
                "metadata_json": '{"source": "demo"}',
                "is_demo": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        col_read_id = task_repository.insert_task_item(
            {
                "parent_centered_task_id": college_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Textbook Reading",
                "description": "Read assigned textbook chapters.",
                "weight_pct": 60.0,
                "target_quantity": 120.0,
                "target_unit": "pages",
                "allocated_time_budget": 8.4,
                "start_date": today,
                "due_date": "",
                "priority": "Medium",
                "status": "In Progress",
                "notes": "",
                "sort_order": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        task_repository.insert_task_item(
            {
                "parent_centered_task_id": college_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Problem Sets",
                "description": "Weekly graded problem sheets.",
                "weight_pct": 40.0,
                "target_quantity": 5.6,
                "target_unit": "hours",
                "allocated_time_budget": 5.6,
                "start_date": today,
                "due_date": "",
                "priority": "High",
                "status": "Active",
                "notes": "",
                "sort_order": 2,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        fitness_id = task_repository.insert_centered_task(
            {
                "name": "Fitness",
                "description": "Strength training & mobility sessions.",
                "weight": 15.0,
                "target_allocation": 6.0,
                "target_unit": "hours",
                "allocation_mode": "budgeted",
                "allocation_finalized": 1,
                "start_date": today,
                "target_end_date": "",
                "priority": "Medium",
                "status": "Active",
                "background_image": "",
                "background_mode": "none",
                "font_family": "Inter",
                "primary_color": "#059669",
                "accent_color": "#14B8A6",
                "text_color": "",
                "metadata_json": '{"source": "demo"}',
                "is_demo": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        fit_sess_id = task_repository.insert_task_item(
            {
                "parent_centered_task_id": fitness_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Strength Workouts",
                "description": "4 structured gym sessions per week.",
                "weight_pct": 100.0,
                "target_quantity": 4.0,
                "target_unit": "sessions",
                "allocated_time_budget": 6.0,
                "start_date": today,
                "due_date": "",
                "priority": "Medium",
                "status": "In Progress",
                "notes": "",
                "sort_order": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        comm_id = task_repository.insert_centered_task(
            {
                "name": "Communication Skills",
                "description": "Structured speaking and technical writing drills.",
                "weight": 10.0,
                "target_allocation": 4.0,
                "target_unit": "hours",
                "allocation_mode": "budgeted",
                "allocation_finalized": 1,
                "start_date": today,
                "target_end_date": "",
                "priority": "Medium",
                "status": "Active",
                "background_image": "",
                "background_mode": "none",
                "font_family": "Inter",
                "primary_color": "#D97706",
                "accent_color": "#F59E0B",
                "text_color": "",
                "metadata_json": '{"source": "demo"}',
                "is_demo": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        task_repository.insert_task_item(
            {
                "parent_centered_task_id": comm_id,
                "item_type": "standard",
                "linked_centered_task_id": None,
                "name": "Daily Speaking Practice",
                "description": "Short structured explanations & articulation.",
                "weight_pct": 100.0,
                "target_quantity": 4.0,
                "target_unit": "hours",
                "allocated_time_budget": 4.0,
                "start_date": today,
                "due_date": "",
                "priority": "Medium",
                "status": "Active",
                "notes": "",
                "sort_order": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )

        # Sample Progress Entries
        sample_entries = [
            (dp_id, 0.7, 42.0, ts_days_ago(2), "Cleaned dataset & handled outliers"),
            (md_id, 0.35, 21.0, ts_days_ago(1), "Tuned XGBoost baseline"),
            (math_id, 3.2, 192.0, ts_days_ago(3), "Eigenvalues and matrix calculus review"),
            (py_id, 2.4, 144.0, ts_days_ago(1), "Vectorized numpy exercises"),
            (col_read_id, 55.0, 110.0, ts_days_ago(2), "Chapters 1-3 summarized"),
            (fit_sess_id, 2.0, 120.0, ts_days_ago(1), "Upper and lower body sessions"),
        ]
        for iid, qty, mins, ts, cmt in sample_entries:
            task_repository.insert_progress_entry(
                {
                    "task_item_id": iid,
                    "quantity_completed": qty,
                    "time_spent_minutes": mins,
                    "entry_timestamp": ts,
                    "comments": cmt,
                    "update_source": "manual",
                    "created_at": ts,
                    "updated_at": ts,
                },
                conn=conn,
            )

        # Snapshot record for demo global budget
        snap_grp = uuid.uuid4().hex[:12]
        for ct_id, nm, w, tgt in [
            (ml_id, "Machine Learning", 40.0, 16.0),
            (college_id, "College Studies", 35.0, 14.0),
            (fitness_id, "Fitness", 15.0, 6.0),
            (comm_id, "Communication Skills", 10.0, 4.0),
        ]:
            task_repository.insert_allocation_snapshot(
                {
                    "snapshot_group_id": snap_grp,
                    "scope": "global_budget",
                    "centered_task_id": ct_id,
                    "centered_task_name_snapshot": nm,
                    "task_item_id": None,
                    "task_item_name_snapshot": "",
                    "budget_mode": "fixed",
                    "total_budget": 40.0,
                    "budget_unit": "hours",
                    "weight_pct": w,
                    "allocated_target": tgt,
                    "target_unit": "hours",
                    "reason": "Demo workspace allocation",
                    "is_active": 1,
                    "created_at": now_utc,
                },
                conn=conn,
            )

        # 2. Demo Challenges
        ch1_id = challenge_repository.insert_challenge(
            {
                "name": "Deep Work Phone Discipline",
                "description": "Eliminate reflexive social media checks during study blocks.",
                "behaviour_to_avoid": "Unnecessary Instagram & short-form feed scrolling",
                "objective": "Keep focus blocks phone-free and build urge awareness.",
                "start_date": today,
                "end_date": "",
                "status": "Active",
                "current_cycle_id": None,
                "is_demo": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        ch1_cyc1 = challenge_repository.insert_cycle(
            {
                "challenge_id": ch1_id,
                "cycle_number": 1,
                "status": "Active",
                "started_at": ts_days_ago(5),
                "ended_at": None,
                "reset_reason": "",
                "created_at": ts_days_ago(5),
            },
            conn=conn,
        )
        challenge_repository.update_challenge_status_and_cycle(ch1_id, "Active", ch1_cyc1, None, now_utc, conn=conn)
        challenge_repository.upsert_challenge_settings(
            ch1_id,
            {
                "background_image": "images/presets/emerald-horizon.svg",
                "background_mode": "preset",
                "font_family": "Plus Jakarta Sans",
                "font_size": "16px",
                "text_color": "",
                "accent_color": "#0D9488",
                "card_style": "elevated",
                "layout_style": "comfortable",
                "metadata_json": '{"source": "demo"}',
                "updated_at": now_utc,
            },
            conn=conn,
        )

        ch2_id = challenge_repository.insert_challenge(
            {
                "name": "Zero Late-Night Entertainment",
                "description": "Protect sleep hygiene after 10:30 PM.",
                "behaviour_to_avoid": "Binge-watching videos past bedtime",
                "objective": "Wind down offline after 10:30 PM.",
                "start_date": today,
                "end_date": "",
                "status": "Active",
                "current_cycle_id": None,
                "is_demo": 1,
                "completed_at": None,
                "created_at": now_utc,
                "updated_at": now_utc,
            },
            conn=conn,
        )
        ch2_cyc1 = challenge_repository.insert_cycle(
            {
                "challenge_id": ch2_id,
                "cycle_number": 1,
                "status": "Active",
                "started_at": ts_days_ago(4),
                "ended_at": None,
                "reset_reason": "",
                "created_at": ts_days_ago(4),
            },
            conn=conn,
        )
        challenge_repository.update_challenge_status_and_cycle(ch2_id, "Active", ch2_cyc1, None, now_utc, conn=conn)
        challenge_repository.upsert_challenge_settings(
            ch2_id,
            {
                "background_image": "images/presets/midnight-contours.svg",
                "background_mode": "preset",
                "font_family": "Inter",
                "font_size": "16px",
                "text_color": "",
                "accent_color": "#10B981",
                "card_style": "bordered",
                "layout_style": "focused",
                "metadata_json": '{"source": "demo"}',
                "updated_at": now_utc,
            },
            conn=conn,
        )

        demo_events = [
            (ch1_id, ch1_cyc1, "THOUGHT", "Observed", ts_days_ago(4, 2), "Boredom", "Between study blocks", 15, "Noticed urge to check feed, breathed instead"),
            (ch1_id, ch1_cyc1, "URGE", "Resisted", ts_days_ago(3, 4), "Hard math problem", "Desk study", 90, "Left phone in another room"),
            (ch1_id, ch1_cyc1, "URGE", "Resisted", ts_days_ago(2, 1), "Notification buzz", "Evening review", 45, "Switched to Do Not Disturb"),
            (ch1_id, ch1_cyc1, "URGE", "Gave In", ts_days_ago(2, 6), "Fatigue", "After lunch", 300, "Scrolled 5 mins"),
            (ch1_id, ch1_cyc1, "ACTION", "Occurred", ts_days_ago(2, 6), "Fatigue", "After lunch", 300, "Opened Instagram briefly"),
            (ch1_id, ch1_cyc1, "URGE", "Resisted", ts_days_ago(1, 3), "Task switching", "Afternoon focus", 60, "Drank water and resumed"),
            (ch1_id, ch1_cyc1, "URGE", "Pending", ts_days_ago(0, 1), "Waiting for build", "Desk", 20, "Feeling tempted right now"),
            (ch2_id, ch2_cyc1, "URGE", "Resisted", ts_days_ago(3, 0), "Stress", "Bedroom", 120, "Read physical book instead"),
            (ch2_id, ch2_cyc1, "THOUGHT", "Observed", ts_days_ago(1, 0), "Tiredness", "Late evening", 20, "Thought about opening YouTube"),
        ]
        for cid, cyc_id, etype, outc, ts, trig, ctx, dur, cmt in demo_events:
            from app.utils.validation import normalize_trigger
            t_cat, t_txt = normalize_trigger("", trig)
            challenge_repository.insert_event(
                {
                    "challenge_id": cid,
                    "cycle_id": cyc_id,
                    "event_type": etype,
                    "outcome": outc,
                    "related_urge_id": None,
                    "event_timestamp": ts,
                    "trigger_category": t_cat,
                    "trigger_text": t_txt,
                    "context": ctx,
                    "duration_seconds": dur,
                    "comments": cmt,
                    "tags": "demo",
                    "created_at": ts,
                    "updated_at": ts,
                },
                conn=conn,
            )

        auth_repository.insert_activity_log(
            "settings", "demo_data_seeded", "system", None, "Loaded optional demo workspace data", now_utc, conn=conn
        )
    return True

