from pathlib import Path
import tempfile
import unittest

import pandas as pd

from knowledge_base.extract_faq import FAQ_COLUMNS
from knowledge_base.extract_task_evidence import extract_task_evidence


def faq_row(
    question: str,
    answer: str,
    *,
    school: str = "HKUST",
    category: str = "visa",
) -> dict[str, str]:
    return {
        "question": question,
        "answer": answer,
        "school": school,
        "stage": category,
        "category": category,
        "risk_level": "high",
        "source_url": "https://example.edu.hk/faq",
        "updated_at": "2026-06-30",
    }


class ExtractTaskEvidenceTests(unittest.TestCase):
    def test_extracts_visa_deadline_and_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "faq.csv"
            pd.DataFrame(
                [
                    faq_row(
                        "When should I apply for the student visa/ entry permit?",
                        "Application period: Fall admission: March or soonest possible. "
                        "Please refer to the Checklist of Documents Required for Visa/ Entry Permit Application.",
                    )
                ],
                columns=FAQ_COLUMNS,
            ).to_csv(path, index=False)

            evidence = extract_task_evidence(path)

        self.assertTrue(any(item.task_code == "apply_student_visa" for item in evidence))
        self.assertTrue(any(item.evidence_type == "deadline" for item in evidence))
        self.assertTrue(any(item.evidence_type == "required_document" for item in evidence))

    def test_extracts_action_url_from_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "faq.csv"
            pd.DataFrame(
                [
                    faq_row(
                        "What documents are needed for the student visa application?",
                        "View the document list at Visa Application "
                        "(https://www.gs.cuhk.edu.hk/registration/visa-application)",
                        school="CUHK",
                    )
                ],
                columns=FAQ_COLUMNS,
            ).to_csv(path, index=False)

            evidence = extract_task_evidence(path)

        urls = [item.normalized_value for item in evidence if item.evidence_type == "action_url"]
        self.assertIn("https://www.gs.cuhk.edu.hk/registration/visa-application", urls)

    def test_skips_application_fee_when_not_offer_holder_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "faq.csv"
            pd.DataFrame(
                [
                    faq_row(
                        "How much is the online application fee?",
                        "The online application fee is HK$600 and can be paid online.",
                        category="payment",
                    )
                ],
                columns=FAQ_COLUMNS,
            ).to_csv(path, index=False)

            evidence = extract_task_evidence(path)

        self.assertEqual(evidence, [])


if __name__ == "__main__":
    unittest.main()
