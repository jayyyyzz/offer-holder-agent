from pathlib import Path
import tempfile
import unittest

from crawler.dynamic_crawl_pages import (
    detect_visible_block,
    normalize_visible_text,
    select_sources,
)


class DynamicCrawlerTests(unittest.TestCase):
    def test_detects_visible_block_page(self) -> None:
        marker = detect_visible_block("Please enable JavaScript and cookies to continue")
        self.assertEqual(marker, "enable javascript and cookies to continue")

    def test_normalizes_visible_text(self) -> None:
        text = normalize_visible_text(" A   line \n\n A   line \n B\tline ")
        self.assertEqual(text, "A line\nB line")

    def test_selects_only_dynamic_sources_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source_list = Path(tmp) / "source_list.csv"
            source_list.write_text(
                "\n".join(
                    [
                        "school,page_type,stage,url,priority,need_dynamic,remark",
                        "CityU,visa,visa,https://example.edu/visa,1,yes,",
                        "HKU,visa,visa,https://example.edu/hku-visa,1,no,",
                    ]
                ),
                encoding="utf-8",
            )
            frame = select_sources(source_list)
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["school"], "CityU")


if __name__ == "__main__":
    unittest.main()
