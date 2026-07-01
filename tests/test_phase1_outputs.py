from pathlib import Path
import tempfile
import unittest

import pandas as pd

from knowledge_base.phase1_outputs import (
    build_raw_page_index,
    build_schema_dictionary,
    write_phase1_outputs,
)


class Phase1OutputsTests(unittest.TestCase):
    def test_build_raw_page_index_reads_header_and_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            raw_file = raw_dir / "hkust__visa__sample.txt"
            raw_file.write_text(
                "\n".join(
                    [
                        "school: HKUST",
                        "page_type: visa",
                        "stage: visa",
                        "source_url: https://example.edu/visa",
                        "final_url: https://example.edu/visa",
                        "title: Student Visa",
                        "content_type: text/html",
                        "extraction_method: html_beautifulsoup",
                        "crawled_at: 2026-06-30T00:00:00+00:00",
                        "---",
                        "Mainland students should apply for an entry permit.",
                    ]
                ),
                encoding="utf-8",
            )

            frame = build_raw_page_index(raw_dir)

            self.assertEqual(len(frame), 1)
            row = frame.iloc[0]
            self.assertEqual(row["school"], "HKUST")
            self.assertEqual(row["page_type"], "visa")
            self.assertEqual(row["title"], "Student Visa")
            self.assertGreater(row["body_char_count"], 20)

    def test_write_phase1_outputs_creates_manifest_and_schema_dictionary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_dir = root / "data" / "raw_pages"
            metadata_dir = root / "data" / "metadata"
            raw_dir.mkdir(parents=True)
            metadata_dir.mkdir(parents=True)

            (root / "source_list.csv").write_text(
                "school,page_type,stage,url,priority,need_dynamic,remark\n"
                "HKUST,visa,visa,https://example.edu/visa,1,no,\n",
                encoding="utf-8",
            )
            (raw_dir / "hkust__visa__sample.txt").write_text(
                "\n".join(
                    [
                        "school: HKUST",
                        "page_type: visa",
                        "stage: visa",
                        "source_url: https://example.edu/visa",
                        "final_url: https://example.edu/visa",
                        "title: Student Visa",
                        "content_type: text/html",
                        "extraction_method: html_beautifulsoup",
                        "crawled_at: 2026-06-30T00:00:00+00:00",
                        "---",
                        "Visa application guidance.",
                    ]
                ),
                encoding="utf-8",
            )

            counts = write_phase1_outputs(
                root=root,
                raw_dir=raw_dir,
                raw_page_index=metadata_dir / "raw_page_index.csv",
                phase1_manifest=metadata_dir / "phase1_manifest.csv",
                schema_dictionary=metadata_dir / "schema_dictionary.csv",
            )

            self.assertEqual(counts["raw_page_index_rows"], 1)
            self.assertGreater(counts["schema_dictionary_rows"], 20)

            manifest = pd.read_csv(metadata_dir / "phase1_manifest.csv", dtype=str)
            raw_pages = manifest[manifest["artifact"] == "raw_pages"].iloc[0]
            raw_index = manifest[manifest["artifact"] == "raw_page_index"].iloc[0]
            self.assertEqual(raw_pages["file_count"], "1")
            self.assertEqual(raw_index["row_count"], "1")
            self.assertTrue((manifest["artifact"] == "task_evidence_quality_report").any())
            self.assertTrue((manifest["artifact"] == "tasks_enriched_review").any())
            self.assertTrue((manifest["artifact"] == "task_review_decisions").any())
            self.assertTrue((manifest["artifact"] == "tasks_reviewed").any())
            self.assertTrue((manifest["artifact"] == "user_task_states").any())

            schema = build_schema_dictionary()
            self.assertTrue(
                (
                    (schema["dataset"] == "tasks.csv")
                    & (schema["column"] == "task_id")
                ).any()
            )
            self.assertTrue(
                (
                    (schema["dataset"] == "task_evidence_quality_report.csv")
                    & (schema["column"] == "quality_decision")
                ).any()
            )
            self.assertTrue(
                (
                    (schema["dataset"] == "user_task_states.csv")
                    & (schema["column"] == "deadline_at")
                ).any()
            )
            self.assertTrue(
                (
                    (schema["dataset"] == "tasks_reviewed.csv")
                    & (schema["column"] == "human_review_status")
                ).any()
            )
            self.assertTrue(
                (
                    (schema["dataset"] == "task_review_decisions.csv")
                    & (schema["column"] == "reviewer_decision")
                ).any()
            )


if __name__ == "__main__":
    unittest.main()
