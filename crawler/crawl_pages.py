from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
import logging
import re
import time
import urllib.robotparser
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

import pandas as pd
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from crawler.block_detection import detect_block_marker, validate_cached_raw_page

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - depends on local optional dependency
    PdfReader = None  # type: ignore[assignment]


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_LIST = ROOT_DIR / "source_list.csv"
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw_pages"
DEFAULT_LOG_PATH = ROOT_DIR / "data" / "metadata" / "crawl_log.csv"

SOURCE_COLUMNS = [
    "school",
    "page_type",
    "stage",
    "url",
    "priority",
    "need_dynamic",
    "remark",
]
LOG_COLUMNS = [
    "school",
    "page_type",
    "stage",
    "source_url",
    "final_url",
    "priority",
    "need_dynamic",
    "status",
    "http_status",
    "title",
    "crawled_at",
    "raw_file",
    "content_type",
    "char_count",
    "elapsed_ms",
    "error",
]

REMOVE_TAGS = [
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "aside",
    "noscript",
    "svg",
    "canvas",
    "form",
    "button",
]
NOISE_SELECTORS = [
    "[aria-label*='cookie' i]",
    "[class*='cookie' i]",
    "[id*='cookie' i]",
    "[class*='breadcrumb' i]",
    "[id*='breadcrumb' i]",
    "[class*='social' i]",
    "[class*='share' i]",
    "[class*='newsletter' i]",
    "[class*='popup' i]",
    "[class*='modal' i]",
]
PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "applications/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
}


@dataclass(frozen=True)
class CrawlConfig:
    timeout: float = 25
    delay: float = 1.5
    user_agent: str = (
        "HKOfferAgentResearchBot/0.1 "
        "(official-page archive; contact: replace-with-your-email@example.com)"
    )
    respect_robots: bool = True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_slug(value: str, max_length: int = 50) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower())
    return value.strip("_")[:max_length] or "page"


