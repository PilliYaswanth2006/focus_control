import io
import os
import tempfile
import unittest
from PIL import Image
from werkzeug.datastructures import FileStorage
from app import create_app
from app.services import auth_service, challenge_service, demo_service, statistics_service
from app.utils.validation import ValidationError
from config import Config


class UrgeAndResistanceTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.upload_dir = tempfile.mkdtemp()

        class TempConfig(Config):
            TESTING = True
            DATABASE_PATH = self.db_path
            UPLOAD_FOLDER = self.upload_dir
            SECRET_KEY = "test-secret"

        self.app = create_app(TempConfig)
        with self.app.app_context():
            auth_service.setup_credentials("pin", "1234", "1234", "Tester", "UTC")

    def tearDown(self):
        import shutil
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass
        if os.path.exists(self.upload_dir):
            shutil.rmtree(self.upload_dir, ignore_errors=True)

    def test_challenge_lifecycle_reset_preserves_history_and_calculations(self):
        with self.app.app_context():
            cid = challenge_service.create_challenge(
                {
                    "name": "No Social Scrolling",
                    "behaviour_to_avoid": "Instagram reels",
                    "objective": "Protect study focus",
                    "start_immediately": "1",
                    "accent_color": "#0D9488",
                    "card_style": "glass",
                    "layout_style": "focused",
                }
            )

            # Record distinct event types in Cycle 1
            challenge_service.record_event(cid, {"event_type": "THOUGHT", "trigger_text": "Boredom"})
            challenge_service.record_event(cid, {"event_type": "URGE", "outcome": "Resisted", "trigger_text": "Boredom"})
            challenge_service.record_event(cid, {"event_type": "URGE", "outcome": "Resisted"})
            u_gave_in = challenge_service.record_event(cid, {"event_type": "URGE", "outcome": "Gave In"})
            u_pending = challenge_service.record_event(cid, {"event_type": "URGE", "outcome": "Pending"})
            act_id = challenge_service.record_event(
                cid, {"event_type": "ACTION", "related_urge_id": str(u_gave_in), "comments": "Opened app"}
            )

            det = challenge_service.get_challenge_details(cid)
            m = det["metrics"]
            # Resisted=2, Gave In=1, Pending=1 (excluded!), Thoughts=1, Actions=1
            # Resistance rate = 2 / (2 + 1) * 100 = 66.7%
            self.assertEqual(m["total_thoughts"], 1)
            self.assertEqual(m["total_urges"], 4)
            self.assertEqual(m["resisted_urges"], 2)
            self.assertEqual(m["gave_in_urges"], 1)
            self.assertEqual(m["pending_urges"], 1)
            self.assertEqual(m["total_actions"], 1)
            self.assertAlmostEqual(m["resistance_rate"], 66.7, places=1)

            # Edit event without changing timestamp -> historical timestamp preserved!
            orig_ts = [e["event_timestamp"] for e in det["events"] if e["id"] == act_id][0]
            challenge_service.update_event(act_id, {"comments": "Edited comment", "trigger_text": "Fatigue"})
            det_after_edit = challenge_service.get_challenge_details(cid)
            edited_ev = [e for e in det_after_edit["events"] if e["id"] == act_id][0]
            self.assertEqual(edited_ev["event_timestamp"], orig_ts)
            self.assertEqual(edited_ev["comments"], "Edited comment")

            # Pause -> Resume -> Reset (preserves Cycle 1!)
            challenge_service.pause_challenge(cid)
            self.assertEqual(challenge_service.get_challenge_details(cid)["status"], "Paused")
            challenge_service.resume_challenge(cid)
            self.assertEqual(challenge_service.get_challenge_details(cid)["status"], "Active")

            challenge_service.reset_challenge(cid, reason="Starting fresh week")
            det_reset = challenge_service.get_challenge_details(cid)
            self.assertEqual(det_reset["current_cycle_number"], 2)
            # Current cycle has 0 events, all-time retains all 6 events!
            self.assertEqual(len(det_reset["events"]), 0)
            self.assertEqual(det_reset["all_time_metrics"]["total_urges"], 4)
            self.assertEqual(len(det_reset["cycles"]), 2)
            self.assertIsNotNone(u_pending)

    def test_daily_tracking_comments_and_image_upload_validation(self):
        with self.app.app_context():
            # Valid PNG image upload
            buf = io.BytesIO()
            Image.new("RGB", (32, 32), color=(13, 148, 136)).save(buf, format="PNG")
            buf.seek(0)
            valid_img = FileStorage(stream=buf, filename="bg.png", content_type="image/png")

            cid = challenge_service.create_challenge(
                {"name": "Mindful Focus", "behaviour_to_avoid": "Procrastination"},
                bg_file=valid_img,
            )
            ch = challenge_service.get_challenge_details(cid)
            self.assertTrue(ch["background_image"].startswith("uploads/backgrounds/"))

            # Spoofed non-image upload must fail validation
            fake_img = FileStorage(stream=io.BytesIO(b"not an image"), filename="evil.png", content_type="image/png")
            with self.assertRaises(ValidationError):
                challenge_service.update_challenge(cid, {"name": "Mindful Focus", "behaviour_to_avoid": "Procrastination"}, bg_file=fake_img)

            # Daily records & comments keep distinct created_at / updated_at
            challenge_service.record_event(cid, {"event_type": "URGE", "outcome": "Resisted"})
            daily = challenge_service.get_daily_tracking_data(cid)
            today_str = daily["today"]
            today_row = [r for r in daily["daily_rows"] if r["date"] == today_str][0]
            self.assertEqual(today_row["metrics"]["resisted_urges"], 1)

            cmt_id = challenge_service.add_daily_comment(cid, today_str, "Initial check-in")
            challenge_service.save_daily_record(cid, today_str, "Stayed steady", "Calm", "Home desk")
            challenge_service.edit_daily_comment(cmt_id, "Updated check-in")

            daily2 = challenge_service.get_daily_tracking_data(cid)
            today_row2 = [r for r in daily2["daily_rows"] if r["date"] == today_str][0]
            self.assertEqual(today_row2["comments"][0]["comment_text"], "Updated check-in")
            self.assertEqual(today_row2["reflection"], "Stayed steady")

            # Demo data separation test
            demo_service.seed_demo_data()
            self.assertTrue(demo_service.has_demo_data())
            stats_all = statistics_service.get_global_statistics(include_demo=True)
            stats_personal = statistics_service.get_global_statistics(include_demo=False)
            self.assertGreater(stats_all["challenges"]["summary"]["total_urges"], stats_personal["challenges"]["summary"]["total_urges"])

            demo_service.clear_demo_data()
            self.assertFalse(demo_service.has_demo_data())
            # Personal challenge still intact
            self.assertIsNotNone(challenge_service.get_challenge_details(cid))

    def test_triggers_duration_targets_pending_linking_daily_nav_reflections_and_trash(self):
        with self.app.app_context():
            from app.repositories import challenge_repository

            cid = challenge_service.create_challenge(
                {
                    "name": "30-Day Clean Focus",
                    "behaviour_to_avoid": "Doomscrolling",
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-30",
                    "target_value": "30",
                    "target_unit": "clean days",
                    "start_immediately": "1",
                }
            )
            det = challenge_service.get_challenge_details(cid)
            self.assertEqual(det["planned_duration_days"], 30)
            self.assertAlmostEqual(det["target_value"], 30.0, places=2)
            self.assertEqual(det["target_unit"], "clean days")

            # Predefined trigger normalization (case-insensitive) & custom detail -> "Other"
            e_resisted = challenge_service.record_event(
                cid,
                {
                    "event_type": "URGE",
                    "outcome": "Resisted",
                    "trigger_category": "stress",
                    "trigger_text": "Exam deadline",
                    "event_timestamp": "2026-10-05T09:30",
                },
            )
            e_pending = challenge_service.record_event(
                cid,
                {
                    "event_type": "URGE",
                    "outcome": "Pending",
                    "trigger_category": "Boredom",
                    "event_timestamp": "2026-10-05T14:00",
                },
            )
            # Custom text with blank category auto-maps to "Other"
            challenge_service.record_event(
                cid,
                {
                    "event_type": "THOUGHT",
                    "trigger_text": "Waiting for bus",
                    "event_timestamp": "2026-10-05T18:00",
                },
            )
            # Invalid predefined category rejected
            with self.assertRaises(ValidationError):
                challenge_service.record_event(
                    cid, {"event_type": "THOUGHT", "trigger_category": "InvalidCategoryXYZ"}
                )

            # Linking ACTION to a Pending urge auto-resolves that Pending urge to "Gave In"
            e_action = challenge_service.record_event(
                cid,
                {
                    "event_type": "ACTION",
                    "related_urge_id": str(e_pending),
                    "trigger_category": "Boredom",
                    "event_timestamp": "2026-10-05T14:05",
                },
            )
            resolved_urge = challenge_repository.get_event(e_pending)
            self.assertEqual(resolved_urge["outcome"], "Gave In")

            det2 = challenge_service.get_challenge_details(cid)
            trig_rows = {r["trigger"]: r for r in det2["trigger_analytics"]["categories"]}
            self.assertIn("Stress", trig_rows)
            self.assertAlmostEqual(trig_rows["Stress"]["resistance_rate"], 100.0, places=1)
            self.assertIn("Boredom", trig_rows)
            self.assertAlmostEqual(trig_rows["Boredom"]["resistance_rate"], 0.0, places=1)
            self.assertIn("Other", trig_rows)

            # Daily tracking date navigation + chronological timeline + multiple reflections CRUD
            rf1 = challenge_service.add_daily_reflection(
                cid, "2026-10-05", "Morning check", "Felt strong early", mood="Calm", context="Desk"
            )
            rf2 = challenge_service.add_daily_reflection(
                cid, "2026-10-05", "Evening review", "Afternoon boredom slip", mood="Tired", context="Commute"
            )
            challenge_service.edit_daily_reflection(rf2, "Evening Review v2", "Afternoon boredom slip updated", mood="Focused", context="Home")

            daily = challenge_service.get_daily_tracking_data(cid, selected_date="2026-10-05")
            self.assertEqual(daily["selected_date"], "2026-10-05")
            self.assertEqual(daily["prev_date"], "2026-10-04")
            self.assertEqual(daily["next_date"], "2026-10-06")
            self.assertEqual(len(daily["selected_day"]["timeline_events"]), 4)
            # Chronological order: 09:30 -> 14:00 -> 14:05 -> 18:00
            self.assertEqual(daily["selected_day"]["timeline_events"][0]["id"], e_resisted)
            self.assertEqual(daily["selected_day"]["timeline_events"][-2]["id"], e_action)
            self.assertEqual(len(daily["selected_day"]["reflections"]), 2)
            self.assertTrue(any(r["title"] == "Evening Review v2" for r in daily["selected_day"]["reflections"]))

            challenge_service.delete_daily_reflection(rf1)
            daily_after_del = challenge_service.get_daily_tracking_data(cid, selected_date="2026-10-05")
            self.assertEqual(len(daily_after_del["selected_day"]["reflections"]), 1)

            # Soft-delete event -> restore -> soft-delete challenge -> restore -> permanent purge
            challenge_service.delete_event(e_action, permanent=False)
            self.assertIsNone(challenge_repository.get_event(e_action))
            self.assertIn(e_action, [e["id"] for e in challenge_repository.list_deleted_events()])
            challenge_service.restore_event(e_action)
            self.assertIsNotNone(challenge_repository.get_event(e_action))

            challenge_service.delete_challenge(cid, confirm_force=True, permanent=False)
            self.assertIsNone(challenge_service.get_challenge_details(cid))
            self.assertIn(cid, [c["id"] for c in challenge_repository.list_deleted_challenges()])
            challenge_service.restore_challenge(cid)
            self.assertIsNotNone(challenge_service.get_challenge_details(cid))

            challenge_service.delete_challenge(cid, confirm_force=True, permanent=False)
            challenge_service.delete_challenge(cid, confirm_force=True, permanent=True)
            self.assertIsNone(challenge_repository.get_challenge(cid, include_deleted=True))


if __name__ == "__main__":
    unittest.main()
