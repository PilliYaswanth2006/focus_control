import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from app import create_app
from app.services import auth_service, calendar_service, challenge_service, progress_service, task_service
from config import Config


class CalendarAndDataManagementTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.backup_dir = os.path.join(os.path.dirname(os.path.abspath(self.db_path)), "backups")

        class TempConfig(Config):
            TESTING = True
            DATABASE_PATH = self.db_path
            SECRET_KEY = "test-secret"

        self.app = create_app(TempConfig)
        self.client = self.app.test_client()
        self.client.post(
            "/setup",
            data={
                "display_name": "Tester",
                "timezone": "UTC",
                "credential_type": "pin",
                "credential": "1234",
                "confirm_credential": "1234",
            },
        )

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass
        if os.path.exists(self.backup_dir):
            import shutil
            shutil.rmtree(self.backup_dir, ignore_errors=True)

    def test_calendar_accuracy_no_synthetic_data_and_filters(self):
        with self.app.app_context():
            # Empty month should have zero total_activity across every day cell
            empty_cal = calendar_service.get_calendar_month_data(month_str="2025-02")
            self.assertEqual(len(empty_cal["weeks"][0]), 7)
            for week in empty_cal["weeks"]:
                for d in week:
                    self.assertEqual(d["total_activity"], 0)

            ct_id = task_service.create_centered_task({"name": "Reading", "weight": "100"})
            item_id = task_service.add_internal_task_item(
                ct_id, {"name": "Algorithms Book", "weight_pct": "100", "target_quantity": "100", "target_unit": "pages"}
            )
            progress_service.add_progress_entry(
                item_id,
                {"quantity_completed": "25", "time_spent_minutes": "90", "entry_timestamp": "2026-11-12T10:00"},
            )

            ch_id = challenge_service.create_challenge(
                {"name": "Zero Shorts", "behaviour_to_avoid": "Shorts", "start_immediately": "1"}
            )
            challenge_service.record_event(
                ch_id,
                {
                    "event_type": "URGE",
                    "outcome": "Resisted",
                    "trigger_category": "Boredom",
                    "event_timestamp": "2026-11-12T15:30",
                },
            )
            challenge_service.add_daily_reflection(ch_id, "2026-11-12", "Checkin", "Avoided reel impulse")

            cal_all = calendar_service.get_calendar_month_data(
                month_str="2026-11", selected_date="2026-11-12", module_filter="all"
            )
            day12 = cal_all["selected_day"]
            self.assertEqual(day12["task_hours"], 1.5)
            self.assertEqual(day12["resisted"], 1)
            self.assertEqual(day12["note_count"], 1)
            self.assertEqual(day12["total_activity"], 3)

            cal_tasks = calendar_service.get_calendar_month_data(
                month_str="2026-11", selected_date="2026-11-12", module_filter="tasks"
            )
            self.assertEqual(cal_tasks["selected_day"]["task_hours"], 1.5)
            self.assertEqual(cal_tasks["selected_day"]["resisted"], 0)
            self.assertEqual(cal_tasks["selected_day"]["note_count"], 0)

            cal_other = calendar_service.get_calendar_month_data(
                month_str="2026-11", selected_date="2026-11-01", module_filter="all"
            )
            self.assertEqual(cal_other["selected_day"]["total_activity"], 0)

    def test_backup_restore_json_and_csv_zip_exports(self):
        with self.app.app_context():
            ct_id = task_service.create_centered_task({"name": "Original Task", "weight": "100"})
            task_service.add_internal_task_item(
                ct_id, {"name": "Item 1", "weight_pct": "100", "target_quantity": "10", "target_unit": "hours"}
            )
            ch_id = challenge_service.create_challenge(
                {"name": "Original Challenge", "behaviour_to_avoid": "Snacking", "start_immediately": "1"}
            )
            challenge_service.record_event(ch_id, {"event_type": "URGE", "outcome": "Resisted", "trigger_category": "Stress"})

        # 1. Download SQLite backup and verify valid SQLite header & content
        b_resp = self.client.get("/settings/backup/download")
        self.assertEqual(b_resp.status_code, 200)
        backup_bytes = b_resp.data
        self.assertTrue(backup_bytes.startswith(b"SQLite format 3\x00"))

        # 2. Export JSON and ensure password hash & lockout secrets are NEVER exposed
        j_resp = self.client.get("/settings/export/json?include_demo=1")
        self.assertEqual(j_resp.status_code, 200)
        exported = json.loads(j_resp.data.decode("utf-8"))
        self.assertNotIn("auth_password_hash", exported["settings"])
        self.assertNotIn("auth_failed_attempts", exported["settings"])
        self.assertNotIn("auth_locked_until", exported["settings"])
        self.assertEqual(len(exported["centered_tasks"]), 1)
        self.assertEqual(len(exported["urge_events"]), 1)

        # 3. Export ZIP of all CSV datasets & single CSV dataset
        z_resp = self.client.get("/settings/export/csv?dataset=all")
        self.assertEqual(z_resp.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(z_resp.data), "r") as zf:
            names = set(zf.namelist())
            self.assertEqual(
                names,
                {
                    "centered_tasks.csv",
                    "task_progress_entries.csv",
                    "challenges.csv",
                    "urge_events.csv",
                    "daily_reflections_and_comments.csv",
                },
            )
            self.assertIn("Original Task", zf.read("centered_tasks.csv").decode("utf-8-sig"))

        csv_resp = self.client.get("/settings/export/csv?dataset=urge_events")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("Stress", csv_resp.data.decode("utf-8-sig"))

        # 4. Mutate database after backup, then restore from backup and verify state reverted cleanly
        with self.app.app_context():
            ch2 = challenge_service.create_challenge(
                {"name": "Post Backup Ephemeral", "behaviour_to_avoid": "Test"}
            )
            self.assertIsNotNone(challenge_service.get_challenge_details(ch2))

        # Invalid extension / corrupted file must be rejected without touching live DB
        bad_resp = self.client.post(
            "/settings/backup/restore",
            data={"backup_file": (io.BytesIO(b"not a sqlite file"), "evil.txt")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b".db, .sqlite, or .sqlite3", bad_resp.data)

        bad_header = self.client.post(
            "/settings/backup/restore",
            data={"backup_file": (io.BytesIO(b"corrupted bytes"), "fake.db")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"not a valid SQLite 3 database", bad_header.data)

        # Missing required tables sqlite file must be rejected
        fd_empty, empty_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd_empty)
        try:
            ec = sqlite3.connect(empty_db_path)
            ec.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
            ec.commit()
            ec.close()
            with open(empty_db_path, "rb") as fh:
                incomplete_bytes = fh.read()
        finally:
            os.remove(empty_db_path)

        miss_resp = self.client.post(
            "/settings/backup/restore",
            data={"backup_file": (io.BytesIO(incomplete_bytes), "incomplete.db")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(b"missing required Focus", miss_resp.data)

        # Valid backup restore restores exact state prior to "Post Backup Ephemeral"
        ok_resp = self.client.post(
            "/settings/backup/restore",
            data={"backup_file": (io.BytesIO(backup_bytes), "backup.db")},
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(ok_resp.status_code, 200)
        self.assertIn(b"SQLite backup restored successfully", ok_resp.data)

        with self.app.app_context():
            all_ch = challenge_service.list_challenges_with_metrics()
            self.assertEqual([c["name"] for c in all_ch], ["Original Challenge"])


if __name__ == "__main__":
    unittest.main()
