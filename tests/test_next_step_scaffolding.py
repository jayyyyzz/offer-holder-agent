from pathlib import Path
import tempfile
import unittest

import pandas as pd

from agent.intent_router import route_intent
from agent.llm_prompt import build_grounded_prompt
from agent.rag_retriever import DocumentChunk, RetrievalResult
from agent.task_planner import StudentProfile, TaskPlanner, TASK_COLUMNS
from agent.user_state import load_user_profile, save_user_profile
from knowledge_base.enrich_tasks import TASK_ENRICHED_COLUMNS, build_enriched_tasks
from knowledge_base.extract_task_evidence import TASK_EVIDENCE_COLUMNS
from knowledge_base.vector_index import build_vector_index, search_vector_index, write_vector_index


class NextStepScaffoldingTests(unittest.TestCase):
    def test_build_enriched_tasks_joins_official_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_csv = root / "tasks.csv"
            evidence_csv = root / "task_evidence.csv"

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
                        "evidence_id": "e1",
                        "task_code": "apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "evidence_type": "deadline",
                        "evidence_text": "Submit the visa application as soon as possible.",
                        "normalized_value": "as soon as possible",
                        "source_question": "When should I apply?",
                        "source_url": "https://example.edu/visa-faq",
                        "confidence": "high",
                        "updated_at": "2026-06-30",
                    }
                ],
                columns=TASK_EVIDENCE_COLUMNS,
            ).to_csv(evidence_csv, index=False)

            frame = build_enriched_tasks(tasks_csv, evidence_csv)

            self.assertEqual(len(frame), 1)
            row = frame.iloc[0]
            self.assertEqual(row["enrichment_status"], "evidence_found")
            self.assertIn("as soon as possible", row["official_deadline_evidence"])

    def test_sparse_vector_index_can_search_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chunks_csv = root / "chunks.csv"
            index_csv = root / "vector_index.csv"

            pd.DataFrame(
                [
                    {
                        "chunk_id": "c1",
                        "school": "HKUST",
                        "page_type": "visa",
                        "stage": "visa",
                        "title": "Student Visa",
                        "source_url": "https://example.edu/visa",
                        "final_url": "https://example.edu/visa",
                        "raw_file": "raw.txt",
                        "chunk_index": "0",
                        "text": "Entry permit and student visa application guidance.",
                        "updated_at": "2026-06-30",
                    },
                    {
                        "chunk_id": "c2",
                        "school": "HKUST",
                        "page_type": "housing",
                        "stage": "housing",
                        "title": "Accommodation",
                        "source_url": "https://example.edu/housing",
                        "final_url": "https://example.edu/housing",
                        "raw_file": "raw2.txt",
                        "chunk_index": "0",
                        "text": "Residence application and hostel fees.",
                        "updated_at": "2026-06-30",
                    },
                ]
            ).to_csv(chunks_csv, index=False)

            frame = build_vector_index(chunks_csv)
            write_vector_index(frame, index_csv)
            results = search_vector_index("student visa entry permit", index_csv, school="HKUST")

            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0].chunk_id, "c1")

    def test_llm_prompt_includes_grounding_rules(self) -> None:
        intent = route_intent("HKUST 还没申请签证，下一步做什么？")
        profile = StudentProfile(school="HKUST", completed_flags={"accepted_offer"})
        tasks = TaskPlanner().plan(profile, intent=intent, limit=1)

        prompt = build_grounded_prompt(
            query=intent.raw_message,
            intent=intent,
            profile=profile,
            tasks=tasks,
            risks=[],
            evidence=[],
        )

        self.assertIn("只能基于下方", prompt)
        self.assertIn("Evidence ID", prompt)
        self.assertIn("HKUST", prompt)
        self.assertIn("Planned tasks", prompt)

    def test_llm_prompt_includes_evidence_ids_and_matched_terms(self) -> None:
        intent = route_intent("HKUST 还没申请签证，下一步做什么？")
        profile = StudentProfile(school="HKUST", completed_flags={"accepted_offer"})
        chunk = DocumentChunk(
            chunk_id="chunk-visa-1",
            school="HKUST",
            page_type="visa",
            stage="visa",
            title="Applying for Student Visa",
            source_url="https://example.edu/visa",
            final_url="https://example.edu/visa",
            raw_file="raw.txt",
            chunk_index=0,
            text="Students should apply for a student visa.",
            updated_at="2026-06-30",
        )

        prompt = build_grounded_prompt(
            query=intent.raw_message,
            intent=intent,
            profile=profile,
            tasks=[],
            risks=[],
            evidence=[RetrievalResult(chunk=chunk, score=8.0, matched_terms=("visa",))],
        )

        self.assertIn("evidence_id: Evidence 1", prompt)
        self.assertIn("chunk_id: chunk-visa-1", prompt)
        self.assertIn("matched_terms: visa", prompt)

    def test_task_planner_can_use_enriched_task_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enriched_csv = root / "tasks_enriched.csv"
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "task_name": "ENRICHED_SENTINEL visa task",
                        "description": "Use enriched task source.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Check official portal.",
                        "required_documents": "Check official portal.",
                        "action_url": "https://example.edu/visa",
                        "risk_level": "high",
                        "source_url": "https://example.edu/visa",
                        "updated_at": "2026-06-30",
                        "task_code": "apply_student_visa",
                        "evidence_count": "1",
                        "evidence_types": "deadline",
                        "official_deadline_evidence": "Apply as soon as possible.",
                        "official_document_evidence": "",
                        "official_action_evidence": "",
                        "official_action_urls": "",
                        "official_fee_evidence": "",
                        "evidence_ids": "e1",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-06-30",
                    }
                ],
                columns=TASK_ENRICHED_COLUMNS,
            ).to_csv(enriched_csv, index=False)

            intent = route_intent("HKUST 还没申请签证，下一步做什么？")
            profile = StudentProfile(school="HKUST", completed_flags={"accepted_offer"})
            tasks = TaskPlanner(task_source_csv=enriched_csv).plan(profile, intent=intent)

            self.assertEqual(tasks[0].task_name, "ENRICHED_SENTINEL visa task")
            self.assertEqual(tasks[0].official_deadline_evidence, "Apply as soon as possible.")

    def test_task_planner_filters_completed_enriched_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            enriched_csv = root / "tasks_enriched.csv"
            pd.DataFrame(
                [
                    {
                        "task_id": "hkust-apply_student_visa",
                        "school": "HKUST",
                        "stage": "visa",
                        "task_name": "Visa task",
                        "description": "Use enriched task source.",
                        "trigger_condition": "Offer accepted.",
                        "deadline": "Check official portal.",
                        "required_documents": "Check official portal.",
                        "action_url": "https://example.edu/visa",
                        "risk_level": "high",
                        "source_url": "https://example.edu/visa",
                        "updated_at": "2026-06-30",
                        "task_code": "apply_student_visa",
                        "evidence_count": "1",
                        "evidence_types": "deadline",
                        "official_deadline_evidence": "Apply as soon as possible.",
                        "official_document_evidence": "",
                        "official_action_evidence": "",
                        "official_action_urls": "",
                        "official_fee_evidence": "",
                        "evidence_ids": "e1",
                        "enrichment_status": "evidence_found",
                        "enriched_at": "2026-06-30",
                    }
                ],
                columns=TASK_ENRICHED_COLUMNS,
            ).to_csv(enriched_csv, index=False)

            profile = StudentProfile(
                school="HKUST",
                completed_flags={"accepted_offer", "visa_submitted"},
            )
            tasks = TaskPlanner(task_source_csv=enriched_csv).plan(profile, intent=None)

            self.assertEqual(tasks, [])

    def test_user_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "user_states.csv"
            profile = StudentProfile(
                school="CUHK",
                completed_flags={"accepted_offer", "paid_deposit"},
                has_conditional_offer=True,
            )

            save_user_profile("demo-user", profile, path=path, notes="test")
            loaded = load_user_profile("demo-user", path)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.school, "CUHK")
            self.assertIn("paid_deposit", loaded.completed_flags)
            self.assertTrue(loaded.has_conditional_offer)


if __name__ == "__main__":
    unittest.main()
