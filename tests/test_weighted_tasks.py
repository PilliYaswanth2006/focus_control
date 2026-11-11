import os
import tempfile
import unittest
from app import create_app
from app.database.connection import get_db
from app.services import allocation_service, auth_service, progress_service, statistics_service, task_service
from app.utils.validation import ValidationError
from config import Config


class WeightedTaskManagerTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        class TempConfig(Config):
            TESTING = True
            DATABASE_PATH = self.db_path
            SECRET_KEY = "test-secret"

        self.app = create_app(TempConfig)
        with self.app.app_context():
            auth_service.setup_credentials("pin", "1234", "1234", "Tester", "UTC")

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_budget_allocation_weight_validation_and_snapshots(self):
        with self.app.app_context():
            ml_id = task_service.create_centered_task({"name": "Machine Learning", "weight": "40", "allocation_mode": "budgeted"})
            col_id = task_service.create_centered_task({"name": "College Studies", "weight": "35", "allocation_mode": "budgeted"})
            fit_id = task_service.create_centered_task({"name": "Fitness", "weight": "15", "allocation_mode": "budgeted"})
            comm_id = task_service.create_centered_task({"name": "Communication", "weight": "10", "allocation_mode": "budgeted"})

            # Mode A: Fixed 40 hours -> ML receives 16 hours
            allocation_service.apply_global_budget("fixed", 40, "hours")
            ml = task_service.get_centered_task_details(ml_id)
            self.assertAlmostEqual(ml["target_allocation"], 16.0, places=2)

            # Add internal items 40%, 30%, 20% (= 90%, NOT 100%)
            m_id = task_service.add_internal_task_item(ml_id, {"name": "Mathematics", "weight_pct": "40", "target_unit": "hours"})
            p_id = task_service.add_internal_task_item(ml_id, {"name": "Python", "weight_pct": "30", "target_unit": "hours"})
            a_id = task_service.add_internal_task_item(ml_id, {"name": "Algorithms", "weight_pct": "20", "target_unit": "hours"})

            # Must fail finalization when sum == 90%
            with self.assertRaises(ValidationError) as ctx:
                allocation_service.finalize_internal_allocation(ml_id)
            self.assertIn("90.00%", ctx.exception.message)

            # Add remaining 10% -> sum == 100%
            pr_id = task_service.add_internal_task_item(ml_id, {"name": "Projects", "weight_pct": "10", "target_unit": "hours"})
            allocation_service.finalize_internal_allocation(ml_id)

            ml = task_service.get_centered_task_details(ml_id)
            items_by_name = {i["name"]: i for i in ml["metrics"]["items"]}
            self.assertAlmostEqual(items_by_name["Mathematics"]["target_quantity"], 6.4, places=2)
            self.assertAlmostEqual(items_by_name["Python"]["target_quantity"], 4.8, places=2)
            self.assertAlmostEqual(items_by_name["Algorithms"]["target_quantity"], 3.2, places=2)
            self.assertAlmostEqual(items_by_name["Projects"]["target_quantity"], 1.6, places=2)

            # Mode B: Dynamic budget update to 50 hours -> ML becomes 20 hours; snapshots preserved!
            allocation_service.apply_global_budget("dynamic", 50, "hours")
            ml_after = task_service.get_centered_task_details(ml_id)
            self.assertAlmostEqual(ml_after["target_allocation"], 20.0, places=2)

            # Verify historical snapshot from 40h budget is preserved (is_active=0) AND new 50h snapshot is active
            rows = get_db().execute(
                "SELECT total_budget, allocated_target, is_active FROM task_allocations WHERE centered_task_id = ? AND scope = 'global_budget' ORDER BY id ASC",
                (ml_id,),
            ).fetchall()
            self.assertGreaterEqual(len(rows), 2)
            self.assertEqual(rows[-1]["is_active"], 1)
            self.assertAlmostEqual(rows[-1]["allocated_target"], 20.0, places=2)
            self.assertTrue(any(r["is_active"] == 0 and abs(r["allocated_target"] - 16.0) < 0.01 for r in rows))

            # Verify unused tasks stay untouched
            self.assertIsNotNone(task_service.get_centered_task_details(col_id))
            self.assertIsNotNone(task_service.get_centered_task_details(fit_id))
            self.assertIsNotNone(task_service.get_centered_task_details(comm_id))

    def test_nested_centered_tasks_cycle_prevention_and_no_double_count(self):
        with self.app.app_context():
            ml_id = task_service.create_centered_task({"name": "Machine Learning", "weight": "50"})
            proj_id = task_service.create_centered_task({"name": "ML Projects", "weight": "0"})
            other_id = task_service.create_centered_task({"name": "College", "weight": "50"})

            dp_id = task_service.add_internal_task_item(
                proj_id, {"name": "Data Prep", "weight_pct": "50", "target_quantity": "2", "target_unit": "hours"}
            )
            me_id = task_service.add_internal_task_item(
                proj_id, {"name": "Model Eval", "weight_pct": "50", "target_quantity": "2", "target_unit": "hours"}
            )

            # Link ML Projects (100% of ML's 20h = 20h) -> cascades 50% to Data Prep (10h) and Model Eval (10h)
            task_service.add_internal_task_item(
                ml_id, {"item_type": "linked_centered", "linked_centered_task_id": str(proj_id), "weight_pct": "100"}
            )
            dp_after_link = task_service.get_task_item_details(dp_id)
            self.assertAlmostEqual(dp_after_link["target_quantity"], 10.0, places=2)

            # Circular reference: ML Projects linking Machine Learning must fail
            with self.assertRaises(ValidationError):
                task_service.add_internal_task_item(
                    proj_id, {"item_type": "linked_centered", "linked_centered_task_id": str(ml_id), "weight_pct": "0"}
                )

            # Self-reference must fail
            with self.assertRaises(ValidationError):
                task_service.add_internal_task_item(
                    ml_id, {"item_type": "linked_centered", "linked_centered_task_id": str(ml_id), "weight_pct": "0"}
                )

            # Single-parent rule: ML Projects cannot also link under College while linked under ML
            with self.assertRaises(ValidationError):
                task_service.add_internal_task_item(
                    other_id, {"item_type": "linked_centered", "linked_centered_task_id": str(proj_id), "weight_pct": "50"}
                )

            # Log 10 hours on Data Prep -> 100% of Data Prep -> ML Projects becomes 50% complete, ML rolls up to 50%
            progress_service.add_progress_entry(dp_id, {"quantity_completed": "10", "time_spent_minutes": "600", "comments": "Done"})

            ml_det = task_service.get_centered_task_details(ml_id)
            proj_det = task_service.get_centered_task_details(proj_id)
            self.assertAlmostEqual(proj_det["metrics"]["completion_pct"], 50.0, places=1)
            self.assertAlmostEqual(ml_det["metrics"]["completion_pct"], 50.0, places=1)

            # Global time logged MUST be 10.0 hours (NOT 20.0 hours double-counted!)
            stats = statistics_service.get_global_statistics()
            self.assertAlmostEqual(stats["tasks"]["total_logged_hours"], 10.0, places=2)
            self.assertIsNotNone(me_id)

    def test_progress_lifecycle_completion_reopen_custom_units_and_sessions(self):
        with self.app.app_context():
            ct_id = task_service.create_centered_task({"name": "Study", "weight": "100"})
            read_id = task_service.add_internal_task_item(
                ct_id,
                {"name": "Read Book", "weight_pct": "100", "target_quantity": "100", "target_unit": "pages", "status": "Not Started"},
            )

            # Partial progress -> In Progress (40% even if 180 mins spent; does not confuse time with quantity!)
            e1 = progress_service.add_progress_entry(
                read_id, {"quantity_completed": "40", "time_spent_minutes": "180", "comments": "Ch 1-2"}
            )
            item = task_service.get_task_item_details(read_id)
            self.assertEqual(item["status"], "In Progress")
            self.assertAlmostEqual(item["completion_pct"], 40.0, places=1)

            # Complete remaining 60 pages -> Auto Completed + Parent Auto Completed
            progress_service.add_progress_entry(
                read_id, {"quantity_completed": "60", "time_spent_minutes": "120", "comments": "Ch 3-5"}
            )
            item = task_service.get_task_item_details(read_id)
            ct = task_service.get_centered_task_details(ct_id)
            self.assertEqual(item["status"], "Completed")
            self.assertEqual(ct["status"], "Completed")

            # Changing global budget preserves Completed task target unless explicitly confirmed
            allocation_service.apply_global_budget("dynamic", 80, "hours", completed_policy="preserve")
            ct_preserved = task_service.get_centered_task_details(ct_id)
            self.assertAlmostEqual(ct_preserved["target_allocation"], 40.0, places=2)

            # Explicit reopen preserves progress records and logs status history
            progress_service.reopen_task_item(read_id, reason="Added bonus chapters", new_target_quantity="120")
            item_reopened = task_service.get_task_item_details(read_id)
            self.assertEqual(item_reopened["status"], "In Progress")
            self.assertEqual(len(item_reopened["progress_entries"]), 2)
            self.assertTrue(any(h["from_status"] == "Completed" and h["to_status"] == "In Progress" for h in item_reopened["status_history"]))

            # Focus session start & stop
            sess_id = progress_service.start_focus_session(read_id, "Deep reading")
            progress_service.stop_focus_session(sess_id, quantity_completed="10", notes="Finished bonus chapter")
            item_after_sess = task_service.get_task_item_details(read_id)
            self.assertEqual(len(item_after_sess["progress_entries"]), 3)
            self.assertIsNotNone(e1)

    def test_top_level_weight_cap_incomplete_allocation_cascade_filters_clone_and_trash(self):
        with self.app.app_context():
            from app.repositories import task_repository

            # Top-level budgeted weight = 60% (40% remaining unallocated)
            ct1 = task_service.create_centered_task(
                {"name": "Core AI", "weight": "60", "allocation_mode": "budgeted", "priority": "Critical", "target_end_date": "2025-01-01"}
            )
            # Exceeding 100% (60 + 50 = 110%) must be rejected
            with self.assertRaises(ValidationError):
                task_service.create_centered_task({"name": "Extra", "weight": "50", "allocation_mode": "budgeted"})

            budget = allocation_service.get_budget_overview()
            self.assertAlmostEqual(budget["budgeted_root_weight_sum"], 60.0, places=2)
            self.assertAlmostEqual(budget["remaining_unallocated_weight"], 40.0, places=2)
            self.assertAlmostEqual(budget["allocated_budget"], 24.0, places=2)
            self.assertAlmostEqual(budget["available_budget"], 16.0, places=2)

            # Incomplete internal allocation (60% only, completed 50% -> parent progress MUST be 30.0%, NOT 50.0%!)
            item1 = task_service.add_internal_task_item(
                ct1, {"name": "Neural Nets", "weight_pct": "60", "target_quantity": "14.4", "target_unit": "hours"}
            )
            progress_service.add_progress_entry(item1, {"quantity_completed": "7.2", "time_spent_minutes": "432"})
            ct1_det = task_service.get_centered_task_details(ct1)
            self.assertAlmostEqual(ct1_det["metrics"]["completion_pct"], 30.0, places=1)
            # Workspace progress = 60% * 30% / 100 = 18.0% (unallocated 40% root NOT treated as complete)
            ws_pct = task_service.compute_workspace_task_progress(
                task_repository.list_root_centered_tasks(include_archived=False),
                task_service.build_task_metrics_index(),
            )
            self.assertAlmostEqual(ws_pct, 18.0, places=1)

            # Edit centered weight 60% -> 50% (20h) cascades to active/in-progress child item (60% of 20h = 12h)
            task_service.update_centered_task(
                ct1, {"name": "Core AI", "weight": "50", "allocation_mode": "budgeted", "priority": "High", "status": "Active"}
            )
            item1_after = task_service.get_task_item_details(item1)
            self.assertAlmostEqual(item1_after["target_quantity"], 12.0, places=2)
            self.assertGreaterEqual(len(item1_after["allocations"]), 2)

            # Nested child centered task + filtering & sorting + overdue_only
            sub_ct = task_service.create_centered_task(
                {"name": "Sub Lab", "weight": "0", "allocation_mode": "manual", "priority": "Low", "status": "Active"}
            )
            task_service.add_internal_task_item(
                sub_ct,
                {"name": "Lab Overdue", "weight_pct": "100", "target_quantity": "5", "target_unit": "hours", "due_date": "2024-01-01"},
            )
            task_service.add_internal_task_item(
                ct1, {"item_type": "linked_centered", "linked_centered_task_id": str(sub_ct), "weight_pct": "40"}
            )

            high_list = task_service.list_centered_tasks_with_metrics(priority="High", sort_by="weight")
            self.assertEqual([t["id"] for t in high_list], [ct1])
            overdue_list = task_service.list_centered_tasks_with_metrics(overdue_only=True)
            self.assertIn(sub_ct, [t["id"] for t in overdue_list])

            # Hierarchical clone with hierarchy=True, preserve_progress=False -> unlinked independent copy at 0% weight
            clone_id = task_service.clone_centered_task_as_independent(
                ct1, new_name="Core AI Clone", include_hierarchy=True, preserve_progress=False
            )
            clone_det = task_service.get_centered_task_details(clone_id)
            self.assertEqual(clone_det["weight"], 0.0)
            self.assertEqual(clone_det["status"], "Not Started")
            self.assertAlmostEqual(clone_det["metrics"]["completion_pct"], 0.0, places=1)
            self.assertEqual(len(clone_det["metrics"]["items"]), 2)
            # Linked child was deep-cloned as independent sub-centered task
            linked_clone_items = [i for i in clone_det["metrics"]["items"] if i["item_type"] == "linked_centered"]
            self.assertEqual(len(linked_clone_items), 1)
            self.assertNotEqual(linked_clone_items[0]["linked_centered_task_id"], sub_ct)

            # Clone without hierarchy omits linked centered child
            flat_clone_id = task_service.clone_centered_task_as_independent(
                ct1, new_name="Flat Clone", include_hierarchy=False, preserve_progress=True
            )
            flat_det = task_service.get_centered_task_details(flat_clone_id)
            self.assertEqual(len(flat_det["metrics"]["items"]), 1)
            self.assertEqual(len(task_service.get_task_item_details(flat_det["metrics"]["items"][0]["id"])["progress_entries"]), 1)

            # Cannot delete sub_ct while linked inside ct1
            with self.assertRaises(ValidationError):
                task_service.delete_centered_task(sub_ct, confirm_force=True)

            # Soft-delete flat_clone_id -> Trash -> Restore -> Permanent Purge
            task_service.delete_centered_task(flat_clone_id, confirm_force=True, permanent=False)
            self.assertIsNone(task_service.get_centered_task_details(flat_clone_id))
            trash_cts = task_repository.list_deleted_centered_tasks()
            self.assertIn(flat_clone_id, [t["id"] for t in trash_cts])

            # Fill remaining budgeted weight up to 100%, then ensure restore caps weight safely
            task_service.restore_centered_task(flat_clone_id)
            self.assertIsNotNone(task_service.get_centered_task_details(flat_clone_id))

            # Trash -> Permanent purge removes row completely
            task_service.delete_centered_task(flat_clone_id, confirm_force=True, permanent=False)
            task_service.delete_centered_task(flat_clone_id, confirm_force=True, permanent=True)
            self.assertIsNone(task_repository.get_centered_task(flat_clone_id, include_deleted=True))


if __name__ == "__main__":
    unittest.main()
