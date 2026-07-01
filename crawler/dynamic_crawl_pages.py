"""Browser-rendered crawler for pages that ordinary HTTP requests cannot extract.

This is primarily for official pages protected by WAF/JavaScript rendering, for
example CityUHK pages that return an Incapsula shell to ``requests`` but render
readable content in a real browser.
"""

from __future__ import annotations

import argparse
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests

from crawler.block_detection import validate_cached_raw_page
from crawler.crawl_pages import (
    DEFAULT_LOG_PATH,
    DEFAULT_RAW_DIR,
    DEFAULT_SOURCE_LIST,
    LOG_COLUMNS,
    CrawlConfig,
    RobotsCache,
    clean_html,
    raw_filename,
    save_log,
    utc_now,
    validate_source_list,
    write_raw_page,
)


ROOT_DIR = Path(__file__).resolve().parents[1]


VISIBLE_BLOCK_MARKERS = (
    "enable javascript and cookies to continue",
    "just a moment...",
    "attention required! | cloudflare",
    "access denied",
    "request unsuccessful",
)


@dataclass(frozen=True)
class BrowserCrawlConfig:
    timeout_ms: int = 45_000
    settle_ms: int = 2_500
    delay: float = 1.5
    headless: bool = True
    user_agent: str = ""
    robots_user_agent: str = (
        "HKOfferAgentResearchBot/0.1 "
        "(browser-rendered official-page archive; contact: replace-with-your-email@example.com)"
    )
    respect_robots: bool = True


def detect_visible_block(text: str, title: str = "") -> str:
    lowered = f"{title}\n{text}".lower()
    for marker in VISIBLE_BLOCK_MARKERS:
        if marker in lowered:
            return marker
    return ""


def normalize_visible_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def select_sources(
    source_list: Path,
    *,
    schools: Iterable[str] | None = None,
    page_types: Iterable[str] | None = None,
    max_priority: int = 3,
    only_need_dynamic: bool = True,
    limit: int | None = None,
) -> pd.DataFrame:
    sources = validate_source_list(pd.read_csv(source_list))
    sources = sources[sources["priority"] <= max_priority]
    if only_need_dynamic:
        sources = sources[sources["need_dynamic"].str.lower().eq("yes")]
    if schools:
        wanted = {school.lower() for school in schools}
        sources = sources[sources["school"].str.lower().isin(wanted)]
    if page_types:
        wanted_types = {page_type.lower() for page_type in page_types}
        sources = sources[sources["page_type"].str.lower().isin(wanted_types)]
    if limit:
        sources = sources.head(limit)
    return sources


