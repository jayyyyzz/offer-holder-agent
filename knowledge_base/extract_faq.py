"""Extract FAQ candidates from archived official-page text files."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import re
import sys

from agent.rag_retriever import DEFAULT_RAW_DIR, ROOT_DIR, parse_raw_page


DEFAULT_FAQ_CSV = ROOT_DIR / "data" / "cleaned" / "faq.csv"
FAQ_COLUMNS = [
    "question",
    "answer",
    "school",
    "stage",
    "category",
    "risk_level",
    "source_url",
    "updated_at",
]


EN_QUESTION_STARTERS = (
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
)
ZH_QUESTION_STARTERS = (
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


@dataclass(frozen=True)
class FaqItem:
    question: str
    answer: str
    school: str
    stage: str
    category: str
    risk_level: str
    source_url: str
    updated_at: str

    def to_row(self) -> dict[str, str]:
        return {column: getattr(self, column) for column in FAQ_COLUMNS}


def extract_faq_items(
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    *,
    include_all_pages: bool = False,
    school_filter: set[str] | None = None,
    min_answer_chars: int = 30,
) -> list[FaqItem]:
    items: list[FaqItem] = []
    seen: set[tuple[str, str]] = set()

    for path in sorted(Path(raw_dir).glob("*.txt")):
        metadata, body = parse_raw_page(path)
        school = metadata.get("school", "")
        if school_filter and school.lower() not in school_filter:
            continue
        if not include_all_pages and metadata.get("page_type") != "faq":
            continue

        source_url = metadata.get("source_url") or metadata.get("final_url", "")
        stage = metadata.get("stage") or metadata.get("page_type", "")
        for question, answer in extract_pairs_from_text(body, min_answer_chars=min_answer_chars):
            dedupe_key = (school.lower(), normalize_question(question))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            category = infer_category(question, answer, default=stage)
            items.append(
                FaqItem(
                    question=question,
                    answer=answer,
                    school=school,
                    stage=stage,
                    category=category,
                    risk_level=infer_risk_level(question, answer, category),
                    source_url=source_url,
                    updated_at=datetime.now(UTC).date().isoformat(),
                )
            )

    return items


def extract_pairs_from_text(text: str, *, min_answer_chars: int = 30) -> list[tuple[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    pairs: list[tuple[str, str]] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not is_question_line(line):
            index += 1
            continue

        question = clean_question(line)
        answer_lines: list[str] = []
        cursor = index + 1
        while cursor < len(lines):
            next_line = lines[cursor]
            if is_question_line(next_line):
                break
            if not is_probably_navigation_line(next_line):
                answer_lines.append(next_line)
            if len(" ".join(answer_lines)) >= 1400 or len(answer_lines) >= 14:
                break
            cursor += 1

        answer = clean_answer(" ".join(answer_lines))
        if len(answer) >= min_answer_chars and len(question) >= 5:
            pairs.append((question, answer))
        index = max(cursor, index + 1)

    return pairs


def is_question_line(line: str) -> bool:
    text = clean_question(line)
    if len(text) < 5 or len(text) > 240:
        return False
    lowered = text.lower().strip()

    if re.match(r"^(q|question|問|问)\s*[:：.)-]", lowered):
        return True
    if lowered.endswith("?") or lowered.endswith("？"):
        return True
    if lowered.startswith("if "):
        return False
    if any(lowered.startswith(starter + " ") for starter in EN_QUESTION_STARTERS):
        return True
    if any(text.startswith(starter) for starter in ZH_QUESTION_STARTERS):
        return True
    if re.match(r"^\d{1,2}[.)]\s+", lowered):
        stripped = re.sub(r"^\d{1,2}[.)]\s+", "", lowered)
        return any(stripped.startswith(starter + " ") for starter in EN_QUESTION_STARTERS)
    return False


def clean_question(line: str) -> str:
    text = re.sub(r"^\s*(q|question|問|问)\s*[:：.)-]\s*", "", line, flags=re.I)
    text = re.sub(r"^\s*\d{1,2}[.)]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_answer(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1600]


def is_probably_navigation_line(line: str) -> bool:
    lowered = line.lower()
    nav_terms = {
        "back to top",
        "share",
        "print",
        "download",
        "previous",
        "next",
        "home",
        "menu",
    }
    return lowered in nav_terms or is_probably_section_heading(line) or len(line) <= 2


def is_probably_section_heading(line: str) -> bool:
    cleaned = re.sub(r"\s+", " ", line).strip().lower()
    headings = {
        "offer acceptance",
        "accept the offer",
        "supporting documents",
        "student visa/ entry permit",
        "student visa / entry permit",
        "application procedures",
        "visa application procedures",
        "accommodation",
        "tuition fee",
        "registration",
        "orientation",
    }
    return cleaned in headings


def infer_category(question: str, answer: str, *, default: str = "general") -> str:
    text = f"{question} {answer}".lower()
    mapping = {
        "visa": ("visa", "entry permit", "immigration", "id995", "签证", "进入许可", "入境"),
        "offer_acceptance": ("offer", "acceptance", "deposit", "conditional", "留位费", "录取"),
        "housing": ("housing", "accommodation", "hostel", "hall", "宿舍", "住宿"),
        "payment": ("tuition", "fee", "payment", "pay", "学费", "缴费", "付款"),
        "registration": ("registration", "enrolment", "enrollment", "注册", "学籍", "账号"),
        "orientation": ("orientation", "arrival", "welcome", "迎新", "到港", "开学"),
    }
    for category, keywords in mapping.items():
        if any(keyword in text for keyword in keywords):
            return category
    return default or "general"


def infer_risk_level(question: str, answer: str, category: str) -> str:
    text = f"{question} {answer}".lower()
    high_terms = (
        "deadline",
        "late",
        "overdue",
        "visa",
        "entry permit",
        "conditional",
        "deposit",
        "official document",
        "截止",
        "逾期",
        "签证",
        "进入许可",
        "留位费",
        "条件",
    )
    if category in {"visa", "offer_acceptance", "registration"} or any(
        term in text for term in high_terms
    ):
        return "high"
    if category in {"housing", "payment", "orientation"}:
        return "medium"
    return "low"


def normalize_question(question: str) -> str:
    return re.sub(r"\W+", "", question.lower())


def write_faq_csv(items: list[FaqItem], output: Path | str = DEFAULT_FAQ_CSV) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FAQ_COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow(item.to_row())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract FAQ candidates from raw official pages.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_FAQ_CSV)
    parser.add_argument("--all-pages", action="store_true", help="Scan all page types, not only FAQ pages")
    parser.add_argument("--school", action="append", help="Filter by school; repeatable")
    parser.add_argument("--min-answer-chars", type=int, default=30)
    parser.add_argument("--limit", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    school_filter = {school.lower() for school in args.school} if args.school else None
    items = extract_faq_items(
        args.raw_dir,
        include_all_pages=args.all_pages,
        school_filter=school_filter,
        min_answer_chars=args.min_answer_chars,
    )
    if args.limit:
        items = items[: args.limit]
    write_faq_csv(items, args.output)
    print(f"已抽取 FAQ 候选：{len(items)} 条 -> {args.output}")
    if items:
        counts: dict[str, int] = {}
        for item in items:
            counts[item.category] = counts.get(item.category, 0) + 1
        for category, count in sorted(counts.items()):
            print(f"{category}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
