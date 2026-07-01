import unittest

from crawler.import_manual_page import normalize_manual_text


class ImportManualPageTests(unittest.TestCase):
    def test_normalize_manual_text_dedupes_lines_and_fixes_mojibake(self) -> None:
        text = (
            "I have submitted my documents, what\u9225\u6a9a next?\n\n\n"
            "Answer\nAnswer\n\u9286\u3000 Program"
        )

        normalized = normalize_manual_text(text)

        self.assertIn("what’s next?", normalized)
        self.assertIn("Program", normalized)
        self.assertEqual(normalized.count("Answer"), 1)


if __name__ == "__main__":
    unittest.main()
