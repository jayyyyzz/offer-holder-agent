from pathlib import Path
import tempfile
import unittest

import pandas as pd

from agent.intent_router import route_intent
from agent.task_planner import StudentProfile, TaskPlanner
from knowledge_base.enrich_tasks import TASK_ENRICHED_COLUMNS
from knowledge_base.review_enriched_tasks import TASK_REVIEW_COLUMNS, build_task_review_report
from knowledge_base.reviewed_tasks import (
    TASK_REVIEW_SUMMARY_COLUMNS,
    TASK_REVIEW_PENDING_EXPORT_COLUMNS,
    TASK_REVIEW_DECISION_COLUMNS,
    TASK_REVIEWED_COLUMNS,
    build_review_pending_export,
    build_review_pending_summary,
    build_reviewed_tasks,
    init_task_review_decisions,
)


class ReviewedTasksTests(unittest.TestCase):
    def test_init_task_review_decisions_prefills_report_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_csv = root / "tasks_enriched_review.csv"
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "task_code": "pay_deposit",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "candidate_evidence_count": "2",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "0",
                        "evidence_quality_status": "audited",
                        "enrichment_status": "evidence_found",
                        "official_deadline_evidence": "Deposit due before the deadline.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Pay online in the portal.",
                        "official_action_urls": "https://example.edu/deposit",
                        "official_fee_evidence": "HK$5,000",
                        "review_priority": "high",
                        "review_reason": "Needs human confirmation.",
                        "suggested_action": "Check portal and offer letter.",
                        "generated_at": "2026-07-01",
                    }
                ],
                columns=TASK_REVIEW_COLUMNS,
            ).to_csv(report_csv, index=False)

            frame = init_task_review_decisions(report_csv)

            self.assertEqual(list(frame.columns), TASK_REVIEW_DECISION_COLUMNS)
            self.assertEqual(len(frame), 1)
            row = frame.iloc[0]
            self.assertEqual(row["reviewer_decision"], "")
            self.assertEqual(row["reviewed_deadline_evidence"], "Deposit due before the deadline.")
            self.assertEqual(row["reviewed_action_urls"], "https://example.edu/deposit")

    def test_build_reviewed_tasks_handles_approve_reject_and_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enriched_csv = root / "tasks_enriched.csv"
            report_csv = root / "tasks_enriched_review.csv"
            decisions_csv = root / "task_review_decisions.csv"

            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "description": "Pay deposit.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Check portal.",
                        "required_documents": "Portal notice.",
                        "action_url": "https://example.edu/deposit",
                        "risk_level": "high",
                        "source_url": "https://example.edu/deposit",
                        "updated_at": "2026-07-01",
                        "task_code": "pay_deposit",
                        "evidence_count": "1",
                        "candidate_evidence_count": "3",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "1",
                        "evidence_types": "deadline,action_instruction",
                        "official_deadline_evidence": "Original deadline evidence.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Original action evidence.",
                        "official_action_urls": "https://example.edu/deposit",
                        "official_fee_evidence": "HK$5,000",
                        "evidence_ids": "e1;e2;e3",
                        "evidence_quality_status": "audited",
                        "evidence_quality_notes": "1 keep; 1 review/missing; 1 reject",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-07-01",
                    },
                    {
                        "task_id": "hkust-submit_conditions",
                        "school": "HKUST",
                        "stage": "offer_acceptance",
                        "task_name": "补交 conditional offer 材料",
                        "description": "Submit conditions.",
                        "trigger_condition": "Conditional offer.",
                        "deadline": "Check offer letter.",
                        "required_documents": "Transcript.",
                        "action_url": "https://example.edu/conditions",
                        "risk_level": "high",
                        "source_url": "https://example.edu/conditions",
                        "updated_at": "2026-07-01",
                        "task_code": "submit_conditions",
                        "evidence_count": "1",
                        "candidate_evidence_count": "2",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "0",
                        "rejected_evidence_count": "1",
                        "evidence_types": "required_document",
                        "official_deadline_evidence": "Submit before registration.",
                        "official_document_evidence": "Final transcript.",
                        "official_action_evidence": "Upload in portal.",
                        "official_action_urls": "https://example.edu/conditions",
                        "official_fee_evidence": "",
                        "evidence_ids": "e4;e5",
                        "evidence_quality_status": "audited",
                        "evidence_quality_notes": "1 keep; 1 reject",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-07-01",
                    },
                    {
                        "task_id": "hkust-apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "task_name": "申请学生签证",
                        "description": "Apply for visa.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Apply ASAP.",
                        "required_documents": "Visa form.",
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
                        "official_action_evidence": "",
                        "official_action_urls": "https://example.edu/visa",
                        "official_fee_evidence": "",
                        "evidence_ids": "e6;e7",
                        "evidence_quality_status": "audited",
                        "evidence_quality_notes": "2 keep",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-07-01",
                    },
                ],
                columns=TASK_ENRICHED_COLUMNS,
            ).to_csv(enriched_csv, index=False)

            report = build_task_review_report(enriched_csv)
            report.to_csv(report_csv, index=False)

            decisions = init_task_review_decisions(report_csv)
            decisions.loc[decisions["task_id"] == "hkust-pay_deposit", "reviewer_decision"] = "approve_with_edits"
            decisions.loc[decisions["task_id"] == "hkust-pay_deposit", "reviewed_deadline_evidence"] = "Reviewed deadline evidence."
            decisions.loc[decisions["task_id"] == "hkust-pay_deposit", "reviewed_action_evidence"] = "Reviewed action evidence."
            decisions.loc[decisions["task_id"] == "hkust-pay_deposit", "reviewer_notes"] = "Portal wording confirmed."
            decisions.loc[decisions["task_id"] == "hkust-pay_deposit", "reviewed_at"] = "2026-07-01"
            decisions.loc[decisions["task_id"] == "hkust-submit_conditions", "reviewer_decision"] = "reject"
            decisions.loc[decisions["task_id"] == "hkust-submit_conditions", "reviewer_notes"] = "General FAQ only."
            decisions.to_csv(decisions_csv, index=False)

            reviewed = build_reviewed_tasks(enriched_csv, report_csv, decisions_csv)

            self.assertEqual(list(reviewed.columns), TASK_REVIEWED_COLUMNS)

            approved = reviewed[reviewed["task_id"] == "hkust-pay_deposit"].iloc[0]
            self.assertEqual(approved["enrichment_status"], "review_approved_with_edits")
            self.assertEqual(approved["human_review_status"], "review_approved_with_edits")
            self.assertEqual(approved["official_deadline_evidence"], "Reviewed deadline evidence.")
            self.assertEqual(approved["official_action_evidence"], "Reviewed action evidence.")
            self.assertEqual(approved["evidence_quality_status"], "human_reviewed")

            rejected = reviewed[reviewed["task_id"] == "hkust-submit_conditions"].iloc[0]
            self.assertEqual(rejected["enrichment_status"], "review_rejected")
            self.assertEqual(rejected["human_review_status"], "review_rejected")
            self.assertEqual(rejected["official_deadline_evidence"], "")
            self.assertEqual(rejected["official_document_evidence"], "")
            self.assertEqual(int(rejected["evidence_count"]), 0)
            self.assertEqual(int(rejected["usable_evidence_count"]), 0)

            not_required = reviewed[reviewed["task_id"] == "hkust-apply_student_visa"].iloc[0]
            self.assertEqual(not_required["human_review_status"], "not_required")
            self.assertEqual(not_required["official_deadline_evidence"], "Apply as soon as possible.")

    def test_build_reviewed_tasks_marks_pending_review_without_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enriched_csv = root / "tasks_enriched.csv"
            report_csv = root / "tasks_enriched_review.csv"

            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "description": "Pay deposit.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Check portal.",
                        "required_documents": "Portal notice.",
                        "action_url": "https://example.edu/deposit",
                        "risk_level": "high",
                        "source_url": "https://example.edu/deposit",
                        "updated_at": "2026-07-01",
                        "task_code": "pay_deposit",
                        "evidence_count": "1",
                        "candidate_evidence_count": "1",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "0",
                        "rejected_evidence_count": "0",
                        "evidence_types": "deadline",
                        "official_deadline_evidence": "Original deadline evidence.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Original action evidence.",
                        "official_action_urls": "https://example.edu/deposit",
                        "official_fee_evidence": "HK$5,000",
                        "evidence_ids": "e1",
                        "evidence_quality_status": "audited",
                        "evidence_quality_notes": "1 keep",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-07-01",
                    }
                ],
                columns=TASK_ENRICHED_COLUMNS,
            ).to_csv(enriched_csv, index=False)

            report = build_task_review_report(enriched_csv)
            report.to_csv(report_csv, index=False)

            reviewed = build_reviewed_tasks(enriched_csv, report_csv, None)

            row = reviewed.iloc[0]
            self.assertEqual(row["human_review_status"], "review_pending")
            self.assertEqual(row["enrichment_status"], "review_pending")
            self.assertEqual(row["official_deadline_evidence"], "")
            self.assertEqual(row["evidence_quality_status"], "review_pending")

    def test_task_planner_can_use_reviewed_task_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed_csv = root / "tasks_reviewed.csv"
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "task_name": "REVIEWED_SENTINEL visa task",
                        "description": "Use reviewed task source.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Reviewed official portal guidance.",
                        "required_documents": "Reviewed passport copy.",
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
                        "official_deadline_evidence": "Reviewed deadline evidence.",
                        "official_document_evidence": "Reviewed passport copy.",
                        "official_action_evidence": "Upload in visa portal.",
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
                ],
                columns=TASK_REVIEWED_COLUMNS,
            ).to_csv(reviewed_csv, index=False)

            intent = route_intent("HKUST 还没申请签证，下一步做什么？")
            profile = StudentProfile(school="HKUST", completed_flags={"accepted_offer"})
            tasks = TaskPlanner(task_source_csv=reviewed_csv).plan(profile, intent=intent)

            self.assertEqual(tasks[0].task_name, "REVIEWED_SENTINEL visa task")
            self.assertEqual(tasks[0].official_deadline_evidence, "Reviewed deadline evidence.")

    def test_init_task_review_decisions_can_filter_pending_and_school(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_csv = root / "tasks_enriched_review.csv"
            decisions_csv = root / "task_review_decisions.csv"
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "task_code": "pay_deposit",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "candidate_evidence_count": "2",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "0",
                        "evidence_quality_status": "audited",
                        "enrichment_status": "evidence_found",
                        "official_deadline_evidence": "Deposit due before the deadline.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Pay online in the portal.",
                        "official_action_urls": "https://example.edu/deposit",
                        "official_fee_evidence": "HK$5,000",
                        "review_priority": "high",
                        "review_reason": "Needs human confirmation.",
                        "suggested_action": "Check portal and offer letter.",
                        "generated_at": "2026-07-01",
                    },
                    {
                        "task_id": "hku-pay_deposit",
                        "school": "HKU",
                        "task_code": "pay_deposit",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "candidate_evidence_count": "1",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "0",
                        "rejected_evidence_count": "0",
                        "evidence_quality_status": "audited",
                        "enrichment_status": "evidence_found",
                        "official_deadline_evidence": "Deadline.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Pay online.",
                        "official_action_urls": "https://example.edu/hku",
                        "official_fee_evidence": "",
                        "review_priority": "high",
                        "review_reason": "Needs human confirmation.",
                        "suggested_action": "Check portal.",
                        "generated_at": "2026-07-01",
                    },
                ],
                columns=TASK_REVIEW_COLUMNS,
            ).to_csv(report_csv, index=False)
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "task_code": "pay_deposit",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "review_priority": "high",
                        "review_reason": "Needs human confirmation.",
                        "reviewer_decision": "approve",
                        "reviewed_deadline_evidence": "Deposit due before the deadline.",
                        "reviewed_document_evidence": "",
                        "reviewed_action_evidence": "Pay online in the portal.",
                        "reviewed_action_urls": "https://example.edu/deposit",
                        "reviewed_fee_evidence": "HK$5,000",
                        "reviewer_notes": "",
                        "reviewed_at": "2026-07-01",
                    }
                ],
                columns=TASK_REVIEW_DECISION_COLUMNS,
            ).to_csv(decisions_csv, index=False)

            frame = init_task_review_decisions(
                report_csv,
                task_review_decisions_csv=decisions_csv,
                school_filter="HKU",
                pending_only=True,
            )

            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["school"], "HKU")

    def test_build_review_pending_summary_counts_pending_and_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_csv = root / "tasks_enriched_review.csv"
            decisions_csv = root / "task_review_decisions.csv"

            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "task_code": "pay_deposit",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "candidate_evidence_count": "2",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "0",
                        "evidence_quality_status": "audited",
                        "enrichment_status": "evidence_found",
                        "official_deadline_evidence": "Deposit due before the deadline.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Pay online in the portal.",
                        "official_action_urls": "https://example.edu/deposit",
                        "official_fee_evidence": "HK$5,000",
                        "review_priority": "high",
                        "review_reason": "Needs human confirmation.",
                        "suggested_action": "Check portal and offer letter.",
                        "generated_at": "2026-07-01",
                    },
                    {
                        "task_id": "hkust-submit_conditions",
                        "school": "HKUST",
                        "task_code": "submit_conditions",
                        "stage": "offer_acceptance",
                        "task_name": "补交 conditional offer 材料",
                        "candidate_evidence_count": "1",
                        "usable_evidence_count": "0",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "0",
                        "evidence_quality_status": "audited",
                        "enrichment_status": "evidence_needs_review",
                        "official_deadline_evidence": "",
                        "official_document_evidence": "",
                        "official_action_evidence": "",
                        "official_action_urls": "",
                        "official_fee_evidence": "",
                        "review_priority": "medium",
                        "review_reason": "Still needs review.",
                        "suggested_action": "Check evidence.",
                        "generated_at": "2026-07-01",
                    },
                ],
                columns=TASK_REVIEW_COLUMNS,
            ).to_csv(report_csv, index=False)

            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "task_code": "pay_deposit",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "review_priority": "high",
                        "review_reason": "Needs human confirmation.",
                        "reviewer_decision": "approve_with_edits",
                        "reviewed_deadline_evidence": "Deposit due before the deadline.",
                        "reviewed_document_evidence": "",
                        "reviewed_action_evidence": "Pay online in the portal.",
                        "reviewed_action_urls": "https://example.edu/deposit",
                        "reviewed_fee_evidence": "HK$5,000",
                        "reviewer_notes": "",
                        "reviewed_at": "2026-07-01",
                    }
                ],
                columns=TASK_REVIEW_DECISION_COLUMNS,
            ).to_csv(decisions_csv, index=False)

            summary = build_review_pending_summary(report_csv, decisions_csv, school_filter="HKUST")
            self.assertEqual(list(summary.columns), TASK_REVIEW_SUMMARY_COLUMNS)
            self.assertEqual(len(summary), 2)
            high = summary[summary["review_priority"] == "high"].iloc[0]
            self.assertEqual(int(high["approved_with_edits_count"]), 1)
            medium = summary[summary["review_priority"] == "medium"].iloc[0]
            self.assertEqual(int(medium["pending_count"]), 1)

    def test_build_review_pending_export_returns_only_pending_rows_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_csv = root / "tasks_enriched_review.csv"
            decisions_csv = root / "task_review_decisions.csv"

            pd.DataFrame(
                [
                    {
                        "task_id": "hku-submit_conditions",
                        "school": "HKU",
                        "task_code": "submit_conditions",
                        "stage": "offer_acceptance",
                        "task_name": "补交 conditional offer 材料",
                        "candidate_evidence_count": "1",
                        "usable_evidence_count": "0",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "0",
                        "evidence_quality_status": "audited",
                        "enrichment_status": "evidence_needs_review",
                        "official_deadline_evidence": "",
                        "official_document_evidence": "Final transcript.",
                        "official_action_evidence": "Upload in portal.",
                        "official_action_urls": "https://example.edu/hku",
                        "official_fee_evidence": "",
                        "review_priority": "medium",
                        "review_reason": "Need transcript confirmation.",
                        "suggested_action": "Check portal and email.",
                        "generated_at": "2026-07-01",
                    },
                    {
                        "task_id": "hkust-pay_deposit",
                        "school": "HKUST",
                        "task_code": "pay_deposit",
                        "stage": "offer_acceptance",
                        "task_name": "缴纳留位费",
                        "candidate_evidence_count": "2",
                        "usable_evidence_count": "1",
                        "review_evidence_count": "1",
                        "rejected_evidence_count": "0",
                        "evidence_quality_status": "audited",
                        "enrichment_status": "evidence_found",
                        "official_deadline_evidence": "Deposit due before the deadline.",
                        "official_document_evidence": "",
                        "official_action_evidence": "Pay online in the portal.",
                        "official_action_urls": "https://example.edu/deposit",
                        "official_fee_evidence": "HK$5,000",
                        "review_priority": "high",
                        "review_reason": "Needs human confirmation.",
                        "suggested_action": "Check portal and offer letter.",
                        "generated_at": "2026-07-01",
                    },
                ],
                columns=TASK_REVIEW_COLUMNS,
            ).to_csv(report_csv, index=False)

            pd.DataFrame(
                [
                    {
                        "task_id": "hku-submit_conditions",
                        "school": "HKU",
                        "task_code": "submit_conditions",
                        "stage": "offer_acceptance",
                        "task_name": "补交 conditional offer 材料",
                        "review_priority": "medium",
                        "review_reason": "Need transcript confirmation.",
                        "reviewer_decision": "approve",
                        "reviewed_deadline_evidence": "",
                        "reviewed_document_evidence": "Final transcript.",
                        "reviewed_action_evidence": "Upload in portal.",
                        "reviewed_action_urls": "https://example.edu/hku",
                        "reviewed_fee_evidence": "",
                        "reviewer_notes": "",
                        "reviewed_at": "2026-07-01",
                    }
                ],
                columns=TASK_REVIEW_DECISION_COLUMNS,
            ).to_csv(decisions_csv, index=False)

            frame = build_review_pending_export(report_csv, decisions_csv)
            self.assertEqual(list(frame.columns), TASK_REVIEW_PENDING_EXPORT_COLUMNS)
            self.assertEqual(len(frame), 1)
            row = frame.iloc[0]
            self.assertEqual(row["school"], "HKUST")
            self.assertEqual(row["review_priority"], "high")
            self.assertEqual(row["reviewer_decision"], "")


if __name__ == "__main__":
    unittest.main()
