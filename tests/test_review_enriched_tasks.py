from pathlib import Path
import tempfile
import unittest

import pandas as pd

from knowledge_base.enrich_tasks import TASK_ENRICHED_COLUMNS
from knowledge_base.review_enriched_tasks import build_task_review_report


class ReviewEnrichedTasksTests(unittest.TestCase):
    def test_flags_pay_deposit_for_manual_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tasks_enriched.csv"
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "description": "Pay deposit.",
                        "trigger_condition": "Deposit required.",
                        "deadline": "Check portal.",
                        "required_documents": "Portal info.",
                        "action_url": "https://example.edu/deposit",
                        "risk_level": "high",
                        "source_url": "https://example.edu/deposit",
                        "updated_at": "2026-06-30",
                        "task_code": "pay_deposit",
                        "evidence_count": "1",
                        "candidate_evidence_count": "3",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "1",
                        "evidence_types": "deadline, action_instruction",
                        "official_deadline_evidence": "Pay the deposit before the deadline.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Login and pay online.",
                        "official_action_urls": "https://example.edu/deposit",
                        "official_fee_evidence": "HK$5,000",
                        "evidence_ids": "e1; e2; e3",
                        "evidence_quality_status": "audited",
                        "evidence_quality_notes": "1 keep; 1 review/missing; 1 reject",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-06-30",
                    }
                ],
                columns=TASK_ENRICHED_COLUMNS,
            ).to_csv(csv_path, index=False)

            report = build_task_review_report(csv_path)

            self.assertEqual(len(report), 1)
            row = report.iloc[0]
            self.assertEqual(row["review_priority"], "high")
            self.assertIn("general admission FAQ", row["review_reason"])

    def test_skips_clean_non_ambiguous_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "tasks_enriched.csv"
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "task_name": "申请学生签证",
                        "description": "Apply visa.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Apply ASAP.",
                        "required_documents": "Visa form.",
                        "action_url": "https://example.edu/visa",
                        "risk_level": "high",
                        "source_url": "https://example.edu/visa",
                        "updated_at": "2026-06-30",
                        "task_code": "apply_student_visa",
                        "evidence_count": "2",
                        "candidate_evidence_count": "2",
                        "usable_evidence_count": "2",
                        "review_evidence_count": "0",
                        "rejected_evidence_count": "0",
                        "evidence_types": "deadline,required_document",
                        "official_deadline_evidence": "Submit as soon as possible.",
                        "official_document_evidence": "Passport copy.",
                        "official_action_evidence": "",
                        "official_action_urls": "https://example.edu/visa",
                        "official_fee_evidence": "",
                        "evidence_ids": "e1; e2",
                        "evidence_quality_status": "audited",
                        "evidence_quality_notes": "2 keep",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-06-30",
                    }
                ],
                columns=TASK_ENRICHED_COLUMNS,
            ).to_csv(csv_path, index=False)

            report = build_task_review_report(csv_path)

            self.assertTrue(report.empty)


if __name__ == "__main__":
    unittest.main()