class BrowserPageCrawler:
    def __init__(self, config: BrowserCrawlConfig) -> None:
        self.config = config
        session = requests.Session()
        session.headers.update({"User-Agent": config.robots_user_agent})
        self.robots = RobotsCache(
            session,
            CrawlConfig(
                timeout=config.timeout_ms / 1000,
                delay=config.delay,
                user_agent=config.robots_user_agent,
                respect_robots=config.respect_robots,
            ),
        )

    def crawl_row(self, row: pd.Series, raw_dir: Path, force: bool, page: object) -> dict[str, object]:
        started = time.monotonic()
        url = str(row["url"])
        filename = raw_filename(str(row["school"]), str(row["page_type"]), url)
        output_path = raw_dir / filename
        base = {
            "school": row["school"],
            "page_type": row["page_type"],
            "stage": row["stage"],
            "source_url": url,
            "final_url": "",
            "priority": int(row["priority"]),
            "need_dynamic": row["need_dynamic"],
            "status": "",
            "http_status": "",
            "title": "",
            "crawled_at": utc_now(),
            "raw_file": output_path.relative_to(ROOT_DIR).as_posix(),
            "content_type": "text/html",
            "char_count": 0,
            "elapsed_ms": 0,
            "error": "",
        }

        if output_path.exists() and not force:
            cached = validate_cached_raw_page(output_path, row)
            base["status"] = cached["status"]
            base["error"] = cached["error"]
            base["title"] = cached["title"]
            base["final_url"] = cached["final_url"]
            base["content_type"] = cached["content_type"] or "text/html"
            base["char_count"] = cached["char_count"]
            base["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return base

        if not self.robots.allowed(url):
            base["status"] = "blocked_by_robots"
            base["error"] = "robots.txt does not allow this user agent"
            base["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return base

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
            if response is not None:
                base["http_status"] = response.status
            try:
                page.wait_for_load_state("networkidle", timeout=min(10_000, self.config.timeout_ms))
            except Exception:
                logging.debug("networkidle not reached for %s", url)
            page.wait_for_timeout(self.config.settle_ms)

            final_url = page.url
            title = page.title()
            html = page.content()
            _, html_text = clean_html(html)
            visible_text = normalize_visible_text(page.locator("body").inner_text(timeout=10_000))
            text = visible_text if len(visible_text) >= len(html_text) else html_text
            marker = detect_visible_block(text, title)

            base["final_url"] = final_url
            base["title"] = title
            base["char_count"] = len(text)

            if marker:
                base["status"] = "soft_blocked_dynamic"
                base["error"] = f"visible anti-bot or denial page: {marker}"
                return base
            if len(text) < 100:
                base["status"] = "empty_content"
                base["error"] = "browser-rendered text is shorter than 100 characters"
                return base

            write_raw_page(
                output_path,
                row=row,
                source_url=url,
                final_url=final_url,
                title=title,
                crawled_at=str(base["crawled_at"]),
                text=text,
                content_type="text/html",
                extraction_method="browser_playwright",
            )
            base["status"] = "success_dynamic"
            return base
        except Exception as exc:
            base["status"] = "request_error"
            base["error"] = f"{type(exc).__name__}: {exc}"
            return base
        finally:
            base["elapsed_ms"] = int((time.monotonic() - started) * 1000)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Browser-render official HK university pages")
    parser.add_argument("--source-list", type=Path, default=DEFAULT_SOURCE_LIST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--school", action="append", help="Filter by school; repeatable")
    parser.add_argument("--page-type", action="append", help="Filter by page_type; repeatable")
    parser.add_argument("--max-priority", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout-ms", type=int, default=45_000)
    parser.add_argument("--settle-ms", type=int, default=2_500)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--force", action="store_true", help="Overwrite existing text files")
    parser.add_argument("--all", action="store_true", help="Crawl all matching sources, not only need_dynamic=yes")
    parser.add_argument("--headed", action="store_true", help="Show browser window")
    parser.add_argument("--user-agent", default="", help="Optional browser user agent; default uses Playwright browser UA")
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sources = select_sources(
        args.source_list,
        schools=args.school,
        page_types=args.page_type,
        max_priority=args.max_priority,
        only_need_dynamic=not args.all,
        limit=args.limit,
    )
    if sources.empty:
        logging.warning("没有匹配的动态采集数据源")
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run: "
            ".\\.venv\\Scripts\\python -m pip install -r requirements.txt"
        ) from exc

    config = BrowserCrawlConfig(
        timeout_ms=args.timeout_ms,
        settle_ms=args.settle_ms,
        delay=args.delay,
        headless=not args.headed,
        user_agent=args.user_agent,
        respect_robots=not args.ignore_robots,
    )
    crawler = BrowserPageCrawler(config)
    records: list[dict[str, object]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=config.headless)
        context_kwargs = {
            "locale": "en-HK",
            "viewport": {"width": 1366, "height": 900},
        }
        if config.user_agent:
            context_kwargs["user_agent"] = config.user_agent
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        try:
            for _, row in sources.iterrows():
                logging.info("[%s/%s] %s", row["school"], row["page_type"], row["url"])
                record = crawler.crawl_row(row, args.raw_dir, args.force, page)
                records.append(record)
                logging.info(
                    "status=%s http=%s chars=%s",
                    record["status"],
                    record["http_status"],
                    record["char_count"],
                )
                time.sleep(config.delay)
        finally:
            context.close()
            browser.close()

    save_log(records, args.log_path)
    counts = pd.Series([record["status"] for record in records]).value_counts()
    print(counts.to_string())
    return 1 if any(status in {"request_error", "parse_error"} for status in counts.index) else 0


if __name__ == "__main__":
    raise SystemExit(main())
