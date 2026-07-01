"""Audit data coverage across sources, raw pages, chunks, FAQ, and tasks."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

from agent.rag_retriever import DEFAULT_CHUNKS_CSV
from agent.task_planner import DEFAULT_TASKS_CSV
from crawler.summarize_crawl import DEFAULT_SUMMARY_PATH, OK_STATUSES, build_crawl_summary
from knowledge_base.extract_faq import DEFAULT_FAQ_CSV


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_QUALITY_REPORT = ROOT_DIR / "data" / "metadata" / "data_quality_report.csv"


QUALITY_COLUMNS = [
    "school",
    "page_type",
    "stage",
    "source_url",
    "latest_status",
    "usable_status",
    "latest_char_count",
    "usable_char_count",
    "raw_file_exists",
    "chunk_count",
    "faq_count",
    "task_count",
    "coverage_level",
    "needs_attention",
    "notes",
]


def build_quality_report(
    *,
    summary_path: Path | str = DEFAULT_SUMMARY_PATH,
    chunks_csv: Path | str = DEFAULT_CHUNKS_CSV,
    faq_csv: Path | str = DEFAULT_FAQ_CSV,
    tasks_csv: Path | str = DEFAULT_TASKS_CSV,
) -> pd.DataFrame:
    summary = load_or_build_summary(Path(summary_path))
    chunks = read_optional_csv(Path(chunks_csv))
    faq = read_optional_csv(Path(faq_csv))
    tasks = read_optional_csv(Path(tasks_csv))

    chunk_counts = count_by(chunks, ["raw_file"])
    faq_by_source = count_by(faq, ["source_url"])
    faq_by_school_stage = count_by(faq, ["school", "stage"])
    task_by_school_stage = count_by(tasks, ["school", "stage"])

    rows: list[dict[str, object]] = []
    for row in summary.to_dict(orient="records"):
        raw_file = str(row.get("usable_raw_file") or row.get("latest_raw_file", ""))
        source_url = str(row.get("source_url", ""))
        school = str(row.get("school", ""))
        stage = str(row.get("stage", ""))

        faq_count = faq_by_source.get((source_url,), 0)
        if faq_count == 0:
            faq_count = faq_by_school_stage.get((school, stage), 0)

        report_row = {
            "school": school,
            "page_type": row.get("page_type", ""),
            "stage": stage,
            "source_url": source_url,
            "latest_status": row.get("latest_status", ""),
            "usable_status": row.get("usable_status", "") or row.get("latest_status", ""),
            "latest_char_count": _to_int(row.get("latest_char_count", 0)),
            "usable_char_count": _to_int(row.get("usable_char_count") or row.get("latest_char_count", 0)),
            "raw_file_exists": row.get("raw_file_exists", ""),
            "chunk_count": chunk_counts.get((raw_file,), 0),
            "faq_count": faq_count,
            "task_count": task_by_school_stage.get((school, stage), 0),
            "coverage_level": "",
            "needs_attention": "",
            "notes": "",
        }
        coverage_level, notes = assess_row(report_row)
        report_row["coverage_level"] = coverage_level
        report_row["needs_attention"] = "yes" if coverage_level in {"blocker", "weak"} else "no"
        report_row["notes"] = "; ".join(notes)
        rows.append(report_row)

    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def load_or_build_summary(summary_path: Path) -> pd.DataFrame:
    if summary_path.exists() and summary_path.stat().st_size > 0:
        return pd.read_csv(summary_path, dtype=str, keep_default_na=False)
    return build_crawl_summary()


def assess_row(row: dict[str, object]) -> tuple[str, list[str]]:
    notes: list[str] = []
    latest_status = str(row.get("latest_status", ""))
    status = str(row.get("usable_status") or latest_status)
    char_count = _to_int(row.get("usable_char_count") or row.get("latest_char_count", 0))
    chunk_count = _to_int(row.get("chunk_count", 0))
    raw_exists = row.get("raw_file_exists") == "yes"

    if status not in OK_STATUSES:
        notes.append(f"latest crawl status is {status}")
        return "blocker", notes
    if latest_status and latest_status not in OK_STATUSES:
        notes.append(f"latest crawl attempt is {latest_status}; using previous successful raw text")
    if not raw_exists:
        notes.append("raw text file is missing")
        return "blocker", notes
    if char_count < 100:
        notes.append("raw text is too short")
        return "blocker", notes
    if chunk_count == 0:
        notes.append("no retrieval chunks generated")
        return "weak", notes
    if char_count < 800:
        notes.append("source text is short; may need manual verification")
        return "weak", notes
    if (
        str(row.get("page_type", "")) != "faq"
        and str(row.get("stage", "")) != "general"
        and _to_int(row.get("task_count", 0)) == 0
    ):
        notes.append("no task template mapped to this school/stage")
        return "weak", notes
    if str(row.get("page_type", "")) == "faq" and _to_int(row.get("faq_count", 0)) == 0:
        notes.append("FAQ page has no extracted FAQ candidates")
        return "weak", notes
    return "ok", notes


def read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def count_by(frame: pd.DataFrame, columns: list[str]) -> dict[tuple[str, ...], int]:
    if frame.empty or any(column not in frame.columns for column in columns):
        return {}
    grouped = frame.groupby(columns, dropna=False).size()
    result: dict[tuple[str, ...], int] = {}
    for key, count in grouped.items():
        if not isinstance(key, tuple):
            key = (key,)
        result[tuple(str(item) for item in key)] = int(count)
    return result


def write_quality_report(
    frame: pd.DataFrame,
    output: Path | str = DEFAULT_QUALITY_REPORT,
) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, encoding="utf-8-sig")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit local data coverage for the offer agent.")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_CSV)
    parser.add_argument("--faq", type=Path, default=DEFAULT_FAQ_CSV)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_QUALITY_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = build_quality_report(
        summary_path=args.summary,
        chunks_csv=args.chunks,
        faq_csv=args.faq,
        tasks_csv=args.tasks,
    )
    write_quality_report(frame, args.output)
    print(f"已生成 data quality report：{len(frame)} 条 -> {args.output}")
    print(frame["coverage_level"].value_counts(dropna=False).to_string())
    attention_count = int((frame["needs_attention"] == "yes").sum())
    print(f"needs_attention: {attention_count}")
    return 0


def _to_int(value: object) -> int:
    try:
        if value == "":
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
