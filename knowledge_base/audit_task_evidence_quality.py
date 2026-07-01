"""Audit whether task evidence candidates are safe to promote into task fields."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import re
import sys

import pandas as pd

from crawler.crawl_pages import DEFAULT_SOURCE_LIST
from knowledge_base.extract_task_evidence import (
    DEFAULT_TASK_EVIDENCE_CSV,
    TASK_EVIDENCE_COLUMNS,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TASK_EVIDENCE_QUALITY_REPORT = (
    ROOT_DIR / "data" / "metadata" / "task_evidence_quality_report.csv"
)


TASK_EVIDENCE_QUALITY_COLUMNS = [
    "evidence_id",
    "school",
    "task_code",
    "stage",
    "evidence_type",
    "source_url",
    "source_question",
    "confidence",
    "text_char_count",
    "task_keyword_hit_count",
    "field_keyword_hit_count",
    "source_stage_match",
    "source_page_type",
    "normalized_value_present",
    "low_quality_flags",
    "quality_score",
    "quality_decision",
    "notes",
    "reviewed_at",
]


TASK_KEYWORDS = {
    "accept_offer": ("accept", "offer", "admission offer", "acceptance"),
    "pay_deposit": ("deposit", "payment", "pay", "admission deposit"),
    "submit_conditions": (
        "conditional",
        "condition",
        "transcript",
        "certificate",
        "degree",
        "graduation",
        "official document",
    ),
    "apply_student_visa": (
        "visa",
        "entry permit",
        "immigration",
        "e-visa",
        "id995",
        "non-local",
    ),
    "apply_accommodation": ("housing", "accommodation", "hostel", "hall", "residence"),
    "pay_tuition": ("tuition", "fee", "payment", "bill", "invoice"),
    "complete_registration": ("registration", "enrolment", "enrollment", "student account"),
    "prepare_arrival_orientation": ("orientation", "arrival", "induction", "welcome"),
}


FIELD_KEYWORDS = {
    "deadline": (
        "deadline",
        "due",
        "no later",
        "before",
        "on or before",
        "as soon as possible",
        "application period",
        "working days",
        "weeks",
    ),
    "required_document": (
        "document",
        "transcript",
        "certificate",
        "passport",
        "checklist",
        "form",
        "proof",
        "photo",
        "statement",
    ),
    "action_instruction": (
        "apply",
        "submit",
        "upload",
        "send",
        "check",
        "login",
        "complete",
        "download",
        "visit",
        "click",
        "pay",
    ),
    "action_url": ("http://", "https://"),
    "fee_amount": ("hkd", "hk$", "$", "fee", "deposit", "tuition"),
}


LOW_QUALITY_PATTERNS = (
    "application fee",
    "scholarship",
    "credit transfer",
    "programme cancelled",
    "program cancelled",
    "physical or other disability",
    "deferred admission",
    "deferred acceptance",
    "refund",
    "cancel any programmes",
)


TASK_PAGE_TYPES = {
    "accept_offer": {"offer_holder", "admitted_student", "faq"},
    "pay_deposit": {"offer_holder", "tuition", "faq"},
    "submit_conditions": {"offer_holder", "admitted_student", "faq"},
    "apply_student_visa": {"visa", "faq"},
    "apply_accommodation": {"accommodation", "faq"},
    "pay_tuition": {"tuition", "faq"},
    "complete_registration": {"registration", "admitted_student", "faq"},
    "prepare_arrival_orientation": {"orientation", "faq"},
}


def build_task_evidence_quality_report(
    task_evidence_csv: Path | str = DEFAULT_TASK_EVIDENCE_CSV,
    source_list: Path | str = DEFAULT_SOURCE_LIST,
) -> pd.DataFrame:
    evidence = _read_csv(Path(task_evidence_csv), required=TASK_EVIDENCE_COLUMNS)
    source_catalog = build_source_catalog(source_list)
    reviewed_at = datetime.now(UTC).date().isoformat()

    rows = []
    for row in evidence.to_dict(orient="records"):
        rows.append(audit_evidence_row(row, source_catalog=source_catalog, reviewed_at=reviewed_at))
    return pd.DataFrame(rows, columns=TASK_EVIDENCE_QUALITY_COLUMNS)


def audit_evidence_row(
    row: dict[str, object],
    *,
    source_catalog: dict[tuple[str, str], dict[str, set[str]]],
    reviewed_at: str,
) -> dict[str, object]:
    text = " ".join(
        [
            str(row.get("evidence_text", "")),
            str(row.get("normalized_value", "")),
            str(row.get("source_question", "")),
        ]
    ).lower()
    task_code = str(row.get("task_code", ""))
    evidence_type = str(row.get("evidence_type", ""))
    confidence = str(row.get("confidence", "")).lower()
    source_url = str(row.get("source_url", ""))
    school = str(row.get("school", ""))

    task_hits = count_keyword_hits(text, TASK_KEYWORDS.get(task_code, ()))
    field_hits = count_keyword_hits(text, FIELD_KEYWORDS.get(evidence_type, ()))
    source_info = source_catalog.get((school.lower(), source_url), {"page_types": set(), "stages": set()})
    page_types = set(source_info.get("page_types", set()))
    stages = set(source_info.get("stages", set()))
    source_page_type = ";".join(sorted(page_types))
    source_stage_match = source_matches_task(task_code, page_types, stages, str(row.get("stage", "")))
    flags = low_quality_flags(text, row)

    score = 0
    score += {"high": 30, "medium": 20, "low": 0}.get(confidence, 0)
    if task_hits:
        score += 25
    if field_hits:
        score += 15
    if source_stage_match == "yes":
        score += 15
    elif source_stage_match == "partial":
        score += 5
    if source_url:
        score += 10
    if str(row.get("normalized_value", "")).strip():
        score += 5

    if confidence == "low":
        score -= 30
    if evidence_type == "source_context":
        score -= 50
        flags.append("source_context_only")
    if not task_hits and evidence_type not in {"action_url", "fee_amount"}:
        score -= 25
        flags.append("task_keyword_mismatch")
    if not field_hits and evidence_type in FIELD_KEYWORDS:
        score -= 10
        flags.append("field_keyword_weak")
    if source_stage_match == "no":
        score -= 20
        flags.append("source_stage_or_page_type_mismatch")

    char_count = len(str(row.get("evidence_text", "")))
    if char_count < 30:
        score -= 20
        flags.append("text_too_short")
    elif char_count > 900:
        score -= 10
        flags.append("text_too_long")

    if flags:
        score -= 10 * len([flag for flag in flags if flag in {"admission_noise", "navigation_noise"}])

    decision = quality_decision(score, confidence=confidence, flags=flags, evidence_type=evidence_type)
    notes = "; ".join(flags) if flags else "rule checks passed"

    return {
        "evidence_id": row.get("evidence_id", ""),
        "school": school,
        "task_code": task_code,
        "stage": row.get("stage", ""),
        "evidence_type": evidence_type,
        "source_url": source_url,
        "source_question": row.get("source_question", ""),
        "confidence": row.get("confidence", ""),
        "text_char_count": char_count,
        "task_keyword_hit_count": task_hits,
        "field_keyword_hit_count": field_hits,
        "source_stage_match": source_stage_match,
        "source_page_type": source_page_type,
        "normalized_value_present": "yes" if str(row.get("normalized_value", "")).strip() else "no",
        "low_quality_flags": "; ".join(flags),
        "quality_score": max(0, min(100, score)),
        "quality_decision": decision,
        "notes": notes,
        "reviewed_at": reviewed_at,
    }


def build_source_catalog(source_list: Path | str = DEFAULT_SOURCE_LIST) -> dict[tuple[str, str], dict[str, set[str]]]:
    path = Path(source_list)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    catalog: dict[tuple[str, str], dict[str, set[str]]] = {}
    for row in frame.to_dict(orient="records"):
        school = str(row.get("school", "")).lower()
        url = str(row.get("url", ""))
        if not school or not url:
            continue
        item = catalog.setdefault((school, url), {"page_types": set(), "stages": set()})
        item["page_types"].add(str(row.get("page_type", "")))
        item["stages"].add(str(row.get("stage", "")))
    return catalog


def count_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword and keyword.lower() in text)


def source_matches_task(
    task_code: str,
    page_types: set[str],
    stages: set[str],
    inferred_stage: str,
) -> str:
    expected_page_types = TASK_PAGE_TYPES.get(task_code, set())
    if page_types & expected_page_types:
        return "yes"
    if inferred_stage and inferred_stage in stages:
        return "yes"
    if "faq" in page_types:
        return "partial"
    if not page_types and not stages:
        return "partial"
    return "no"


def low_quality_flags(text: str, row: dict[str, object]) -> list[str]:
    flags = []
    for pattern in LOW_QUALITY_PATTERNS:
        if pattern in text:
            flags.append("admission_noise")
            break
    if re.search(r"\b(home|menu|search|share|cookie|subscribe)\b", text) and len(text) > 500:
        flags.append("navigation_noise")
    return flags


def quality_decision(
    score: int,
    *,
    confidence: str,
    flags: list[str],
    evidence_type: str,
) -> str:
    if "source_context_only" in flags:
        return "reject"
    if "admission_noise" in flags:
        return "reject" if score < 70 else "review"
    if confidence == "low" and evidence_type not in {"action_url", "fee_amount"}:
        return "reject" if score < 70 else "review"
    if score >= 70:
        return "keep"
    if score >= 45:
        return "review"
    return "reject"


def write_task_evidence_quality_report(
    frame: pd.DataFrame,
    output_path: Path | str = DEFAULT_TASK_EVIDENCE_QUALITY_REPORT,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def _read_csv(path: Path, *, required: list[str]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=required)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column in required:
        if column not in frame.columns:
            frame[column] = ""
    return frame[required]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit task evidence candidate quality.")
    parser.add_argument("--task-evidence", type=Path, default=DEFAULT_TASK_EVIDENCE_CSV)
    parser.add_argument("--source-list", type=Path, default=DEFAULT_SOURCE_LIST)
    parser.add_argument("--output", type=Path, default=DEFAULT_TASK_EVIDENCE_QUALITY_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = build_task_evidence_quality_report(args.task_evidence, args.source_list)
    write_task_evidence_quality_report(frame, args.output)
    print(f"已生成 task evidence quality report：{len(frame)} 条 -> {args.output}")
    if not frame.empty:
        print(frame["quality_decision"].value_counts(dropna=False).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
