"""Import manually captured official-page text into the raw page archive.

This is useful for official pages that are blocked by WAF/anti-bot controls in
automation, but whose content can be opened and copied manually by the user.
The imported page uses the same raw-page format and crawl log schema as crawler
outputs, so downstream FAQ extraction, audit, and retrieval can reuse it.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import time

import pandas as pd

from crawler.crawl_pages import (
    DEFAULT_LOG_PATH,
    DEFAULT_RAW_DIR,
    DEFAULT_SOURCE_LIST,
    raw_filename,
    save_log,
    utc_now,
    validate_source_list,
    write_raw_page,
)


ROOT_DIR = Path(__file__).resolve().parents[1]


COMMON_MOJIBAKE_REPLACEMENTS = {
    "鈥檚": "’s",
    "鈥檙": "’r",
    "鈥檛": "’t",
    "鈥檓": "’m",
    "鈥檝": "’v",
    "鈥檒": "’l",
    "鈥淎": "“A",
    "鈥淧": "“P",
    "鈥?": "”",
    "銆€": " ",
}


def normalize_manual_text(text: str, *, fix_mojibake: bool = True) -> str:
    if fix_mojibake:
        for bad, good in COMMON_MOJIBAKE_REPLACEMENTS.items():
            text = text.replace(bad, good)

    lines: list[str] = []
    previous_nonblank = ""
    for raw_line in text.replace("\xa0", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if line == previous_nonblank:
            continue
        lines.append(line)
        previous_nonblank = line

    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def find_source_row(
    sources: pd.DataFrame,
    *,
    school: str,
    page_type: str,
    source_url: str | None = None,
) -> pd.Series:
    matches = sources[
        (sources["school"].str.lower() == school.lower())
        & (sources["page_type"].str.lower() == page_type.lower())
    ]
    if source_url:
        matches = matches[matches["url"] == source_url]
    if matches.empty:
        raise ValueError(
            f"source not found in source_list.csv: school={school}, "
            f"page_type={page_type}, source_url={source_url or '*'}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"multiple sources match school={school}, page_type={page_type}; "
            "pass --source-url to disambiguate"
        )
    return matches.iloc[0]


def import_manual_page(
    input_path: Path,
    *,
    school: str,
    page_type: str,
    source_url: str | None = None,
    title: str = "",
    source_list: Path = DEFAULT_SOURCE_LIST,
    raw_dir: Path = DEFAULT_RAW_DIR,
    log_path: Path = DEFAULT_LOG_PATH,
    fix_mojibake: bool = True,
) -> dict[str, object]:
    started = time.monotonic()
    sources = validate_source_list(pd.read_csv(source_list))
    row = find_source_row(sources, school=school, page_type=page_type, source_url=source_url)
    url = source_url or str(row["url"])
    output_path = raw_dir / raw_filename(str(row["school"]), str(row["page_type"]), url)

    raw_text = input_path.read_text(encoding="utf-8", errors="replace")
    text = normalize_manual_text(raw_text, fix_mojibake=fix_mojibake)
    crawled_at = utc_now()
    title = title or f"{row['school']} {row['page_type']} manual capture"

    write_raw_page(
        output_path,
        row=row,
        source_url=url,
        final_url=url,
        title=title,
        crawled_at=crawled_at,
        text=text,
        content_type="text/plain",
        extraction_method="manual_capture",
    )

    record = {
        "school": row["school"],
        "page_type": row["page_type"],
        "stage": row["stage"],
        "source_url": url,
        "final_url": url,
        "priority": int(row["priority"]),
        "need_dynamic": row["need_dynamic"],
        "status": "success",
        "http_status": "",
        "title": title,
        "crawled_at": crawled_at,
        "raw_file": output_path.relative_to(ROOT_DIR).as_posix(),
        "content_type": "text/plain",
        "char_count": len(text),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "error": f"manual_capture_from={input_path}",
    }
    save_log([record], log_path)
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import manually copied official-page text.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--school", required=True)
    parser.add_argument("--page-type", required=True)
    parser.add_argument("--source-url")
    parser.add_argument("--title", default="")
    parser.add_argument("--source-list", type=Path, default=DEFAULT_SOURCE_LIST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--no-fix-mojibake", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    record = import_manual_page(
        args.input,
        school=args.school,
        page_type=args.page_type,
        source_url=args.source_url,
        title=args.title,
        source_list=args.source_list,
        raw_dir=args.raw_dir,
        log_path=args.log_path,
        fix_mojibake=not args.no_fix_mojibake,
    )
    print(
        f"已导入 manual capture：{record['school']} / {record['page_type']} "
        f"chars={record['char_count']} -> {record['raw_file']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
