from pathlib import Path
import tempfile
import unittest

import pandas as pd

from crawler.summarize_crawl import build_crawl_summary
from knowledge_base.audit_data_quality import assess_row, build_quality_report


SOURCE_HEADER = "school,page_type,stage,url,priority,need_dynamic,remark\n"
LOG_HEADER = (
    "school,page_type,stage,source_url,final_url,priority,need_dynamic,status,"
    "http_status,title,crawled_at,raw_file,content_type,char_count,elapsed_ms,error\n"
)


class CrawlSummaryTests(unittest.TestCase):
    def test_uses_latest_log_record_for_current_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_list = root / "source_list.csv"
            log_path = root / "crawl_log.csv"
            source_list.write_text(
                SOURCE_HEADER
                + "CityU,faq,general,https://example.edu/faq-new,2,yes,\n",
                encoding="utf-8",
            )
            log_path.write_text(
                LOG_HEADER
                + "CityU,faq,general,https://example.edu/faq-new,https://example.edu/404,2,yes,success_dynamic,200,Page Not Found,2026-01-01T00:00:00+00:00,data/raw_pages/old.txt,text/html,431,1,\n"
                + "CityU,faq,general,https://example.edu/faq-new,https://example.edu/faq-new,2,yes,success_dynamic,200,FAQ,2026-01-02T00:00:00+00:00,data/raw_pages/.gitkeep,text/html,1200,1,\n",
                encoding="utf-8",
            )

            frame = build_crawl_summary(source_list, log_path)
            self.assertEqual(len(frame), 1)
            row = frame.iloc[0]
            self.assertEqual(row["latest_title"], "FAQ")
            self.assertEqual(row["attempt_count"], 2)
            self.assertEqual(row["needs_attention"], "no")

    def test_keeps_usable_success_when_latest_attempt_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_list = root / "source_list.csv"
            log_path = root / "crawl_log.csv"
            source_list.write_text(
                SOURCE_HEADER
                + "HKUST,faq,general,https://example.edu/faq,2,no,\n",
                encoding="utf-8",
            )
            log_path.write_text(
                LOG_HEADER
                + "HKUST,faq,general,https://example.edu/faq,https://example.edu/faq,2,no,success,200,FAQ,2026-01-01T00:00:00+00:00,data/raw_pages/.gitkeep,text/html,385,1,\n"
                + "HKUST,faq,general,https://example.edu/faq,,2,no,request_error,468,,2026-01-02T00:00:00+00:00,data/raw_pages/hkust__faq.txt,text/html,0,1,HTTPError\n",
                encoding="utf-8",
            )

            frame = build_crawl_summary(source_list, log_path)
            row = frame.iloc[0]
            self.assertEqual(row["latest_status"], "request_error")
            self.assertEqual(row["usable_status"], "success")
            self.assertEqual(row["usable_char_count"], 385)
            self.assertEqual(
                row["attention_reason"], "latest_attempt_failed_previous_success_available"
            )


class DataQualityTests(unittest.TestCase):
    def test_assess_row_marks_missing_chunks_as_weak(self) -> None:
        level, notes = assess_row(
            {
                "latest_status": "success",
                "latest_char_count": 1200,
                "raw_file_exists": "yes",
                "chunk_count": 0,
                "task_count": 1,
                "page_type": "visa",
            }
        )
        self.assertEqual(level, "weak")
        self.assertIn("no retrieval chunks generated", notes)

    def test_build_quality_report_counts_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            summary_path = root / "crawl_summary.csv"
            chunks_path = root / "chunks.csv"
            faq_path = root / "faq.csv"
            tasks_path = root / "tasks.csv"

            pd.DataFrame(
                [
                    {
                        "school": "HKU",
                        "page_type": "visa",
                        "stage": "visa",
                        "source_url": "https://example.edu/visa",
                        "latest_status": "success",
                        "latest_char_count": "1200",
                        "raw_file_exists": "yes",
                        "latest_raw_file": "data/raw_pages/hku__visa.txt",
                    }
                ]
            ).to_csv(summary_path, index=False)
            pd.DataFrame(
                [
                    {
                        "chunk_id": "c1",
                        "raw_file": "data/raw_pages/hku__visa.txt",
                        "source_url": "https://example.edu/visa",
                        "school": "HKU",
                        "stage": "visa",
                    }
                ]
            ).to_csv(chunks_path, index=False)
            pd.DataFrame([], columns=["source_url", "school", "stage"]).to_csv(
                faq_path, index=False
            )
            pd.DataFrame([{"school": "HKU", "stage": "visa"}]).to_csv(tasks_path, index=False)

            report = build_quality_report(
                summary_path=summary_path,
                chunks_csv=chunks_path,
                faq_csv=faq_path,
                tasks_csv=tasks_path,
            )
            self.assertEqual(report.iloc[0]["chunk_count"], 1)
            self.assertEqual(report.iloc[0]["coverage_level"], "ok")


if __name__ == "__main__":
    unittest.main()
