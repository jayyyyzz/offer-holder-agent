from pathlib import Path
import tempfile
import unittest

from agent.intent_router import route_intent
from agent.task_planner import StudentProfile, TaskPlanner
from agent.task_state import (
    TaskState,
    load_user_task_states,
    upsert_user_task_state,
    validate_status,
)


class TaskStateTests(unittest.TestCase):
    def test_user_task_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_task_states.csv"

            upsert_user_task_state(
                user_id="demo-user",
                path=path,
                school="HKUST",
                task_id="hkust-apply_student_visa",
                task_code="apply_student_visa",
                stage="visa",
                status="in_progress",
                deadline_at="2026-08-01",
                deadline_timezone="Asia/Hong_Kong",
                deadline_source="portal",
                reminder_at="2026-07-25T09:00:00",
                reminder_status="pending",
                notes="test note",
            )

            states = load_user_task_states("demo-user", path, school="HKUST")

            self.assertIn("hkust-apply_student_visa", states)
            self.assertIn("apply_student_visa", states)
            state = states["apply_student_visa"]
            self.assertEqual(state.status, "in_progress")
            self.assertEqual(state.deadline_at, "2026-08-01")
            self.assertEqual(state.reminder_status, "pending")

    def test_invalid_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_status("almost_done")

    def test_planner_filters_done_task_state_and_applies_deadline_state(self) -> None:
        planner = TaskPlanner()
        profile = StudentProfile(school="HKUST", completed_flags={"accepted_offer"})
        intent = route_intent("HKUST student visa next step", default_school="HKUST")

        done_tasks = planner.plan(
            profile,
            intent=intent,
            task_states={
                "hkust-apply_student_visa": TaskState(
                    user_id="demo-user",
                    school="HKUST",
                    task_id="hkust-apply_student_visa",
                    task_code="apply_student_visa",
                    status="done",
                )
            },
        )
        self.assertNotIn("apply_student_visa", {task.task_code for task in done_tasks})

        active_tasks = planner.plan(
            profile,
            intent=intent,
            task_states={
                "hkust-apply_student_visa": TaskState(
                    user_id="demo-user",
                    school="HKUST",
                    task_id="hkust-apply_student_visa",
                    task_code="apply_student_visa",
                    status="in_progress",
                    deadline_at="2026-08-01",
                    deadline_timezone="Asia/Hong_Kong",
                    reminder_at="2026-07-25T09:00:00",
                    reminder_status="pending",
                )
            },
        )

        visa_task = next(task for task in active_tasks if task.task_code == "apply_student_visa")
        self.assertEqual(visa_task.user_task_status, "in_progress")
        self.assertEqual(visa_task.user_deadline_at, "2026-08-01")
        self.assertIn("个人截止时间", visa_task.reason)


if __name__ == "__main__":
    unittest.main()
