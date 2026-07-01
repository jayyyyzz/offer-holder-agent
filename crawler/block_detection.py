"""Shared soft-block and cached raw-page validation helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping


BLOCK_MARKERS = (
    "_incapsula_resource",
    "cf-chl-",
    "just a moment...",
    "attention required! | cloudflare",
    "enable javascript and cookies to continue",
    "access denied",
    "request unsuccessful",
)


def detect_block_marker(text: str, *, max_chars: int = 200_000) -> str:
    lowered = text[:max_chars].lower()
    for marker in BLOCK_MARKERS:
        if marker in lowered:
            return marker
    return ""


def validate_cached_raw_page(
    path: Path,
    source_row: Mapping[str, object],
    *,
    min_body_chars: int = 100,
) -> dict[str, object]:
    """Validate an existing raw archive before reporting skipped_exists.

    This is deliberately conservative.  It does not delete or overwrite the
    file; it only returns a status that can be written to crawl_log.csv so the
    operator knows a cached page needs attention.
    """

    if not path.exists():
        return _result(False, "missing_cached_raw", "cached raw file does not exist")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return _result(False, "stale_cached_decode_error", f"{type(exc).__name__}: {exc}")

    header, body = split_raw_page(text)
    expected = {
        "school": str(source_row.get("school", "")),
        "page_type": str(source_row.get("page_type", "")),
        "stage": str(source_row.get("stage", "")),
        "source_url": str(source_row.get("url", "")),
    }
    mismatches = []
    for key, expected_value in expected.items():
        cached_value = header.get(key, "")
        if cached_value and expected_value and cached_value != expected_value:
            mismatches.append(f"{key}: cached={cached_value!r} expected={expected_value!r}")
    if mismatches:
        return _result(
            False,
            "stale_cached_mismatch",
            "; ".join(mismatches),
            header=header,
            char_count=len(body),
        )

    marker = detect_block_marker(text)
    if marker:
        return _result(
            False,
            "stale_cached_soft_blocked",
            f"cached raw page contains possible anti-bot challenge: {marker}",
            header=header,
            char_count=len(body),
        )

    if len(body.strip()) < min_body_chars:
        return _result(
            False,
            "stale_cached_empty_content",
            f"cached raw body is shorter than {min_body_chars} characters",
            header=header,
            char_count=len(body),
        )

    return _result(True, "skipped_exists", "", header=header, char_count=len(body))


def split_raw_page(text: str) -> tuple[dict[str, str], str]:
    header_text, separator, body = text.partition("\n---\n")
    if not separator:
        return {}, text

    header: dict[str, str] = {}
    for line in header_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        header[key.strip()] = value.strip()
    return header, body


def _result(
    usable: bool,
    status: str,
    error: str,
    *,
    header: dict[str, str] | None = None,
    char_count: int = 0,
) -> dict[str, object]:
    header = header or {}
    return {
        "usable": usable,
        "status": status,
        "error": error,
        "title": header.get("title", ""),
        "final_url": header.get("final_url", ""),
        "content_type": header.get("content_type", ""),
        "char_count": char_count,
    }
