"""Extract task-planning evidence from cleaned FAQ rows.

The output is intentionally an auditable intermediate table.  It does not
overwrite ``tasks.csv``.  Instead, it records official-source snippets that can
later be promoted into task deadlines, required documents, action URLs, or
instructions after human review.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
import sys

import pandas as pd

from knowledge_base.extract_faq import DEFAULT_FAQ_CSV


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CLEAN_FAQ_CSV = ROOT_DIR / "data" / "cleaned" / "faq_cleaned.csv"
DEFAULT_TASK_EVIDENCE_CSV = ROOT_DIR / "data" / "cleaned" / "task_evidence.csv"


TASK_EVIDENCE_COLUMNS = [
    "evidence_id",
    "task_code",
    "school",
    "stage",
    "evidence_type",
    "evidence_text",
    "normalized_value",
    "source_question",
    "source_url",
    "confidence",
    "updated_at",
]


TASK_KEYWORDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "apply_student_visa",
        "visa",
        (
            "student visa",
            "entry permit",
            "visa application",
            "immigration",
            "e-visa",
            "id995",
        ),
    ),
    (
        "pay_deposit",
        "offer_acceptance",
        (
            "deposit",
            "accept offer and pay",
            "pay the deposit",
            "payment proof",
            "offer acceptance",
        ),
    ),
    (
        "accept_offer",
        "offer_acceptance",
        (
            "accept the offer",
            "admission offer",
            "acceptance deadline",
            "online admission system",
        ),
    ),
    (
        "submit_conditions",
        "offer_acceptance",
        (
            "offer conditions",
            "conditional offer",
            "supporting documents",
            "official documents",
            "document checklist",
            "transcript",
            "certificate",
            "certified true copies",
        ),
    ),
    (
        "apply_accommodation",
        "housing",
        ("accommodation", "housing", "hostel", "hall", "residence"),
    ),
    (
        "pay_tuition",
        "payment",
        ("tuition", "tuition fee", "programme fee", "student account", "billing"),
    ),
    (
        "complete_registration",
        "registration",
        (
            "registration",
            "online registration",
            "enrolment",
            "enrollment",
            "student card",
            "student account",
            "document verification",
        ),
    ),
    (
        "prepare_arrival_orientation",
        "orientation",
        ("orientation", "induction", "arrival", "moving to hong kong", "welcome"),
    ),
)


DEADLINE_PATTERNS = (
    "deadline",
    "no later than",
    "before the deadline",
    "by the deadline",
    "by ",
    "before ",
    "mid-july",
    "end december",
    "application period",
    "apply right after",
    "as soon as possible",
    "on or before",
    "working days",
    "weeks",
)

DOCUMENT_PATTERNS = (
    "document",
    "documents",
    "checklist",
    "transcript",
    "certificate",
    "certified true copies",
    "translation",
    "score report",
    "bank statement",
    "passbook",
    "financial proof",
    "financial standing",
    "application form",
    "mailing cover",
    "passport",
    "travel document",
    "photo",
)

ACTION_PATTERNS = (
    "accept",
    "apply",
    "arrange",
    "check",
    "click",
    "download",
    "log in",
    "login",
    "pay",
    "send",
    "submit",
    "upload",
    "visit",
)

URL_RE = re.compile(r"https?://[^\s),;]+", flags=re.I)
FEE_RE = re.compile(r"\b(?:HK\$|HKD\s*)[\d,]+(?:\.\d+)?\b", flags=re.I)


@dataclass(frozen=True)
class TaskEvidence:
    evidence_id: str
    task_code: str
    school: str
    stage: str
    evidence_type: str
    evidence_text: str
    normalized_value: str
    source_question: str
    source_url: str
    confidence: str
    updated_at: str

    def to_row(self) -> dict[str, str]:
        return {column: getattr(self, column) for column in TASK_EVIDENCE_COLUMNS}


def extract_task_evidence(
    faq_csv: Path | str = DEFAULT_CLEAN_FAQ_CSV,
    *,
    max_per_question: int = 8,
) -> list[TaskEvidence]:
    frame = pd.read_csv(faq_csv, dtype=str, keep_default_na=False)
    required = {"question", "answer", "school", "category", "source_url"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"faq csv missing required columns: {', '.join(missing)}")

    rows: list[TaskEvidence] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row_index, row in enumerate(frame.to_dict(orient="records")):
        task_code, stage, task_confidence = infer_task_code(row)
        if not task_code:
            continue

        emitted_for_question = 0
        candidates = extract_evidence_candidates(row, task_code=task_code, stage=stage)
        for candidate_index, candidate in enumerate(candidates):
            dedupe_key = (
                row.get("school", ""),
                task_code,
                candidate["evidence_type"],
                candidate["normalized_value"],
                normalize_for_dedupe(candidate["evidence_text"]),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            rows.append(
                TaskEvidence(
                    evidence_id=(
                        f"{row.get('school', '').lower()}__{task_code}__"
                        f"{candidate['evidence_type']}__{row_index:04d}_{candidate_index:02d}"
                    ),
                    task_code=task_code,
                    school=row.get("school", ""),
                    stage=stage,
                    evidence_type=candidate["evidence_type"],
                    evidence_text=candidate["evidence_text"],
                    normalized_value=candidate["normalized_value"],
                    source_question=row.get("question", ""),
                    source_url=row.get("source_url", ""),
                    confidence=combine_confidence(task_confidence, candidate["confidence"]),
                    updated_at=datetime.now(UTC).date().isoformat(),
                )
            )
            emitted_for_question += 1
            if emitted_for_question >= max_per_question:
                break

    return rows


def infer_task_code(row: dict[str, str]) -> tuple[str, str, str]:
    question = row.get("question", "")
    answer = row.get("answer", "")
    category = row.get("category", "")
    text = f"{question} {answer}".lower()

    if "application fee" in text and "deposit" not in text and "tuition" not in text:
        return "", "", "low"

    scores: list[tuple[int, str, str]] = []
    for task_code, stage, keywords in TASK_KEYWORDS:
        score = sum(1 for keyword in keywords if keyword in text)
        if category == stage:
            score += 2
        elif category == "offer_acceptance" and stage == "offer_acceptance":
            score += 1
        if score:
            scores.append((score, task_code, stage))

    if not scores:
        return "", "", "low"

    scores.sort(reverse=True)
    score, task_code, stage = scores[0]
    confidence = "high" if score >= 4 else "medium" if score >= 2 else "low"
    return task_code, stage, confidence


def extract_evidence_candidates(
    row: dict[str, str],
    *,
    task_code: str,
    stage: str,
) -> list[dict[str, str]]:
    question = row.get("question", "")
    answer = row.get("answer", "")
    sentences = split_sentences(answer)
    candidates: list[dict[str, str]] = []

    for url in extract_urls(answer):
        candidates.append(
            {
                "evidence_type": "action_url",
                "evidence_text": url,
                "normalized_value": url,
                "confidence": "high",
            }
        )

    for fee in FEE_RE.findall(answer):
        candidates.append(
            {
                "evidence_type": "fee_amount",
                "evidence_text": fee,
                "normalized_value": fee.replace(",", ""),
                "confidence": "medium",
            }
        )

    for sentence in sentences:
        lowered = sentence.lower()
        if is_deadline_sentence(lowered):
            candidates.append(
                {
                    "evidence_type": "deadline",
                    "evidence_text": sentence,
                    "normalized_value": sentence,
                    "confidence": "medium",
                }
            )
        if is_document_sentence(lowered):
            candidates.append(
                {
                    "evidence_type": "required_document",
                    "evidence_text": sentence,
                    "normalized_value": normalize_document_hint(sentence),
                    "confidence": "medium",
                }
            )
        if is_action_sentence(lowered, task_code=task_code):
            candidates.append(
                {
                    "evidence_type": "action_instruction",
                    "evidence_text": sentence,
                    "normalized_value": sentence,
                    "confidence": "medium",
                }
            )

    if not candidates and task_code and answer:
        candidates.append(
            {
                "evidence_type": "source_context",
                "evidence_text": f"Q: {question} A: {answer[:500]}",
                "normalized_value": "",
                "confidence": "low",
            }
        )

    return candidates


def split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    rough = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])", normalized)
    return [sentence.strip(" ;") for sentence in rough if len(sentence.strip()) >= 12]


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.findall(text):
        url = match.rstrip(".")
        if url not in urls:
            urls.append(url)
    return urls


def is_deadline_sentence(lowered_sentence: str) -> bool:
    return any(pattern in lowered_sentence for pattern in DEADLINE_PATTERNS)


def is_document_sentence(lowered_sentence: str) -> bool:
    return any(pattern in lowered_sentence for pattern in DOCUMENT_PATTERNS)


def is_action_sentence(lowered_sentence: str, *, task_code: str) -> bool:
    if task_code == "pay_tuition" and "application fee" in lowered_sentence:
        return False
    return any(pattern in lowered_sentence for pattern in ACTION_PATTERNS)


def normalize_document_hint(sentence: str) -> str:
    hints = [pattern for pattern in DOCUMENT_PATTERNS if pattern in sentence.lower()]
    return "; ".join(dict.fromkeys(hints)) or sentence


def combine_confidence(task_confidence: str, evidence_confidence: str) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    value = min(order.get(task_confidence, 1), order.get(evidence_confidence, 1))
    inverse = {1: "low", 2: "medium", 3: "high"}
    return inverse[value]


def normalize_for_dedupe(value: str) -> str:
    return re.sub(r"\W+", "", value.lower())


def write_task_evidence_csv(
    evidence: list[TaskEvidence],
    output: Path | str = DEFAULT_TASK_EVIDENCE_CSV,
) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TASK_EVIDENCE_COLUMNS)
        writer.writeheader()
        for item in evidence:
            writer.writerow(item.to_row())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract task evidence from cleaned FAQ rows.")
    parser.add_argument("--faq-csv", type=Path, default=DEFAULT_CLEAN_FAQ_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_TASK_EVIDENCE_CSV)
    parser.add_argument("--max-per-question", type=int, default=8)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    evidence = extract_task_evidence(args.faq_csv, max_per_question=args.max_per_question)
    write_task_evidence_csv(evidence, args.output)
    print(f"已生成 task evidence：{len(evidence)} 条 -> {args.output}")
    if evidence:
        counts: dict[str, int] = {}
        for item in evidence:
            counts[item.evidence_type] = counts.get(item.evidence_type, 0) + 1
        for evidence_type, count in sorted(counts.items()):
            print(f"{evidence_type}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
