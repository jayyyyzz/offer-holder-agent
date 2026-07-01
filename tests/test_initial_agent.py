from pathlib import Path
import tempfile
import unittest

from agent.intent_router import infer_completed_flags, route_intent
from agent.rag_retriever import LocalRagRetriever, build_chunks_from_cleaned_faq
from agent.response_generator import format_agent_response
from agent.risk_checker import RiskChecker
from agent.task_planner import StudentProfile, TaskPlanner


class IntentRouterTests(unittest.TestCase):
    def test_routes_chinese_visa_task_question(self) -> None:
        result = route_intent("HKUST 已经交了留位费，还没申请签证，下一步做什么？")
        self.assertEqual(result.school, "HKUST")
        self.assertEqual(result.stage, "visa")
        self.assertEqual(result.intent, "task_plan")
        self.assertIn("visa", result.page_types)

    def test_infers_completed_flags(self) -> None:
        flags = infer_completed_flags("我已经接受offer，也交了留位费")
        self.assertIn("accepted_offer", flags)
        self.assertIn("paid_deposit", flags)

    def test_does_not_treat_question_as_completed_registration(self) -> None:
        flags = infer_completed_flags("HKU 线上注册怎么完成？如果不做会有什么影响？")
        self.assertNotIn("registered", flags)


class RetrieverTests(unittest.TestCase):
    def test_retrieves_chinese_query_against_english_official_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            raw_page = raw_dir / "hkust__visa__sample.txt"
            raw_page.write_text(
                "\n".join(
                    [
                        "school: HKUST",
                        "page_type: visa",
                        "stage: visa",
                        "source_url: https://example.edu/visa",
                        "final_url: https://example.edu/visa",
                        "title: Applying for Student Visa",
                        "crawled_at: 2026-06-29T00:00:00+00:00",
                        "---",
                        "Most non-local students are required to obtain a student visa or entry permit.",
                    ]
                ),
                encoding="utf-8",
            )
            retriever = LocalRagRetriever(raw_dir=raw_dir, chunks_csv=raw_dir / "chunks.csv")
            results = retriever.search("内地学生签证怎么办？", school="HKUST", page_types=["visa"])
            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0].chunk.school, "HKUST")
            self.assertIn("visa", results[0].matched_terms)

    def test_does_not_return_metadata_only_match_as_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            raw_page = raw_dir / "hkust__visa__sample.txt"
            raw_page.write_text(
                "\n".join(
                    [
                        "school: HKUST",
                        "page_type: visa",
                        "stage: visa",
                        "source_url: https://example.edu/visa",
                        "final_url: https://example.edu/visa",
                        "title: Welcome",
                        "crawled_at: 2026-06-29T00:00:00+00:00",
                        "---",
                        "This page only contains a campus map and general contact information.",
                    ]
                ),
                encoding="utf-8",
            )
            retriever = LocalRagRetriever(raw_dir=raw_dir, chunks_csv=raw_dir / "chunks.csv")
            results = retriever.search(
                "student visa",
                school="HKUST",
                page_types=["visa"],
                stage="visa",
            )
            self.assertEqual(results, [])

    def test_stopword_only_query_does_not_return_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            raw_page = raw_dir / "hku__faq__sample.txt"
            raw_page.write_text(
                "\n".join(
                    [
                        "school: HKU",
                        "page_type: faq",
                        "stage: general",
                        "source_url: https://example.edu/faq",
                        "final_url: https://example.edu/faq",
                        "title: FAQ",
                        "crawled_at: 2026-06-29T00:00:00+00:00",
                        "---",
                        "Students should follow official registration guidance.",
                    ]
                ),
                encoding="utf-8",
            )
            retriever = LocalRagRetriever(raw_dir=raw_dir, chunks_csv=raw_dir / "chunks.csv")
            self.assertEqual(retriever.search("when is the for", school="HKU"), [])

    def test_retrieves_chinese_transcript_query_against_english_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            raw_page = raw_dir / "hkust__documents__sample.txt"
            raw_page.write_text(
                "\n".join(
                    [
                        "school: HKUST",
                        "page_type: offer_holder",
                        "stage: offer_acceptance",
                        "source_url: https://example.edu/documents",
                        "final_url: https://example.edu/documents",
                        "title: Submitting Official Documents",
                        "crawled_at: 2026-06-29T00:00:00+00:00",
                        "---",
                        "Admitted students should submit official transcript and degree certificate.",
                    ]
                ),
                encoding="utf-8",
            )
            retriever = LocalRagRetriever(raw_dir=raw_dir, chunks_csv=raw_dir / "chunks.csv")
            results = retriever.search("成绩单和学位证什么时候交？", school="HKUST")
            self.assertGreaterEqual(len(results), 1)
            self.assertIn("transcript", results[0].matched_terms)

    def test_builds_structured_faq_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            faq_path = Path(tmp) / "faq_cleaned.csv"
            faq_path.write_text(
                "\n".join(
                    [
                        "question,answer,school,stage,category,risk_level,source_url,updated_at",
                        "How can I apply for student visa?,Submit the visa documents through the official portal.,HKUST,visa,visa,high,https://example.edu/visa,2026-06-29",
                    ]
                ),
                encoding="utf-8",
            )
            chunks = build_chunks_from_cleaned_faq(faq_path)
            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].page_type, "faq_cleaned")
            self.assertIn("Question:", chunks[0].text)


class PlanningAndResponseTests(unittest.TestCase):
    def test_planner_prioritizes_visa_when_deposit_paid(self) -> None:
        planner = TaskPlanner()
        intent = route_intent("HKUST 已经交了留位费，还没申请签证，下一步做什么？")
        profile = StudentProfile(
            school="HKUST",
            completed_flags={"accepted_offer", "paid_deposit"},
        )
        tasks = planner.plan(profile, intent=intent)
        self.assertEqual(tasks[0].stage, "visa")

    def test_response_contains_task_and_risk_sections(self) -> None:
        planner = TaskPlanner()
        intent = route_intent("HKUST 还没申请签证，下一步做什么？")
        profile = StudentProfile(school="HKUST", completed_flags={"accepted_offer"})
        tasks = planner.plan(profile, intent=intent, limit=3)
        risks = RiskChecker().check(profile, tasks=tasks, evidence=[], intent=intent)
        response = format_agent_response(
            query=intent.raw_message,
            intent=intent,
            profile=profile,
            tasks=tasks,
            risks=risks,
            evidence=[],
        )
        self.assertIn("下一步优先任务", response)
        self.assertIn("风险提醒", response)


if __name__ == "__main__":
    unittest.main()
