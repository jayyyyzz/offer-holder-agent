import unittest

import pandas as pd

from crawler.block_detection import validate_cached_raw_page
from crawler.crawl_pages import (
    SOURCE_COLUMNS,
    clean_html,
    detect_soft_block,
    is_pdf_content,
    raw_filename,
    validate_source_list,
)


class CleaningTests(unittest.TestCase):
    def test_removes_navigation_and_scripts(self) -> None:
        html = """
        <html><head><title>Visa Guide</title><script>bad()</script></head>
        <body><header>Header menu</header><main>
        <h1>Student visa</h1><p>Submit the application form.</p>
        </main><footer>Footer links</footer></body></html>
        """
        title, text = clean_html(html)
        self.assertEqual(title, "Visa Guide")
        self.assertIn("Submit the application form.", text)
        self.assertNotIn("Header menu", text)
        self.assertNotIn("Footer links", text)
        self.assertNotIn("bad()", text)

    def test_detects_incapsula(self) -> None:
        html = '<script src="/_Incapsula_Resource?token=x"></script>'
        self.assertEqual(detect_soft_block(html), "_incapsula_resource")

    def test_filename_is_stable(self) -> None:
        first = raw_filename("HKU", "offer_holder", "https://example.edu/a")
        second = raw_filename("HKU", "offer_holder", "https://example.edu/a")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("hku__offer_holder__"))

    def test_detects_pdf_content(self) -> None:
        self.assertTrue(is_pdf_content("application/pdf", "https://example.edu/guide"))
        self.assertTrue(is_pdf_content("application/octet-stream", "https://example.edu/guide.pdf"))
        self.assertFalse(is_pdf_content("text/html", "https://example.edu/guide"))

    def test_validates_existing_raw_page_before_skipping(self) -> None:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw.txt"
            row = {
                "school": "HKUST",
                "page_type": "visa",
                "stage": "visa",
                "url": "https://example.edu/visa",
            }
            path.write_text(
                "\n".join(
                    [
                        "school: HKUST",
                        "page_type: visa",
                        "stage: visa",
                        "source_url: https://example.edu/visa",
                        "final_url: https://example.edu/visa",
                        "title: Visa",
                        "content_type: text/html",
                        "---",
                        "Students should apply for a student visa entry permit. " * 4,
                    ]
                ),
                encoding="utf-8",
            )

            result = validate_cached_raw_page(path, row)

            self.assertTrue(result["usable"])
            self.assertEqual(result["status"], "skipped_exists")
            self.assertGreater(result["char_count"], 100)

    def test_flags_soft_blocked_cached_raw_page(self) -> None:
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw.txt"
            row = {
                "school": "HKUST",
                "page_type": "visa",
                "stage": "visa",
                "url": "https://example.edu/visa",
            }
            path.write_text(
                "school: HKUST\n"
                "page_type: visa\n"
                "stage: visa\n"
                "source_url: https://example.edu/visa\n"
                "---\n"
                "Just a moment... enable JavaScript and cookies to continue",
                encoding="utf-8",
            )

            result = validate_cached_raw_page(path, row)

            self.assertFalse(result["usable"])
            self.assertEqual(result["status"], "stale_cached_soft_blocked")


class SourceListTests(unittest.TestCase):
    def test_validates_schema(self) -> None:
        frame = pd.DataFrame(
            [
                {
                    "school": "HKU",
                    "page_type": "visa",
                    "stage": "visa",
                    "url": "https://example.edu/visa",
                    "priority": "1",
                    "need_dynamic": "no",
                    "remark": "",
                }
            ],
            columns=SOURCE_COLUMNS,
        )
        result = validate_source_list(frame)
        self.assertEqual(result.iloc[0]["priority"], 1)

    def test_rejects_missing_column(self) -> None:
        with self.assertRaises(ValueError):
            validate_source_list(pd.DataFrame([{"school": "HKU"}]))


if __name__ == "__main__":
    unittest.main()
