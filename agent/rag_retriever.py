"""Local evidence retrieval over crawled official pages.

This is a small, dependency-light retrieval layer. It is intentionally not a
vector database yet: the first agent should be auditable by reading the code
and the generated ``knowledge_base/chunks.csv`` file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import csv
import hashlib
import re
from typing import Iterable

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT_DIR / "data" / "raw_pages"
DEFAULT_CHUNKS_CSV = ROOT_DIR / "knowledge_base" / "chunks.csv"
DEFAULT_CLEAN_FAQ_CSV = ROOT_DIR / "data" / "cleaned" / "faq_cleaned.csv"


CHUNK_COLUMNS = [
    "chunk_id",
    "school",
    "page_type",
    "stage",
    "title",
    "source_url",
    "final_url",
    "raw_file",
    "chunk_index",
    "text",
    "updated_at",
]


QUERY_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "签证": ("visa", "entry permit", "immigration", "non-local", "id995a"),
    "簽證": ("visa", "entry permit", "immigration", "non-local", "id995a"),
    "进入许可": ("entry permit", "visa", "immigration"),
    "進入許可": ("entry permit", "visa", "immigration"),
    "学生签": ("student visa", "entry permit", "immigration"),
    "學生簽": ("student visa", "entry permit", "immigration"),
    "入境": ("entry permit", "arrival", "immigration", "non-local"),
    "留位费": ("deposit", "acceptance", "offer", "payment"),
    "留位費": ("deposit", "acceptance", "offer", "payment"),
    "接受offer": ("accept offer", "acceptance", "admission offer", "deposit"),
    "接受 offer": ("accept offer", "acceptance", "admission offer", "deposit"),
    "录取": ("admission", "offer", "acceptance"),
    "錄取": ("admission", "offer", "acceptance"),
    "conditional": ("conditional offer", "official documents", "transcript"),
    "条件": ("conditional offer", "official documents", "transcript"),
    "條件": ("conditional offer", "official documents", "transcript"),
    "补交": ("official documents", "transcript", "certificate", "conditional"),
    "補交": ("official documents", "transcript", "certificate", "conditional"),
    "材料": ("documents", "official documents", "transcript", "certificate"),
    "成绩单": ("transcript", "official transcript", "academic transcript"),
    "成績單": ("transcript", "official transcript", "academic transcript"),
    "毕业证": ("graduation certificate", "certificate", "degree certificate"),
    "畢業證": ("graduation certificate", "certificate", "degree certificate"),
    "学位证": ("degree certificate", "certificate", "degree"),
    "學位證": ("degree certificate", "certificate", "degree"),
    "语言成绩": ("language result", "english test", "ielts", "toefl"),
    "語言成績": ("language result", "english test", "ielts", "toefl"),
    "认证": ("verification", "certification", "official document"),
    "認證": ("verification", "certification", "official document"),
    "宿舍": ("housing", "accommodation", "hostel", "hall", "residence"),
    "住宿": ("housing", "accommodation", "hostel", "hall", "residence"),
    "学费": ("tuition", "fee", "payment"),
    "學費": ("tuition", "fee", "payment"),
    "缴费": ("tuition", "fee", "payment", "pay"),
    "繳費": ("tuition", "fee", "payment", "pay"),
    "付款": ("payment", "pay", "tuition", "fee"),
    "注册": ("registration", "enrolment", "enrollment", "student account"),
    "註冊": ("registration", "enrolment", "enrollment", "student account"),
    "选课": ("enrolment", "course", "registration"),
    "選課": ("enrolment", "course", "registration"),
    "迎新": ("orientation", "welcome", "induction"),
    "开学": ("orientation", "arrival", "registration"),
    "開學": ("orientation", "arrival", "registration"),
    "到港": ("arrival", "orientation", "non-local"),
}


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "may",
    "must",
    "of",
    "on",
    "or",
    "please",
    "should",
    "the",
    "there",
    "this",
    "to",
    "what",
    "when",
    "where",
    "who",
    "why",
    "will",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    school: str
    page_type: str
    stage: str
    title: str
    source_url: str
    final_url: str
    raw_file: str
    chunk_index: int
    text: str
    updated_at: str


@dataclass(frozen=True)
class RetrievalResult:
    chunk: DocumentChunk
    score: float
    matched_terms: tuple[str, ...]

    @property
    def source_url(self) -> str:
        return self.chunk.source_url or self.chunk.final_url


class LocalRagRetriever:
    """Search official-page chunks from local CSV or raw text files."""

    def __init__(
        self,
        raw_dir: Path | str = DEFAULT_RAW_DIR,
        chunks_csv: Path | str = DEFAULT_CHUNKS_CSV,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.chunks_csv = Path(chunks_csv)
        self._chunks: list[DocumentChunk] | None = None

    def load_chunks(self) -> list[DocumentChunk]:
        if self._chunks is not None:
            return self._chunks

        if self.chunks_csv.exists():
            self._chunks = _read_chunks_csv(self.chunks_csv)
        else:
            self._chunks = build_chunks_from_raw(self.raw_dir)

        return self._chunks

    def search(
        self,
        query: str,
        *,
        school: str | None = None,
        page_types: Iterable[str] | None = None,
        stage: str | None = None,
        top_k: int = 5,
        min_score: float = 1.0,
    ) -> list[RetrievalResult]:
        chunks = self.load_chunks()
        page_type_set = {item.lower() for item in page_types or []}
        query_terms = expand_query_terms(query)

        results: list[RetrievalResult] = []
        for chunk in chunks:
            score, matched = score_chunk(
                chunk,
                query_terms=query_terms,
                school=school,
                page_types=page_type_set,
                stage=stage,
            )
            if matched and score >= min_score:
                results.append(RetrievalResult(chunk=chunk, score=score, matched_terms=matched))

        results.sort(
            key=lambda item: (
                item.score,
                item.chunk.school.lower() == (school or "").lower(),
                -item.chunk.chunk_index,
            ),
            reverse=True,
        )
        return results[:top_k]

    def export_chunks(
        self,
        output_path: Path | str | None = None,
        *,
        faq_csv: Path | str | None = None,
    ) -> list[DocumentChunk]:
        chunks = build_chunks_from_raw(self.raw_dir, faq_csv=faq_csv)
        output = Path(output_path) if output_path else self.chunks_csv
        write_chunks_csv(chunks, output)
        self._chunks = chunks
        return chunks


def build_chunks_from_raw(
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    *,
    faq_csv: Path | str | None = None,
) -> list[DocumentChunk]:
    raw_path = Path(raw_dir)
    chunks: list[DocumentChunk] = []

    for file_path in sorted(raw_path.glob("*.txt")):
        if file_path.name == ".gitkeep":
            continue
        metadata, body = parse_raw_page(file_path)
        for index, text in enumerate(split_text(body)):
            chunk_id = _chunk_id(file_path, index)
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    school=metadata.get("school", ""),
                    page_type=metadata.get("page_type", ""),
                    stage=metadata.get("stage", ""),
                    title=metadata.get("title", ""),
                    source_url=metadata.get("source_url", ""),
                    final_url=metadata.get("final_url", ""),
                    raw_file=_relative_path(file_path),
                    chunk_index=index,
                    text=text,
                    updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
                )
            )

    if faq_csv:
        chunks.extend(build_chunks_from_cleaned_faq(faq_csv))

    return chunks


def build_chunks_from_cleaned_faq(faq_csv: Path | str = DEFAULT_CLEAN_FAQ_CSV) -> list[DocumentChunk]:
    path = Path(faq_csv)
    if not path.exists() or path.stat().st_size == 0:
        return []

    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {"question", "answer", "school", "stage", "category", "source_url", "updated_at"}
    if not required.issubset(frame.columns):
        return []

    chunks: list[DocumentChunk] = []
    for index, row in enumerate(frame.to_dict(orient="records")):
        question = row.get("question", "").strip()
        answer = row.get("answer", "").strip()
        if not question or not answer:
            continue
        text = f"Question: {question}\nAnswer: {answer}"
        source_url = row.get("source_url", "")
        digest = hashlib.sha1(
            f"{row.get('school', '')}|{question}|{source_url}".encode("utf-8")
        ).hexdigest()[:12]
        chunks.append(
            DocumentChunk(
                chunk_id=f"faq_cleaned__{safe_chunk_part(row.get('school', ''))}__{digest}",
                school=row.get("school", ""),
                page_type="faq_cleaned",
                stage=row.get("stage", ""),
                title=question[:500],
                source_url=source_url,
                final_url=source_url,
                raw_file=_relative_path(path),
                chunk_index=index,
                text=text,
                updated_at=row.get("updated_at") or datetime.now(UTC).isoformat(timespec="seconds"),
            )
        )
    return chunks


def parse_raw_page(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if "\n---\n" not in text:
        return {}, text

    header, body = text.split("\n---\n", 1)
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata, body.strip()


def split_text(text: str, *, max_chars: int = 900, overlap_chars: int = 120) -> list[str]:
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            tail = current[-overlap_chars:] if overlap_chars > 0 else ""
            current = f"{tail}\n{paragraph}".strip()
        else:
            chunks.append(paragraph[:max_chars])
            current = paragraph[max_chars - overlap_chars :]

    if current:
        chunks.append(current)

    return chunks


def expand_query_terms(query: str) -> set[str]:
    lowered = query.lower()
    terms = set(_tokenize(lowered))

    for chinese_key, expansions in QUERY_EXPANSIONS.items():
        if chinese_key.lower() in lowered:
            for expansion in expansions:
                terms.update(_tokenize(expansion))

    for phrase in ("entry permit", "student visa", "accept offer", "official documents"):
        if phrase in lowered:
            terms.update(_tokenize(phrase))

    return {term for term in terms if len(term) > 1}


def score_chunk(
    chunk: DocumentChunk,
    *,
    query_terms: set[str],
    school: str | None = None,
    page_types: set[str] | None = None,
    stage: str | None = None,
) -> tuple[float, tuple[str, ...]]:
    content_text = " ".join(
        [
            chunk.title,
            chunk.text,
        ]
    ).lower()
    chunk_terms = set(_tokenize(content_text))
    matched = tuple(sorted(query_terms & chunk_terms))

    if not query_terms or not matched:
        return 0.0, ()

    score = float(len(matched))

    if school and chunk.school.lower() == school.lower():
        score += 4.0
    if page_types and chunk.page_type.lower() in page_types:
        score += 3.0
    if stage and chunk.stage.lower() == stage.lower():
        score += 2.0

    exact_phrase_bonus = _exact_phrase_bonus(content_text, query_terms)
    score += exact_phrase_bonus

    if chunk.page_type == "faq_cleaned":
        score += 0.6
    elif chunk.page_type == "faq":
        score += 0.3

    return score, matched


def write_chunks_csv(chunks: list[DocumentChunk], output_path: Path | str) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHUNK_COLUMNS)
        writer.writeheader()
        for chunk in chunks:
            writer.writerow({column: getattr(chunk, column) for column in CHUNK_COLUMNS})


def _read_chunks_csv(path: Path) -> list[DocumentChunk]:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in CHUNK_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"chunks csv missing required columns: {', '.join(missing)}")

    chunks: list[DocumentChunk] = []
    for row in frame.to_dict(orient="records"):
        chunks.append(
            DocumentChunk(
                chunk_id=row["chunk_id"],
                school=row["school"],
                page_type=row["page_type"],
                stage=row["stage"],
                title=row["title"],
                source_url=row["source_url"],
                final_url=row["final_url"],
                raw_file=row["raw_file"],
                chunk_index=int(row["chunk_index"] or 0),
                text=row["text"],
                updated_at=row["updated_at"],
            )
        )
    return chunks


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in STOPWORDS and len(token) > 1
    ]


def _exact_phrase_bonus(chunk_text: str, query_terms: set[str]) -> float:
    bonus = 0.0
    high_value_terms = {"visa", "permit", "deposit", "tuition", "registration", "housing"}
    for term in query_terms & high_value_terms:
        if term in chunk_text:
            bonus += 0.4
    return bonus


def _chunk_id(path: Path, index: int) -> str:
    return f"{path.stem}__chunk_{index:03d}"


def safe_chunk_part(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower())
    return text.strip("_") or "item"


def _relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return path.as_posix()
