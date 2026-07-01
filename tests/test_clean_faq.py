from pathlib import Path
import tempfile
import unittest

import pandas as pd

from knowledge_base.clean_faq import (
    clean_faq_candidates,
    clean_question_text,
    score_faq_row,
)
from knowledge_base.extract_faq import FAQ_COLUMNS


def faq_row(question: str, answer: str, school: str = "HKU") -> dict[str, str]:
    return {
        "question": question,
        "answer": answer,
        "school": school,
        "stage": "general",
        "category": "general",
        "risk_level": "low",
        "source_url": "https://example.edu/faq",
        "updated_at": "2026-06-29",
    }


class CleanFaqTests(unittest.TestCase):
    def test_cleans_common_question_prefixes(self) -> None:
        self.assertEqual(
            clean_question_text("A01. When is the application deadline?"),
            "When is the application deadline?",
        )
        self.assertEqual(clean_question_text("Q3: How can I apply?"), "How can I apply?")
        self.assertEqual(
            clean_question_text("Why HKBU (https://example.edu.hk/why-hkbu)"),
            "Why HKBU",
        )

    def test_rejects_fragment_question(self) -> None:
        result = score_faq_row(
            faq_row(
                "where bachelor's degree holders may apply for the PhD stream",
                "Consult the relevant programme information before submitting an application.",
            )
        )
        self.assertEqual(result.decision, "reject")
        self.assertIn("question_fragment", result.quality_notes)

    def test_keeps_valid_question(self) -> None:
        result = score_faq_row(
            faq_row(
                "How can I apply for student visa?",
                "Applicants should follow the university instructions and submit the required visa documents through the official application channel.",
            )
        )
        self.assertEqual(result.decision, "keep")
        self.assertGreaterEqual(result.quality_score, 65)

    def test_rejects_broad_navigation_question(self) -> None:
        result = score_faq_row(
            faq_row(
                "Why HKBU (https://example.edu.hk/why-hkbu)",
                "Teaching and Research Fields of Studies Alumni Students Sharing Graduate Attributes Admission Requirements International Students",
                school="HKBU",
            )
        )
        self.assertEqual(result.decision, "reject")
        self.assertIn("broad_navigation_question", result.quality_notes)

    def test_deduplicates_questions_for_same_school(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "faq.csv"
            pd.DataFrame(
                [
                    faq_row("Q1: How can I apply?", "Submit the online application form with required documents."),
                    faq_row("How can I apply?", "Submit the online application form with required documents."),
                ],
                columns=FAQ_COLUMNS,
            ).to_csv(path, index=False)
            cleaned, report = clean_faq_candidates(path)
            self.assertEqual(len(cleaned), 1)
            self.assertEqual(len(report), 2)
            self.assertIn("duplicate_question_for_school", report[1]["quality_notes"])


if __name__ == "__main__":
    unittest.main()
