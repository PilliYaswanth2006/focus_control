import ast
import os
import tempfile
import time
import unittest
from app import create_app
from app.database.connection import get_db
from config import Config


def _make_temp_app():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    class TempConfig(Config):
        TESTING = True
        DATABASE_PATH = db_path
        SECRET_KEY = "test-secret-key"

    app = create_app(TempConfig)
    return app, db_path


class AuthAndComplianceTestCase(unittest.TestCase):
    def setUp(self):
        self.app, self.db_path = _make_temp_app()
        self.client = self.app.test_client()

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_no_type_hints_and_no_orm(self):
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for cur_root, _, files in os.walk(root_dir):
            if any(skip in cur_root for skip in ("__pycache__", ".git", "vendor")):
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                path = os.path.join(cur_root, fn)
                with open(path, "r", encoding="utf-8") as fh:
                    src = fh.read()
                tree = ast.parse(src, filename=path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self.assertNotIn("sqlalchemy", alias.name.lower(), "ORM import found: " + path)
                    elif isinstance(node, ast.ImportFrom):
                        mod = (node.module or "").lower()
                        self.assertNotIn("sqlalchemy", mod, "ORM import found: " + path)
                        self.assertNotEqual(mod, "typing", "typing import found: " + path)
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.assertIsNone(node.returns, "Type annotation found in %s:%d" % (path, node.lineno))
                        for arg in list(node.args.args) + list(node.args.posonlyargs) + list(node.args.kwonlyargs):
                            self.assertIsNone(arg.annotation, "Arg annotation found in %s:%d" % (path, node.lineno))
                    elif isinstance(node, ast.AnnAssign):
                        self.fail("Variable annotation found in %s:%d" % (path, node.lineno))

    def test_setup_lock_unlock_relock_and_session_expiry(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/setup", resp.location)

        resp_tasks = self.client.get("/tasks", follow_redirects=False)
        self.assertEqual(resp_tasks.status_code, 302)
        self.assertIn("/setup", resp_tasks.location)

        resp = self.client.post(
            "/setup",
            data={
                "display_name": "Alex",
                "timezone": "UTC",
                "credential_type": "pin",
                "credential": "4321",
                "confirm_credential": "4321",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.location, "/")

        with self.app.app_context():
            row = get_db().execute("SELECT value FROM app_settings WHERE key = 'auth_password_hash'").fetchone()
            self.assertIsNotNone(row)
            self.assertNotEqual(row["value"], "4321")
            self.assertNotIn("4321", row["value"])

        for route in ["/", "/tasks", "/tasks/new", "/tasks/completed", "/challenges", "/challenges/new", "/statistics", "/settings"]:
            r = self.client.get(route)
            self.assertEqual(r.status_code, 200, "Failed route: " + route)

        relock_resp = self.client.post("/auth/relock", follow_redirects=False)
        self.assertEqual(relock_resp.status_code, 302)
        self.assertIn("/lock", relock_resp.location)

        blocked = self.client.get("/tasks", follow_redirects=False)
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("/lock", blocked.location)

        bad = self.client.post("/lock", data={"credential": "9999"}, follow_redirects=True)
        self.assertIn(b"Incorrect PIN or password", bad.data)

        good = self.client.post("/lock", data={"credential": "4321"}, follow_redirects=False)
        self.assertEqual(good.status_code, 302)
        self.assertEqual(good.location, "/")

        with self.client.session_transaction() as sess:
            sess["last_active_ts"] = time.time() - 7200
        expired = self.client.get("/challenges", follow_redirects=False)
        self.assertEqual(expired.status_code, 302)
        self.assertIn("/lock", expired.location)

    def test_end_to_end_http_workflows(self):
        self.client.post(
            "/setup",
            data={
                "display_name": "Alex",
                "timezone": "Asia/Kolkata",
                "credential_type": "password",
                "credential": "focuspass123",
                "confirm_credential": "focuspass123",
            },
        )

        # Create centered task via HTTP
        r = self.client.post(
            "/tasks/new",
            data={
                "name": "Deep Learning",
                "weight": "100",
                "allocation_mode": "budgeted",
                "priority": "High",
                "status": "Active",
            },
            follow_redirects=True,
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Deep Learning", r.data)

        # Add internal item & log progress via HTTP
        r_item = self.client.post(
            "/tasks/1/items/add",
            data={
                "item_type": "standard",
                "name": "Backpropagation",
                "weight_pct": "100",
                "target_quantity": "10",
                "target_unit": "hours",
                "status": "Active",
            },
            follow_redirects=True,
        )
        self.assertEqual(r_item.status_code, 200)
        self.assertIn(b"Backpropagation", r_item.data)

        r_prog = self.client.post(
            "/task-items/1/progress",
            data={"quantity_completed": "10", "time_spent_minutes": "600", "comments": "Completed module"},
            follow_redirects=True,
        )
        self.assertEqual(r_prog.status_code, 200)
        self.assertIn(b"Completed", r_prog.data)

        # Create challenge, record events, and visit daily tracking & statistics
        r_ch = self.client.post(
            "/challenges/new",
            data={
                "name": "Morning Focus",
                "behaviour_to_avoid": "Social media before noon",
                "start_immediately": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(r_ch.status_code, 200)
        self.assertIn(b"Morning Focus", r_ch.data)

        self.client.post("/challenges/1/events", data={"event_type": "URGE", "outcome": "Resisted"}, follow_redirects=True)
        r_daily = self.client.get("/challenges/1/daily")
        self.assertEqual(r_daily.status_code, 200)
        r_stats = self.client.get("/statistics?start_date=2026-01-01&end_date=2027-01-01")
        self.assertEqual(r_stats.status_code, 200)
        r_api = self.client.get("/statistics/api")
        self.assertEqual(r_api.status_code, 200)
        self.assertIn("tasks", r_api.get_json())

        # System theme toggle JSON & invalid fallback
        r_sys = self.client.post("/settings/toggle-theme", json={"theme": "system"})
        self.assertEqual(r_sys.status_code, 200)
        self.assertEqual(r_sys.get_json()["theme"], "system")
        r_dash = self.client.get("/")
        self.assertEqual(r_dash.status_code, 200)
        self.assertIn(b'data-theme-pref="system"', r_dash.data)

        # Task filter & clone routes
        r_filtered = self.client.get("/tasks?priority=High&sort_by=weight")
        self.assertEqual(r_filtered.status_code, 200)
        self.assertIn(b"Deep Learning", r_filtered.data)

        r_clone = self.client.post(
            "/tasks/1/clone",
            data={"new_name": "DL Cloned", "include_hierarchy_submitted": "1", "include_hierarchy": "1"},
            follow_redirects=True,
        )
        self.assertEqual(r_clone.status_code, 200)
        self.assertIn(b"DL Cloned", r_clone.data)

        # Soft delete cloned task & restore via Trash on Settings
        self.client.post("/tasks/2/delete", data={"confirm_force": "1"}, follow_redirects=True)
        r_settings = self.client.get("/settings")
        self.assertEqual(r_settings.status_code, 200)
        self.assertIn(b"DL Cloned", r_settings.data)
        self.client.post("/tasks/2/restore", follow_redirects=True)
        r_restored = self.client.get("/tasks/2")
        self.assertEqual(r_restored.status_code, 200)
        self.assertIn(b"DL Cloned", r_restored.data)

        # Calendar & Statistics presets
        r_cal = self.client.get("/calendar")
        self.assertEqual(r_cal.status_code, 200)
        self.assertIn(b"Monthly Productivity", r_cal.data)
        r_cal_day = self.client.get("/calendar/day-details?date=2026-10-15")
        self.assertEqual(r_cal_day.status_code, 200)
        self.assertTrue(r_cal_day.get_json()["ok"])

        r_preset = self.client.get("/statistics?preset=30d")
        self.assertEqual(r_preset.status_code, 200)
        self.assertIn(b"previous 30-day window", r_preset.data)


if __name__ == "__main__":
    unittest.main()