def raw_filename(school: str, page_type: str, url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    return f"{safe_slug(school)}__{safe_slug(page_type)}__{digest}.txt"


def detect_soft_block(html: str) -> str:
    return detect_block_marker(html)


def clean_html(html: str) -> tuple[str, str]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()
    for selector in NOISE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    root = soup.find("main") or soup.find("article") or soup.body or soup
    text = root.get_text("\n", strip=True)
    return title[:500], normalize_text(text)


def extract_pdf_text(content: bytes) -> tuple[str, str]:
    """Extract readable text from a PDF response.

    The crawler stores extracted PDF text in the same raw-page text format as
    HTML pages. Layout fidelity is not the goal here; this is for retrieval and
    downstream task extraction.
    """

    if PdfReader is None:
        raise RuntimeError("pypdf is required to extract PDF text; install project dependencies first")

    reader = PdfReader(BytesIO(content))
    metadata = reader.metadata
    title = ""
    if metadata and metadata.title:
        title = str(metadata.title).strip()

    parts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        page_text = normalize_text(page_text)
        if page_text:
            parts.append(f"[PDF page {index}]\n{page_text}")

    return title[:500], "\n\n".join(parts)


def normalize_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def is_pdf_content(content_type: str, url: str) -> bool:
    content_type = content_type.split(";")[0].strip().lower()
    return content_type in PDF_CONTENT_TYPES or urlsplit(url).path.lower().endswith(".pdf")


def write_raw_page(
    output_path: Path,
    *,
    row: pd.Series,
    source_url: str,
    final_url: str,
    title: str,
    crawled_at: str,
    text: str,
    content_type: str,
    extraction_method: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"school: {row['school']}\n"
        f"page_type: {row['page_type']}\n"
        f"stage: {row['stage']}\n"
        f"source_url: {source_url}\n"
        f"final_url: {final_url}\n"
        f"title: {title}\n"
        f"content_type: {content_type}\n"
        f"extraction_method: {extraction_method}\n"
        f"crawled_at: {crawled_at}\n"
        "---\n"
    )
    output_path.write_text(header + text + "\n", encoding="utf-8")


def validate_source_list(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in SOURCE_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"source_list.csv 缺少字段: {', '.join(missing)}")

    result = frame[SOURCE_COLUMNS].copy()
    for column in ("school", "page_type", "stage", "url", "need_dynamic", "remark"):
        result[column] = result[column].fillna("").astype(str).str.strip()
    result["priority"] = pd.to_numeric(result["priority"], errors="coerce").fillna(3).astype(int)
    result["need_dynamic"] = result["need_dynamic"].str.lower()

    invalid_urls = ~result["url"].str.match(r"^https?://", case=False)
    if invalid_urls.any():
        bad_rows = ", ".join(str(index + 2) for index in result.index[invalid_urls])
        raise ValueError(f"source_list.csv 存在无效 URL，行号: {bad_rows}")
    return result


class RobotsCache:
    def __init__(self, session: requests.Session, config: CrawlConfig) -> None:
        self.session = session
        self.config = config
        self.cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        if not self.config.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.cache:
            robots_url = origin + "/robots.txt"
            parser = urllib.robotparser.RobotFileParser(robots_url)
            try:
                response = self.session.get(robots_url, timeout=self.config.timeout)
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                    self.cache[origin] = parser
                elif response.status_code in {401, 403}:
                    parser.parse(["User-agent: *", "Disallow: /"])
                    self.cache[origin] = parser
                else:
                    self.cache[origin] = None
            except requests.RequestException:
                self.cache[origin] = None
        parser = self.cache[origin]
        return parser is None or parser.can_fetch(self.config.user_agent, url)


class PageCrawler:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.2",
                "Accept-Language": "en,zh-Hant;q=0.9,zh;q=0.8",
            }
        )
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.75,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.robots = RobotsCache(self.session, config)
        self._next_request_at: dict[str, float] = {}

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        remaining = self._next_request_at.get(host, 0) - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        self._next_request_at[host] = time.monotonic() + self.config.delay

    def crawl_row(self, row: pd.Series, raw_dir: Path, force: bool) -> dict[str, object]:
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
            "content_type": "",
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
            base["content_type"] = cached["content_type"]
            base["char_count"] = cached["char_count"]
            base["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return base

        if not self.robots.allowed(url):
            base["status"] = "blocked_by_robots"
            base["error"] = "robots.txt does not allow this user agent"
            base["elapsed_ms"] = int((time.monotonic() - started) * 1000)
            return base

        try:
            self._wait(url)
            response = self.session.get(url, timeout=self.config.timeout, allow_redirects=True)
            base["final_url"] = response.url
            base["http_status"] = response.status_code
            base["content_type"] = response.headers.get("Content-Type", "").split(";")[0]
            response.raise_for_status()

            content_type = str(base["content_type"]).lower()
            if is_pdf_content(content_type, response.url):
                title, text = extract_pdf_text(response.content)
                if not title:
                    title = Path(urlsplit(response.url).path).stem or "PDF document"
                extraction_method = "pdf_pypdf"
            elif "html" in content_type:
                marker = detect_soft_block(response.text)
                title, text = clean_html(response.text)
                if marker:
                    base["title"] = title
                    base["char_count"] = len(text)
                    base["status"] = "soft_blocked"
                    base["error"] = f"possible anti-bot challenge: {marker}"
                    return base
                extraction_method = "html_beautifulsoup"
            else:
                base["status"] = "unsupported_content"
                base["error"] = (
                    "crawler extracts HTML and PDF only, "
                    f"got {base['content_type'] or 'unknown content type'}"
                )
                return base

            base["title"] = title
            base["char_count"] = len(text)

            if len(text) < 100:
                base["status"] = "empty_content"
                base["error"] = "cleaned page text is shorter than 100 characters"
                return base

            write_raw_page(
                output_path,
                row=row,
                source_url=url,
                final_url=response.url,
                title=title,
                crawled_at=str(base["crawled_at"]),
                text=text,
                content_type=str(base["content_type"]),
                extraction_method=extraction_method,
            )
            base["status"] = "success"
            return base
        except requests.RequestException as exc:
            base["status"] = "request_error"
            base["error"] = f"{type(exc).__name__}: {exc}"
            return base
        except Exception as exc:
            base["status"] = "parse_error"
            base["error"] = f"{type(exc).__name__}: {exc}"
            return base
        finally:
            base["elapsed_ms"] = int((time.monotonic() - started) * 1000)


def load_existing_log(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=LOG_COLUMNS)
    frame = pd.read_csv(path)
    for column in LOG_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[LOG_COLUMNS]


def save_log(records: Iterable[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing_log(path)
    new_rows = pd.DataFrame(list(records), columns=LOG_COLUMNS)
    pd.concat([existing, new_rows], ignore_index=True).to_csv(
        path,
        index=False,
        encoding="utf-8-sig",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl official HK university offer-holder pages")
    parser.add_argument("--source-list", type=Path, default=DEFAULT_SOURCE_LIST)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--school", action="append", help="Filter by school; repeatable")
    parser.add_argument("--page-type", action="append", help="Filter by page_type; repeatable")
    parser.add_argument("--max-priority", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=float, default=25)
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--force", action="store_true", help="Overwrite existing text files")
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sources = validate_source_list(pd.read_csv(args.source_list))
    sources = sources[sources["priority"] <= args.max_priority]
    if args.school:
        schools = {value.lower() for value in args.school}
        sources = sources[sources["school"].str.lower().isin(schools)]
    if args.page_type:
        page_types = {value.lower() for value in args.page_type}
        sources = sources[sources["page_type"].str.lower().isin(page_types)]
    if args.limit:
        sources = sources.head(args.limit)

    if sources.empty:
        logging.warning("没有匹配的数据源")
        return 0

    config = CrawlConfig(
        timeout=args.timeout,
        delay=args.delay,
        respect_robots=not args.ignore_robots,
    )
    crawler = PageCrawler(config)
    records: list[dict[str, object]] = []
    for _, row in sources.iterrows():
        logging.info("[%s/%s] %s", row["school"], row["page_type"], row["url"])
        record = crawler.crawl_row(row, args.raw_dir, args.force)
        records.append(record)
        logging.info(
            "status=%s http=%s chars=%s",
            record["status"],
            record["http_status"],
            record["char_count"],
        )

    save_log(records, args.log_path)
    counts = pd.Series([record["status"] for record in records]).value_counts()
    print(counts.to_string())
    return 1 if any(status in {"request_error", "parse_error"} for status in counts.index) else 0


if __name__ == "__main__":
    raise SystemExit(main())
