import unittest

from knowledge_base.extract_faq import (
    extract_pairs_from_text,
    infer_category,
    infer_risk_level,
    is_question_line,
    is_probably_section_heading,
)


class FaqExtractionTests(unittest.TestCase):
    def test_detects_english_and_chinese_questions(self) -> None:
        self.assertTrue(is_question_line("Who needs a student visa?"))
        self.assertTrue(is_question_line("如何申请学生签证？"))
        self.assertFalse(is_question_line("Student Visa Application"))
        self.assertFalse(is_question_line("If mailing address is correct, please re-check later."))

    def test_extracts_question_answer_pairs(self) -> None:
        text = """
        Who needs a student visa?
        Most non-local students are required to obtain a student visa or entry permit.
        Please apply via the university.
        How can I apply for accommodation?
        Check the hall application period and submit the form online.
        """
        pairs = extract_pairs_from_text(text, min_answer_chars=20)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][0], "Who needs a student visa?")
        self.assertIn("entry permit", pairs[0][1])

    def test_extract_skips_section_headings_inside_answers(self) -> None:
        text = """
        How can I pay the deposit for accepting the offer?
        Deposit payment instructions will be available after you accept the offer.
        Supporting Documents
        I have accepted the offer. What supporting documents should I submit and how?
        Check the Document Checklist after you have accepted the offer online.
        """
        pairs = extract_pairs_from_text(text, min_answer_chars=20)
        self.assertEqual(len(pairs), 2)
        self.assertNotIn("Supporting Documents", pairs[0][1])

    def test_detects_common_section_headings(self) -> None:
        self.assertTrue(is_probably_section_heading("Student Visa/ Entry Permit"))
        self.assertTrue(is_probably_section_heading("Application Procedures"))

    def test_infers_category_and_risk(self) -> None:
        category = infer_category("Who needs a student visa?", "Apply for an entry permit.")
        self.assertEqual(category, "visa")
        self.assertEqual(
            infer_risk_level("Who needs a student visa?", "Apply for an entry permit.", category),
            "high",
        )


if __name__ == "__main__":
    unittest.main()
