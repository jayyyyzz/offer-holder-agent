"""Clean and score FAQ candidates extracted from official pages."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import re
import sys

import pandas as pd

from knowledge_base.extract_faq import DEFAULT_FAQ_CSV, FAQ_COLUMNS


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CLEAN_FAQ_CSV = ROOT_DIR / "data" / "cleaned" / "faq_cleaned.csv"
DEFAULT_FAQ_QUALITY_REPORT = ROOT_DIR / "data" / "metadata" / "faq_quality_report.csv"


QUALITY_COLUMNS = FAQ_COLUMNS + [
    "cleaned_question",
    "cleaned_answer",
    "quality_score",
    "decision",
    "quality_notes",
]


QUESTION_STARTERS = (
    "what",
    "when",
    "where",
    "who",
    "why",
    "how",
    "can",
    "could",
    "do",
    "does",
    "is",
    "are",
    "should",
    "will",
    "would",
    "may",
    "must",
    "if",
    "am",
    "which",
)
CHINESE_QUESTION_MARKERS = (
    "如何",
    "怎样",
    "怎么",
    "是否",
    "能否",
    "可以",
    "需要",
    "什么时候",
    "何时",
    "哪里",
    "哪个",
    "如果",
    "为何",
    "为什么",
    "多久",
    "多少",
    "谁",
)
FRAGMENT_STARTERS = (
    "where ",
    "are ",
    "and ",
    "or ",
    "but ",
    "with ",
    "without ",
    "for ",
    "from ",
    "that ",
    "which ",
)
NAVIGATION_TERMS = {
    "home",
    "menu",
    "previous",
    "next",
    "back to top",
    "read more",
    "learn more",
    "apply now",
    "for details",
}


@dataclass(frozen=True)
class FaqQualityResult:
    original: dict[str, str]
    cleaned_question: str
    cleaned_answer: str
    quality_score: int
    decision: str
    quality_notes: tuple[str, ...]

    def cleaned_row(self) -> dict[str, str]:
        row = {column: self.original.get(column, "") for column in FAQ_COLUMNS}
        row["question"] = self.cleaned_question
        row["answer"] = self.cleaned_answer
        return row

    def quality_row(self) -> dict[str, str]:
        row = {column: self.original.get(column, "") for column in FAQ_COLUMNS}
        row.update(
            {
                "cleaned_question": self.cleaned_question,
                "cleaned_answer": self.cleaned_answer,
                "quality_score": str(self.quality_score),
                "decision": self.decision,
                "quality_notes": "; ".join(self.quality_notes),
            }
        )
        return row


def clean_faq_candidates(
    input_csv: Path | str = DEFAULT_FAQ_CSV,
    *,
    min_score: int = 65,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    frame = pd.read_csv(input_csv, dtype=str, keep_default_na=False)
    missing = [column for column in FAQ_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"faq csv missing required columns: {', '.join(missing)}")

    results: list[FaqQualityResult] = []
    seen_keys: set[tuple[str, str]] = set()
    for row in frame[FAQ_COLUMNS].to_dict(orient="records"):
        result = score_faq_row(row)
        dedupe_key = (
            result.original.get("school", "").strip().lower(),
            normalize_for_dedupe(result.cleaned_question),
        )
        notes = list(result.quality_notes)
        decision = result.decision
        score = result.quality_score
        if dedupe_key in seen_keys:
            decision = "reject"
            score = min(score, 40)
            notes.append("duplicate_question_for_school")
        else:
            seen_keys.add(dedupe_key)

        if decision != "reject" and score < min_score:
            decision = "review"
        results.append(
            FaqQualityResult(
                original=result.original,
                cleaned_question=result.cleaned_question,
                cleaned_answer=result.cleaned_answer,
                quality_score=score,
                decision=decision,
                quality_notes=tuple(dict.fromkeys(notes)),
            )
        )

    cleaned_rows = [
        result.cleaned_row()
        for result in results
        if result.decision == "keep" and result.quality_score >= min_score
    ]
    quality_rows = [result.quality_row() for result in results]
    return cleaned_rows, quality_rows


def score_faq_row(row: dict[str, str]) -> FaqQualityResult:
    question = clean_question_text(row.get("question", ""))
    answer = clean_answer_text(row.get("answer", ""))
    score = 100
    notes: list[str] = []

    q_len = len(question)
    a_len = len(answer)
    if q_len < 10:
        score -= 45
        notes.append("question_too_short")
    if q_len > 220:
        score -= 20
        notes.append("question_very_long")
    if a_len < 45:
        score -= 40
        notes.append("answer_too_short")
    elif a_len < 80:
        score -= 15
        notes.append("answer_short")
    if a_len > 1400:
        score -= 5
        notes.append("answer_long")

    if not looks_like_question(question):
        score -= 35
        notes.append("question_shape_suspicious")
    if looks_like_fragment(question):
        score -= 45
        notes.append("question_fragment")
    if contains_template_noise(question) or contains_template_noise(answer):
        score -= 55
        notes.append("template_or_navigation_noise")
    if mostly_navigation(answer):
        score -= 60
        notes.append("answer_looks_like_navigation")
    if is_broad_navigation_question(question):
        score -= 60
        notes.append("broad_navigation_question")
    if not row.get("source_url", "").startswith("http"):
        score -= 10
        notes.append("missing_source_url")

    decision = "keep"
    if (
        score < 50
        or "template_or_navigation_noise" in notes
        or "question_fragment" in notes
        or "broad_navigation_question" in notes
    ):
        decision = "reject"

    return FaqQualityResult(
        original={column: row.get(column, "") for column in FAQ_COLUMNS},
        cleaned_question=question,
        cleaned_answer=answer,
        quality_score=max(0, min(100, score)),
        decision=decision,
        quality_notes=tuple(dict.fromkeys(notes)),
    )


def clean_question_text(value: str) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"^(q|question|問|问)\s*\d{0,3}\s*[:：.)-]\s*", "", text, flags=re.I)
    text = re.sub(r"^[A-Z]\d{1,2}[.)]\s*", "", text)
    text = re.sub(r"^\d{1,2}[.)]\s*", "", text)
    text = re.sub(r"\s*\(https?://[^)]+\)\s*$", "", text, flags=re.I)
    return text.strip()


def clean_answer_text(value: str) -> str:
    text = normalize_whitespace(value)
    text = re.sub(r"\s+(Back to top|Previous|Next)\s*$", "", text, flags=re.I)
    return text.strip()


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def looks_like_question(question: str) -> bool:
    lowered = question.lower().strip()
    if question.endswith(("?", "？")):
        return True
    if any(lowered.startswith(starter + " ") for starter in QUESTION_STARTERS):
        return True
    if any(question.startswith(marker) for marker in CHINESE_QUESTION_MARKERS):
        return True
    return False


def looks_like_fragment(question: str) -> bool:
    lowered = question.lower().strip()
    if any(lowered.startswith(starter) for starter in FRAGMENT_STARTERS):
        return not question.endswith(("?", "？"))
    if question.endswith((" from the", " by the", " for the", " from")):
        return True
    return False


def contains_template_noise(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "${content}",
            "${maincatcurrent}",
            "${subcatcurrent}",
            "safeLine".lower(),
            "page not found",
        )
    )


def mostly_navigation(answer: str) -> bool:
    lowered = answer.lower().strip()
    if lowered in NAVIGATION_TERMS:
        return True
    words = re.findall(r"[a-zA-Z]+", lowered)
    if not words:
        return False
    nav_hits = sum(1 for word in words if word in NAVIGATION_TERMS)
    return nav_hits >= 3 and len(words) <= 12


def is_broad_navigation_question(question: str) -> bool:
    lowered = question.lower().strip(" ?")
    broad_questions = {
        "why hkbu",
        "why choose hkbu",
        "why hong kong baptist university",
    }
    return lowered in broad_questions


def normalize_for_dedupe(question: str) -> str:
    return re.sub(r"\W+", "", question.lower())


def write_clean_faq(rows: list[dict[str, str]], output: Path | str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FAQ_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_quality_report(rows: list[dict[str, str]], output: Path | str) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUALITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean extracted FAQ candidates.")
    parser.add_argument("--input", type=Path, default=DEFAULT_FAQ_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_CLEAN_FAQ_CSV)
    parser.add_argument("--quality-report", type=Path, default=DEFAULT_FAQ_QUALITY_REPORT)
    parser.add_argument("--min-score", type=int, default=65)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    cleaned_rows, quality_rows = clean_faq_candidates(args.input, min_score=args.min_score)
    write_clean_faq(cleaned_rows, args.output)
    write_quality_report(quality_rows, args.quality_report)

    decisions = pd.Series([row["decision"] for row in quality_rows]).value_counts()
    print(f"已生成 cleaned FAQ：{len(cleaned_rows)} 条 -> {args.output}")
    print(f"已生成 FAQ quality report：{len(quality_rows)} 条 -> {args.quality_report}")
    print(decisions.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
