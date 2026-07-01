from pathlib import Path
import tempfile
import unittest

from app.runtime_data import ensure_runtime_data_seeded


class RuntimeDataTests(unittest.TestCase):
    def test_ensure_runtime_data_seeded_copies_missing_seed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed_root = root / "seed"
            runtime_root = root / "runtime"
            (seed_root / "cleaned").mkdir(parents=True, exist_ok=True)
            (seed_root / "metadata").mkdir(parents=True, exist_ok=True)
            (seed_root / "cleaned" / "tasks_reviewed.csv").write_text("task_id\nhkust-apply_student_visa\n", encoding="utf-8")
            (seed_root / "metadata" / "crawl_summary.csv").write_text("school\nHKUST\n", encoding="utf-8")

            with self.subTest("first_bootstrap"):
                with unittest.mock.patch("app.runtime_data.resolve_seed_data_root", return_value=seed_root), unittest.mock.patch(
                    "app.runtime_data.resolve_runtime_data_root",
                    return_value=runtime_root,
                ):
                    copied = ensure_runtime_data_seeded()

                self.assertTrue(copied)
                self.assertTrue((runtime_root / "cleaned" / "tasks_reviewed.csv").exists())
                self.assertTrue((runtime_root / "metadata" / "crawl_summary.csv").exists())
                self.assertTrue((runtime_root / "metadata" / "openai_runs").exists())


if __name__ == "__main__":
    unittest.main()
