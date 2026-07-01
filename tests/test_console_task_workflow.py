from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from app.console import (
    build_parser,
    render_user_task_agenda,
    render_user_task_dashboard,
    render_user_task_reminders,
)
from agent.task_planner import StudentProfile
from agent.user_state import save_user_profile
from agent.task_state import upsert_user_task_state


TASK_ROWS = [
    {
        "task_id": "hkust-apply_student_visa",
        "school": "HKUST",
        "stage": "visa",
        "task_name": "申请学生签证 / 进入许可",
        "description": "准备并提交学生签证材料。",
        "trigger_condition": "尚未提交签证申请。",
        "deadline": "以学校签证页面为准。",
        "required_documents": "签证表格；录取证明。",
        "action_url": "https://example.edu/visa",
        "risk_level": "high",
        "source_url": "https://example.edu/visa",
        "updated_at": "2026-06-30",
        "task_code": "apply_student_visa",
    },
    {
        "task_id": "hkust-pay_tuition",
        "school": "HKUST",
        "stage": "payment",
        "task_name": "缴纳学费",
        "description": "核对账单并完成学费付款。",
        "trigger_condition": "学费账单已发布。",
        "deadline": "以账单日期为准。",
        "required_documents": "student ID；付款凭证。",
        "action_url": "https://example.edu/tuition",
        "risk_level": "medium",
        "source_url": "https://example.edu/tuition",
        "updated_at": "2026-06-30",
        "task_code": "pay_tuition",
    },
    {
        "task_id": "hkust-complete_registration",
        "school": "HKUST",
        "stage": "registration",
        "task_name": "完成线上注册",
        "description": "按要求完成注册流程。",
        "trigger_condition": "学校开放注册。",
        "deadline": "以注册指引为准。",
        "required_documents": "student ID；证件信息。",
        "action_url": "https://example.edu/registration",
        "risk_level": "high",
        "source_url": "https://example.edu/registration",
        "updated_at": "2026-06-30",
        "task_code": "complete_registration",
    },
]


