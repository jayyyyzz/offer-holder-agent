"""Build a latest-status summary from the append-only crawl log."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

from crawler.crawl_pages import (
    DEFAULT_LOG_PATH,
    DEFAULT_SOURCE_LIST,
    LOG_COLUMNS,
    ROOT_DIR,
    validate_source_list,
)


DEFAULT_SUMMARY_PATH = ROOT_DIR / "data" / "metadata" / "crawl_summary.csv"
OK_STATUSES = {"success", "success_dynamic", "skipped_exists"}


SUMMARY_COLUMNS = [
    "school",
    "page_type",
    "stage",
    "source_url",
    "priority",
    "need_dynamic",
    "latest_status",
    "latest_http_status",
    "latest_title",
    "latest_final_url",
    "latest_crawled_at",
    "latest_raw_file",
    "latest_content_type",
    "latest_char_count",
    "usable_status",
    "usable_title",
    "usable_final_url",
    "usable_crawled_at",
    "usable_raw_file",
    "usable_content_type",
    "usable_char_count",
    "attempt_count",
    "success_count",
    "last_success_at",
    "raw_file_exists",
    "needs_attention",
    "attention_reason",
    "latest_error",
]


def build_crawl_summary(
    source_list: Path | str = DEFAULT_SOURCE_LIST,
    log_path: Path | str = DEFAULT_LOG_PATH,
) -> pd.DataFrame:
    sources = validate_source_list(pd.read_csv(source_list))
    logs = load_crawl_log(Path(log_path))

    rows: list[dict[str, object]] = []
    for source in sources.to_dict(orient="records"):
        source_logs = logs[
            (logs["school"].str.lower() == str(source["school"]).lower())
            & (logs["page_type"].str.lower() == str(source["page_type"]).lower())
            & (logs["source_url"] == source["url"])
        ].copy()
        rows.append(summarize_source(source, source_logs))

    frame = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    return frame.sort_values(["school", "priority", "page_type"], kind="stable").reset_index(
        drop=True
    )


def load_crawl_log(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=LOG_COLUMNS)

    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column in LOG_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""

    frame = frame[LOG_COLUMNS].copy()
    frame["_parsed_crawled_at"] = pd.to_datetime(frame["crawled_at"], errors="coerce", utc=True)
    frame["_original_order"] = range(len(frame))
    return frame


def summarize_source(source: dict[str, object], logs: pd.DataFrame) -> dict[str, object]:
    base = {
        "school": source["school"],
        "page_type": source["page_type"],
        "stage": source["stage"],
        "source_url": source["url"],
        "priority": int(source["priority"]),
        "need_dynamic": source["need_dynamic"],
        "latest_status": "not_crawled",
        "latest_http_status": "",
        "latest_title": "",
        "latest_final_url": "",
        "latest_crawled_at": "",
        "latest_raw_file": "",
        "latest_content_type": "",
        "latest_char_count": 0,
        "usable_status": "",
        "usable_title": "",
        "usable_final_url": "",
        "usable_crawled_at": "",
        "usable_raw_file": "",
        "usable_content_type": "",
        "usable_char_count": 0,
        "attempt_count": int(len(logs)),
        "success_count": 0,
        "last_success_at": "",
        "raw_file_exists": "no",
        "needs_attention": "yes",
        "attention_reason": "not_crawled",
        "latest_error": "",
    }

    if logs.empty:
        return base

    sorted_logs = logs.sort_values(["_parsed_crawled_at", "_original_order"], kind="stable")
    latest = sorted_logs.iloc[-1].to_dict()
    success_logs = sorted_logs[sorted_logs["status"].isin(OK_STATUSES)]

    base.update(
        {
            "latest_status": latest.get("status", ""),
            "latest_http_status": latest.get("http_status", ""),
            "latest_title": latest.get("title", ""),
            "latest_final_url": latest.get("final_url", ""),
            "latest_crawled_at": latest.get("crawled_at", ""),
            "latest_raw_file": latest.get("raw_file", ""),
            "latest_content_type": latest.get("content_type", ""),
            "latest_char_count": _to_int(latest.get("char_count", 0)),
            "success_count": int(len(success_logs)),
            "last_success_at": success_logs.iloc[-1]["crawled_at"] if not success_logs.empty else "",
            "latest_error": latest.get("error", ""),
        }
    )

    if not success_logs.empty:
        usable = success_logs.iloc[-1].to_dict()
        base.update(
            {
                "usable_status": usable.get("status", ""),
                "usable_title": usable.get("title", ""),
                "usable_final_url": usable.get("final_url", ""),
                "usable_crawled_at": usable.get("crawled_at", ""),
                "usable_raw_file": usable.get("raw_file", ""),
                "usable_content_type": usable.get("content_type", ""),
                "usable_char_count": _to_int(usable.get("char_count", 0)),
            }
        )

    raw_file = str(base["usable_raw_file"] or base["latest_raw_file"])
    raw_exists = bool(raw_file) and (ROOT_DIR / raw_file).exists()
    base["raw_file_exists"] = "yes" if raw_exists else "no"

    reason = attention_reason(base)
    base["needs_attention"] = "yes" if reason else "no"
    base["attention_reason"] = reason
    return base


def attention_reason(row: dict[str, object]) -> str:
    status = str(row.get("latest_status", ""))
    title = str(row.get("latest_title", "")).lower()
    final_url = str(row.get("latest_final_url", "")).lower()
    char_count = _to_int(row.get("latest_char_count", 0))

    if status not in OK_STATUSES:
        if _to_int(row.get("success_count", 0)) > 0:
            return "latest_attempt_failed_previous_success_available"
        return status or "unknown_status"
    if row.get("raw_file_exists") != "yes":
        return "raw_file_missing"
    if char_count < 100:
        return "content_too_short"
    if "page not found" in title or "404" in title or "/error/404" in final_url:
        return "possible_404_page"
    return ""


def write_crawl_summary(frame: pd.DataFrame, output: Path | str = DEFAULT_SUMMARY_PATH) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_path, index=False, encoding="utf-8-sig")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize latest crawl status per source URL.")
    parser.add_argument("--source-list", type=Path, default=DEFAULT_SOURCE_LIST)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_SUMMARY_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = build_crawl_summary(args.source_list, args.log_path)
    write_crawl_summary(frame, args.output)
    print(f"已生成 crawl summary：{len(frame)} 条 -> {args.output}")
    print(frame["latest_status"].value_counts(dropna=False).to_string())
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
