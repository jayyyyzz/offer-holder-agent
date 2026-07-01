from pathlib import Path
import tempfile
import unittest

import pandas as pd

from agent.task_planner import TASK_COLUMNS
from crawler.crawl_pages import SOURCE_COLUMNS
from knowledge_base.audit_task_evidence_quality import (
    TASK_EVIDENCE_QUALITY_COLUMNS,
    build_task_evidence_quality_report,
)
from knowledge_base.enrich_tasks import build_enriched_tasks
from knowledge_base.extract_task_evidence import TASK_EVIDENCE_COLUMNS


class TaskEvidenceQualityTests(unittest.TestCase):
    def test_quality_report_marks_strong_visa_evidence_as_keep_and_context_as_reject(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence_csv = root / "task_evidence.csv"
            source_list = root / "source_list.csv"

            pd.DataFrame(
                [
                    {
                        "evidence_id": "keep-1",
                        "task_code": "apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "evidence_type": "deadline",
                        "evidence_text": "Non-local students should submit the student visa and entry permit application as soon as possible.",
                        "normalized_value": "as soon as possible",
                        "source_question": "When should I apply for a student visa?",
                        "source_url": "https://example.edu/visa",
                        "confidence": "high",
                        "updated_at": "2026-06-30",
                    },
                    {
                        "evidence_id": "reject-1",
                        "task_code": "apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "evidence_type": "source_context",
                        "evidence_text": "General admissions FAQ navigation and menu links.",
                        "normalized_value": "",
                        "source_question": "Admissions FAQ",
                        "source_url": "https://example.edu/visa",
                        "confidence": "high",
                        "updated_at": "2026-06-30",
                    },
                ],
                columns=TASK_EVIDENCE_COLUMNS,
            ).to_csv(evidence_csv, index=False)

            pd.DataFrame(
                [
                    {
                        "school": "HKUST",
                        "page_type": "visa",
                        "stage": "visa",
                        "url": "https://example.edu/visa",
                        "priority": "1",
                        "need_dynamic": "no",
                        "remark": "",
                    }
                ],
                columns=SOURCE_COLUMNS,
            ).to_csv(source_list, index=False)

            report = build_task_evidence_quality_report(evidence_csv, source_list)
            decisions = dict(zip(report["evidence_id"], report["quality_decision"]))

            self.assertEqual(decisions["keep-1"], "keep")
            self.assertEqual(decisions["reject-1"], "reject")

    def test_enriched_tasks_only_promotes_keep_evidence_when_quality_report_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_csv = root / "tasks.csv"
            evidence_csv = root / "task_evidence.csv"
            quality_csv = root / "task_evidence_quality_report.csv"

            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "task_name": "Apply for student visa",
                        "description": "Submit visa materials.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Check school portal.",
                        "required_documents": "Check school portal.",
                        "action_url": "https://example.edu/visa",
                        "risk_level": "high",
                        "source_url": "https://example.edu/visa",
                        "updated_at": "2026-06-30",
                    }
                ],
                columns=TASK_COLUMNS,
            ).to_csv(tasks_csv, index=False)

            pd.DataFrame(
                [
                    {
                        "evidence_id": "keep-1",
                        "task_code": "apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "evidence_type": "deadline",
                        "evidence_text": "Submit the student visa application as soon as possible.",
                        "normalized_value": "as soon as possible",
                        "source_question": "When should I apply?",
                        "source_url": "https://example.edu/visa",
                        "confidence": "high",
                        "updated_at": "2026-06-30",
                    },
                    {
                        "evidence_id": "reject-1",
                        "task_code": "apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "evidence_type": "deadline",
                        "evidence_text": "Scholarship application fee refund information.",
                        "normalized_value": "refund information",
                        "source_question": "Scholarship refund",
                        "source_url": "https://example.edu/visa",
                        "confidence": "low",
                        "updated_at": "2026-06-30",
                    },
                ],
                columns=TASK_EVIDENCE_COLUMNS,
            ).to_csv(evidence_csv, index=False)

            pd.DataFrame(
                [
                    {"evidence_id": "keep-1", "quality_decision": "keep"},
                    {"evidence_id": "reject-1", "quality_decision": "reject"},
                ],
                columns=TASK_EVIDENCE_QUALITY_COLUMNS,
            ).to_csv(quality_csv, index=False)

            frame = build_enriched_tasks(tasks_csv, evidence_csv, quality_csv)
            row = frame.iloc[0]

            self.assertEqual(row["candidate_evidence_count"], 2)
            self.assertEqual(row["usable_evidence_count"], 1)
            self.assertEqual(row["rejected_evidence_count"], 1)
            self.assertIn("as soon as possible", row["official_deadline_evidence"])
            self.assertNotIn("Scholarship", row["official_deadline_evidence"])


if __name__ == "__main__":
    unittest.main()