class ConsoleTaskWorkflowTests(unittest.TestCase):
    def test_render_user_task_dashboard_shows_active_and_completed_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            tasks_csv = temp_dir / "tasks_enriched.csv"
            user_state_csv = temp_dir / "user_states.csv"
            task_state_csv = temp_dir / "user_task_states.csv"
            write_task_csv(tasks_csv, TASK_ROWS)

            save_user_profile(
                "demo-user",
                StudentProfile(
                    school="HKUST",
                    completed_flags={"accepted_offer", "paid_deposit"},
                ),
                path=user_state_csv,
            )
            upsert_user_task_state(
                user_id="demo-user",
                path=task_state_csv,
                school="HKUST",
                task_id="hkust-apply_student_visa",
                task_code="apply_student_visa",
                stage="visa",
                status="in_progress",
                deadline_at="2026-08-01",
                deadline_timezone="Asia/Hong_Kong",
                deadline_source="portal",
                deadline_source_ref="offer letter p.2",
                reminder_at="2026-07-25T09:00:00",
                reminder_status="pending",
            )
            upsert_user_task_state(
                user_id="demo-user",
                path=task_state_csv,
                school="HKUST",
                task_id="hkust-pay_tuition",
                task_code="pay_tuition",
                stage="payment",
                status="done",
                notes="already paid",
            )

            args = build_parser().parse_args(
                [
                    "--list-user-tasks",
                    "--user-id",
                    "demo-user",
                    "--user-state-csv",
                    str(user_state_csv),
                    "--task-state-csv",
                    str(task_state_csv),
                    "--tasks-enriched-csv",
                    str(tasks_csv),
                    "--use-enriched-tasks",
                    "--include-completed-tasks",
                    "--task-limit",
                    "10",
                ]
            )

            output = render_user_task_dashboard(args)

            self.assertIn("用户任务清单：demo-user", output)
            self.assertIn("申请学生签证 / 进入许可", output)
            self.assertIn("个人截止时间：2026-08-01 Asia/Hong_Kong", output)
            self.assertIn("截止追溯：portal | offer letter p.2", output)
            self.assertIn("官方来源：https://example.edu/visa", output)
            self.assertIn("已完成或已跳过：", output)
            self.assertIn("pay_tuition [done]", output)

    def test_render_user_task_reminders_lists_deadlines_and_filters_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            tasks_csv = temp_dir / "tasks_enriched.csv"
            user_state_csv = temp_dir / "user_states.csv"
            task_state_csv = temp_dir / "user_task_states.csv"
            write_task_csv(tasks_csv, TASK_ROWS)

            save_user_profile(
                "demo-user",
                StudentProfile(school="HKUST"),
                path=user_state_csv,
            )
            upsert_user_task_state(
                user_id="demo-user",
                path=task_state_csv,
                school="HKUST",
                task_id="hkust-apply_student_visa",
                task_code="apply_student_visa",
                stage="visa",
                status="in_progress",
                deadline_at="2026-08-01",
                deadline_source="portal",
                deadline_source_ref="offer letter p.2",
                reminder_at="2026-07-25T09:00:00",
                reminder_status="pending",
            )
            upsert_user_task_state(
                user_id="demo-user",
                path=task_state_csv,
                school="HKUST",
                task_id="hkust-pay_tuition",
                task_code="pay_tuition",
                stage="payment",
                status="done",
                deadline_at="2026-08-15",
            )

            args = build_parser().parse_args(
                [
                    "--list-task-reminders",
                    "--user-id",
                    "demo-user",
                    "--user-state-csv",
                    str(user_state_csv),
                    "--task-state-csv",
                    str(task_state_csv),
                    "--tasks-enriched-csv",
                    str(tasks_csv),
                    "--use-enriched-tasks",
                    "--status-filter",
                    "in_progress",
                ]
            )

            output = render_user_task_reminders(args)

            self.assertIn("任务提醒清单：demo-user", output)
            self.assertIn("申请学生签证 / 进入许可", output)
            self.assertIn("截止来源：portal", output)
            self.assertIn("来源备注：offer letter p.2", output)
            self.assertIn("官方来源：https://example.edu/visa", output)
            self.assertIn("提醒时间：2026-07-25T09:00:00（pending）", output)
            self.assertNotIn("缴纳学费", output)

    def test_render_user_task_agenda_groups_overdue_today_and_upcoming(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            tasks_csv = temp_dir / "tasks_enriched.csv"
            user_state_csv = temp_dir / "user_states.csv"
            task_state_csv = temp_dir / "user_task_states.csv"
            write_task_csv(tasks_csv, TASK_ROWS)

            save_user_profile(
                "demo-user",
                StudentProfile(school="HKUST"),
                path=user_state_csv,
            )
            upsert_user_task_state(
                user_id="demo-user",
                path=task_state_csv,
                school="HKUST",
                task_id="hkust-apply_student_visa",
                task_code="apply_student_visa",
                stage="visa",
                status="in_progress",
                reminder_at="2026-07-24T18:00:00",
                reminder_status="pending",
                deadline_at="2026-08-01",
            )
            upsert_user_task_state(
                user_id="demo-user",
                path=task_state_csv,
                school="HKUST",
                task_id="hkust-pay_tuition",
                task_code="pay_tuition",
                stage="payment",
                status="waiting",
                reminder_at="2026-07-25T09:00:00",
                reminder_status="pending",
                deadline_at="2026-07-28",
            )
            upsert_user_task_state(
                user_id="demo-user",
                path=task_state_csv,
                school="HKUST",
                task_id="hkust-complete_registration",
                task_code="complete_registration",
                stage="registration",
                status="not_started",
                deadline_at="2026-07-27",
            )

            args = build_parser().parse_args(
                [
                    "--list-task-agenda",
                    "--user-id",
                    "demo-user",
                    "--user-state-csv",
                    str(user_state_csv),
                    "--task-state-csv",
                    str(task_state_csv),
                    "--tasks-enriched-csv",
                    str(tasks_csv),
                    "--use-enriched-tasks",
                    "--agenda-date",
                    "2026-07-25",
                    "--agenda-days",
                    "3",
                    "--agenda-timezone",
                    "Asia/Hong_Kong",
                ]
            )

            output = render_user_task_agenda(args)

            self.assertIn("任务 agenda：demo-user", output)
            self.assertIn("已逾期：", output)
            self.assertIn("今天（2026-07-25）：", output)
            self.assertIn("未来 3 天：", output)
            self.assertIn("申请学生签证 / 进入许可", output)
            self.assertIn("缴纳学费", output)
            self.assertIn("完成线上注册", output)


def write_task_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
