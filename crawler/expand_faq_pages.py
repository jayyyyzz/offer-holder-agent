"""Browser-click crawler for FAQ pages with collapsed answers.

Some university FAQ pages render the answer text only after an accordion item is
opened.  This module uses Playwright to render the page, force common collapsed
containers open, click FAQ-like controls, and then archive the expanded text in
the same raw-page format used by the static crawler.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import re
import time
from typing import Iterable
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup
import pandas as pd
import requests

from crawler.block_detection import validate_cached_raw_page
from crawler.crawl_pages import (
    DEFAULT_LOG_PATH,
    DEFAULT_RAW_DIR,
    DEFAULT_SOURCE_LIST,
    CrawlConfig,
    RobotsCache,
    normalize_text,
    raw_filename,
    save_log,
    utc_now,
    validate_source_list,
    write_raw_page,
)
from crawler.dynamic_crawl_pages import detect_visible_block


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MANUAL_REVIEW_QUEUE = ROOT_DIR / "data" / "metadata" / "manual_review_queue.csv"

FAQ_CLICK_SELECTORS = (
    "button, "
    "[role='button'], "
    "[data-bs-toggle='collapse'], "
    "[data-toggle='collapse'], "
    ".accordion-button, "
    ".accordion-title, "
    ".faq-question, "
    ".faq-title, "
    "a[href^='#']"
)

EXTRA_BLOCK_MARKERS = (
    "security detection powered by safeline waf",
    "confirm you are human",
)


@dataclass(frozen=True)
class FaqExpandConfig:
    timeout_ms: int = 60_000
    settle_ms: int = 2_500
    click_pause_ms: int = 100
    delay: float = 1.5
    max_clicks: int = 300
    headless: bool = True
    respect_robots: bool = True
    user_agent: str = ""
    robots_user_agent: str = (
        "HKOfferAgentResearchBot/0.1 "
        "(expanded FAQ official-page archive; contact: replace-with-your-email@example.com)"
    )


def select_sources(
    source_list: Path,
    *,
    manual_review_queue: Path | None = None,
    from_manual_review: bool = False,
    schools: Iterable[str] | None = None,
    page_types: Iterable[str] | None = None,
    max_priority: int = 3,
    limit: int | None = None,
) -> pd.DataFrame:
    sources = validate_source_list(pd.read_csv(source_list))
    sources = sources[sources["priority"] <= max_priority]

    if from_manual_review:
        if manual_review_queue is None or not manual_review_queue.exists():
            return sources.iloc[0:0].copy()
        queue = pd.read_csv(manual_review_queue, dtype=str, keep_default_na=False)
        urls = {
            url
            for url in queue.get("source_url", pd.Series(dtype=str)).astype(str)
            if url.startswith("http")
        }
        sources = sources[sources["url"].isin(urls)]

    if schools:
        wanted = {school.lower() for school in schools}
        sources = sources[sources["school"].str.lower().isin(wanted)]
    if page_types:
        wanted_types = {page_type.lower() for page_type in page_types}
        sources = sources[sources["page_type"].str.lower().isin(wanted_types)]
    else:
        sources = sources[sources["page_type"].str.lower().eq("faq")]

    if limit:
        sources = sources.head(limit)
    return sources.sort_values(["school", "priority", "url"], kind="stable").reset_index(drop=True)


class ExpandedFaqCrawler:
    def __init__(self, config: FaqExpandConfig) -> None:
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
        record = {
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
            record["status"] = cached["status"]
            record["error"] = cached["error"]
            record["title"] = cached["title"]
            record["final_url"] = cached["final_url"]
            record["content_type"] = cached["content_type"] or "text/html"
            record["char_count"] = cached["char_count"]
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record

        if not self.robots.allowed(url):
            record["status"] = "blocked_by_robots"
            record["error"] = "robots.txt does not allow this user agent"
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return record

        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)
            if response is not None:
                record["http_status"] = response.status
            try:
                page.wait_for_load_state("networkidle", timeout=min(15_000, self.config.timeout_ms))
            except Exception:
                logging.debug("networkidle not reached for %s", url)
            page.wait_for_timeout(self.config.settle_ms)

            before_text = safe_body_text(page)
            force_expand_dom(page)
            clicked = click_faq_like_controls(
                page,
                max_clicks=self.config.max_clicks,
                pause_ms=self.config.click_pause_ms,
            )
            force_expand_dom(page)
            page.wait_for_timeout(self.config.settle_ms)

            final_url = page.url
            title = page.title()
            html = page.content()
            text = html_to_expanded_text(html, final_url or url)
            after_text = safe_body_text(page)
            marker = detect_visible_block(f"{after_text}\n{text}", title) or detect_extra_block(
                f"{after_text}\n{text}"
            )

            record["final_url"] = final_url
            record["title"] = title
            record["char_count"] = len(text)

            if marker:
                record["status"] = "soft_blocked_dynamic"
                record["error"] = f"visible anti-bot or denial page: {marker}"
                return record
            if len(text) < 100:
                record["status"] = "empty_content"
                record["error"] = "expanded FAQ text is shorter than 100 characters"
                return record

            write_raw_page(
                output_path,
                row=row,
                source_url=url,
                final_url=final_url,
                title=title,
                crawled_at=str(record["crawled_at"]),
                text=text,
                content_type="text/html",
                extraction_method="browser_faq_expand_click",
            )
            record["status"] = "success_dynamic"
            record["error"] = (
                f"expanded_clicks={clicked}; "
                f"before_chars={len(before_text)}; "
                f"after_visible_chars={len(after_text)}"
            )
            return record
        except Exception as exc:
            record["status"] = "request_error"
            record["error"] = f"{type(exc).__name__}: {exc}"
            return record
        finally:
            record["elapsed_ms"] = int((time.monotonic() - started) * 1000)


def force_expand_dom(page: object) -> None:
    page.evaluate(
        """
        () => {
            document.querySelectorAll('details').forEach(el => { el.open = true; });

            document.querySelectorAll('[hidden]').forEach(el => {
                el.removeAttribute('hidden');
            });

            document.querySelectorAll('.collapse, .accordion-collapse').forEach(el => {
                el.classList.add('show');
                el.style.display = 'block';
                el.style.visibility = 'visible';
                el.style.height = 'auto';
            });

            document.querySelectorAll('[aria-expanded="false"]').forEach(el => {
                el.setAttribute('aria-expanded', 'true');
            });

            document.querySelectorAll('[style*="display: none"], [style*="display:none"]').forEach(el => {
                el.style.display = 'block';
            });

            document.querySelectorAll('[style*="visibility: hidden"], [style*="visibility:hidden"]').forEach(el => {
                el.style.visibility = 'visible';
            });

            document.querySelectorAll('[style*="height: 0"], [style*="height:0"]').forEach(el => {
                el.style.height = 'auto';
            });
        }
        """
    )


def click_faq_like_controls(page: object, *, max_clicks: int, pause_ms: int) -> int:
    candidates = page.locator(FAQ_CLICK_SELECTORS)
    count = min(candidates.count(), max_clicks)
    clicked = 0
    for index in range(count):
        try:
            item = candidates.nth(index)
            text = clean_inline_text(item.inner_text(timeout=800))
            if not is_faq_like_control(text):
                continue
            item.click(timeout=1_500, force=True)
            clicked += 1
            page.wait_for_timeout(pause_ms)
        except Exception:
            continue
    return clicked


def is_faq_like_control(text: str) -> bool:
    cleaned = clean_inline_text(text)
    if not cleaned or len(cleaned) > 260:
        return False
    lowered = cleaned.lower()
    if cleaned.endswith("?"):
        return True
    if re.match(r"^\d{1,2}[.)]\s+", cleaned):
        return True
    faq_keywords = (
        "offer",
        "acceptance",
        "admission",
        "application",
        "requirement",
        "document",
        "transcript",
        "certificate",
        "visa",
        "entry permit",
        "tuition",
        "fee",
        "payment",
        "registration",
        "enrol",
        "enroll",
        "student card",
        "accommodation",
        "financial",
        "non-local",
        "local applicant",
    )
    return any(keyword in lowered for keyword in faq_keywords)


def html_to_expanded_text(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    for selector in ("[aria-hidden='true']", ".visually-hidden", ".sr-only"):
        for node in soup.select(selector):
            node.decompose()

    for anchor in soup.find_all("a"):
        text = clean_inline_text(anchor.get_text(" ", strip=True))
        href = anchor.get("href")
        if text and href:
            full_url = urljoin(base_url, href)
            if should_keep_anchor_text_only(text, href, full_url, base_url) or full_url in text:
                anchor.replace_with(text)
            else:
                anchor.replace_with(f"{text} ({full_url})")
        elif text:
            anchor.replace_with(text)

    root = soup.find("main") or soup.find("article") or soup.body or soup
    return normalize_text(root.get_text("\n", strip=True))


def should_keep_anchor_text_only(text: str, href: str, full_url: str, base_url: str) -> bool:
    href = href.strip()
    lowered_href = href.lower()
    if lowered_href.startswith(("javascript:", "mailto:", "tel:")):
        return True
    if href.startswith("#"):
        return True
    full_without_fragment = urldefrag(full_url).url.rstrip("/")
    base_without_fragment = urldefrag(base_url).url.rstrip("/")
    if full_without_fragment == base_without_fragment and is_faq_like_control(text):
        return True
    return False


def safe_body_text(page: object) -> str:
    try:
        return clean_inline_text(page.locator("body").inner_text(timeout=10_000))
    except Exception:
        return ""


def clean_inline_text(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def detect_extra_block(text: str) -> str:
    lowered = text.lower()
    for marker in EXTRA_BLOCK_MARKERS:
        if marker in lowered:
            return marker
    return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Expand and archive collapsed official FAQ pages.")
    parser.add_argument("--source-list", type=Path, default=DEFAULT_SOURCE_LIST)
    parser.add_argument("--manual-review-queue", type=Path, default=DEFAULT_MANUAL_REVIEW_QUEUE)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--from-manual-review", action="store_true")
    parser.add_argument("--school", action="append", help="Filter by school; repeatable")
    parser.add_argument("--page-type", action="append", help="Filter by page_type; repeatable")
    parser.add_argument("--max-priority", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    parser.add_argument("--settle-ms", type=int, default=2_500)
    parser.add_argument("--click-pause-ms", type=int, default=100)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--max-clicks", type=int, default=300)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument("--user-agent", default="")
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
        manual_review_queue=args.manual_review_queue,
        from_manual_review=args.from_manual_review,
        schools=args.school,
        page_types=args.page_type,
        max_priority=args.max_priority,
        limit=args.limit,
    )
    if sources.empty:
        logging.warning("No matching FAQ sources to expand")
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run: "
            ".\\.venv\\Scripts\\python -m pip install -r requirements.txt"
        ) from exc

    config = FaqExpandConfig(
        timeout_ms=args.timeout_ms,
        settle_ms=args.settle_ms,
        click_pause_ms=args.click_pause_ms,
        delay=args.delay,
        max_clicks=args.max_clicks,
        headless=not args.headed,
        respect_robots=not args.ignore_robots,
        user_agent=args.user_agent,
    )
    crawler = ExpandedFaqCrawler(config)
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
                    "status=%s http=%s chars=%s note=%s",
                    record["status"],
                    record["http_status"],
                    record["char_count"],
                    record["error"],
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
