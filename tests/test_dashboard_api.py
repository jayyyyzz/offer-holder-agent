from pathlib import Path
import csv
import tempfile
import unittest

from app.dashboard_api import build_dashboard_payload, save_task_state_from_payload
from agent.task_planner import StudentProfile
from agent.task_state import upsert_user_task_state
from agent.user_state import save_user_profile


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
        "updated_at": "2026-07-01",
        "task_code": "apply_student_visa",
        "evidence_count": "2",
        "candidate_evidence_count": "2",
        "usable_evidence_count": "2",
        "review_evidence_count": "0",
        "rejected_evidence_count": "0",
        "evidence_types": "deadline,required_document",
        "official_deadline_evidence": "Apply as soon as possible.",
        "official_document_evidence": "Passport copy.",
        "official_action_evidence": "Upload in portal.",
        "official_action_urls": "https://example.edu/visa",
        "official_fee_evidence": "",
        "evidence_ids": "e1;e2",
        "evidence_quality_status": "human_reviewed",
        "evidence_quality_notes": "Human review approved.",
        "enrichment_status": "review_approved",
        "enriched_at": "2026-07-01",
        "review_priority": "",
        "review_reason": "",
        "review_decision": "",
        "review_notes": "",
        "human_review_status": "not_required",
        "reviewed_at": "",
    }
]


class DashboardApiTests(unittest.TestCase):
    def test_payload_includes_catalog_and_traceability_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schools_csv = root / "schools.csv"
            reviewed_csv = root / "tasks_reviewed.csv"
            user_state_csv = root / "user_states.csv"
            task_state_csv = root / "user_task_states.csv"

            schools_csv.write_text(
                "school_id,school_name,official_website,offer_holder_url,admitted_student_url,visa_url,accommodation_url,tuition_url,orientation_url\n"
                "hkust,The Hong Kong University of Science and Technology,https://hkust.edu.hk/,,,,,,\n",
                encoding="utf-8",
            )
            write_csv(reviewed_csv, TASK_ROWS)

            save_user_profile(
                "demo-user",
                StudentProfile(school="HKUST", completed_flags={"accepted_offer"}),
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
                notes="prepare supporting docs",
            )

            payload = build_dashboard_payload(
                school="HKUST",
                user_id="demo-user",
                task_source="reviewed",
                tasks_reviewed_csv=reviewed_csv,
                tasks_enriched_csv=reviewed_csv,
                schools_csv=schools_csv,
                user_state_csv=user_state_csv,
                task_state_csv=task_state_csv,
            )

            self.assertEqual(payload["filters"]["task_source_effective"], "reviewed")
            self.assertEqual(payload["catalog"]["schools"][0]["code"], "HKUST")
            self.assertEqual(payload["tasks"][0]["personal_deadline_source_ref"], "offer letter p.2")
            self.assertEqual(payload["tasks"][0]["official_deadline_evidence"], "Apply as soon as possible.")
            self.assertEqual(payload["reminders"][0]["deadline_source_ref"], "offer letter p.2")

    def test_payload_falls_back_when_reviewed_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schools_csv = root / "schools.csv"
            enriched_csv = root / "tasks_enriched.csv"

            schools_csv.write_text(
                "school_id,school_name,official_website,offer_holder_url,admitted_student_url,visa_url,accommodation_url,tuition_url,orientation_url\n"
                "hkust,The Hong Kong University of Science and Technology,https://hkust.edu.hk/,,,,,,\n",
                encoding="utf-8",
            )
            write_csv(enriched_csv, TASK_ROWS)

            payload = build_dashboard_payload(
                school="HKUST",
                task_source="reviewed",
                tasks_enriched_csv=enriched_csv,
                tasks_reviewed_csv=root / "missing_reviewed.csv",
                schools_csv=schools_csv,
            )

            self.assertEqual(payload["filters"]["task_source_effective"], "enriched")
            self.assertTrue(payload["empty_hints"])
            self.assertEqual(payload["filters"]["task_source"], "reviewed")

    def test_payload_defaults_to_builtin_when_no_task_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schools_csv = root / "schools.csv"

            schools_csv.write_text(
                "school_id,school_name,official_website,offer_holder_url,admitted_student_url,visa_url,accommodation_url,tuition_url,orientation_url\n"
                "hkust,The Hong Kong University of Science and Technology,https://hkust.edu.hk/,,,,,,\n",
                encoding="utf-8",
            )

            payload = build_dashboard_payload(
                school="HKUST",
                task_source="reviewed",
                tasks_enriched_csv=root / "missing_enriched.csv",
                tasks_reviewed_csv=root / "missing_reviewed.csv",
                schools_csv=schools_csv,
            )

            self.assertEqual(payload["filters"]["task_source"], "reviewed")
            self.assertEqual(payload["filters"]["task_source_effective"], "builtin")
            self.assertGreater(len(payload["tasks"]), 0)
            self.assertTrue(any("tasks_reviewed.csv" in hint for hint in payload["empty_hints"]))

    def test_save_task_state_from_payload_writes_csv_backing_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_state_csv = root / "user_task_states.csv"

            state = save_task_state_from_payload(
                {
                    "user_id": "demo-user",
                    "school": "HKUST",
                    "task_code": "apply_student_visa",
                    "stage": "visa",
                    "status": "in_progress",
                    "deadline_at": "2026-08-01",
                    "deadline_timezone": "Asia/Hong_Kong",
                    "deadline_source": "portal",
                    "deadline_source_ref": "offer letter p.2",
                    "reminder_at": "2026-07-25T09:00:00",
                    "reminder_timezone": "Asia/Hong_Kong",
                    "reminder_status": "pending",
                    "notes": "prepare supporting docs",
                },
                task_state_csv=task_state_csv,
            )

            self.assertEqual(state.task_id, "hkust-apply_student_visa")
            self.assertTrue(task_state_csv.exists())

            payload = build_dashboard_payload(
                school="HKUST",
                user_id="demo-user",
                task_source="builtin",
                task_state_csv=task_state_csv,
            )
            task = next(item for item in payload["tasks"] if item["task_code"] == "apply_student_visa")
            self.assertEqual(task["task_status"], "in_progress")
            self.assertEqual(task["personal_reminder_timezone"], "Asia/Hong_Kong")


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
      writer = csv.DictWriter(handle, fieldnames=fieldnames)
      writer.writeheader()
      writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
