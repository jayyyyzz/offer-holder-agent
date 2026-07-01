"""Prepare auditable Phase 1 data catalog outputs.

This module ties together the later Phase 1 deliverables:

3. raw official text archives
4. crawl logs and latest crawl summaries
5. cleaned FAQ/task tables
6. data structures for future RAG and task planning

It does not crawl the web and does not overwrite the core data tables.  The
outputs are metadata/catalog files that make the current archive easier to
review and easier to consume in the next stage.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Iterable

import pandas as pd

from agent.rag_retriever import DEFAULT_CHUNKS_CSV
from agent.task_planner import DEFAULT_SCHOOLS_CSV, DEFAULT_TASKS_CSV, TASK_COLUMNS
from crawler.crawl_pages import (
    DEFAULT_LOG_PATH,
    DEFAULT_RAW_DIR,
    DEFAULT_SOURCE_LIST,
    LOG_COLUMNS,
    SOURCE_COLUMNS,
    ROOT_DIR,
)
from crawler.summarize_crawl import DEFAULT_SUMMARY_PATH, SUMMARY_COLUMNS
from knowledge_base.audit_data_quality import DEFAULT_QUALITY_REPORT, QUALITY_COLUMNS
from knowledge_base.clean_faq import DEFAULT_CLEAN_FAQ_CSV, DEFAULT_FAQ_QUALITY_REPORT
from knowledge_base.extract_faq import DEFAULT_FAQ_CSV, FAQ_COLUMNS
from knowledge_base.extract_task_evidence import (
    DEFAULT_TASK_EVIDENCE_CSV,
    TASK_EVIDENCE_COLUMNS,
)
from knowledge_base.audit_task_evidence_quality import (
    DEFAULT_TASK_EVIDENCE_QUALITY_REPORT,
    TASK_EVIDENCE_QUALITY_COLUMNS,
)
from knowledge_base.enrich_tasks import DEFAULT_TASKS_ENRICHED_CSV, TASK_ENRICHED_COLUMNS
from knowledge_base.review_enriched_tasks import DEFAULT_TASK_REVIEW_REPORT, TASK_REVIEW_COLUMNS
from knowledge_base.reviewed_tasks import (
    DEFAULT_TASK_REVIEW_DECISIONS_CSV,
    DEFAULT_TASKS_REVIEWED_CSV,
    TASK_REVIEW_DECISION_COLUMNS,
    TASK_REVIEWED_COLUMNS,
)
from knowledge_base.vector_index import DEFAULT_VECTOR_INDEX_CSV, VECTOR_INDEX_COLUMNS
from agent.user_state import DEFAULT_USER_STATE_CSV, USER_STATE_COLUMNS
from agent.task_state import DEFAULT_USER_TASK_STATE_CSV, USER_TASK_STATE_COLUMNS


DEFAULT_RAW_PAGE_INDEX = ROOT_DIR / "data" / "metadata" / "raw_page_index.csv"
DEFAULT_PHASE1_MANIFEST = ROOT_DIR / "data" / "metadata" / "phase1_manifest.csv"
DEFAULT_SCHEMA_DICTIONARY = ROOT_DIR / "data" / "metadata" / "schema_dictionary.csv"


RAW_PAGE_INDEX_COLUMNS = [
    "raw_file",
    "school",
    "page_type",
    "stage",
    "source_url",
    "final_url",
    "title",
    "content_type",
    "extraction_method",
    "crawled_at",
    "body_char_count",
    "total_char_count",
    "line_count",
]


MANIFEST_COLUMNS = [
    "artifact",
    "path",
    "category",
    "exists",
    "row_count",
    "file_count",
    "updated_at",
    "notes",
]


SCHEMA_DICTIONARY_COLUMNS = [
    "dataset",
    "column",
    "required",
    "description",
]


SCHEMA_DESCRIPTIONS = {
    "school": "School code, e.g. HKU, CUHK, HKUST, CityU, PolyU, HKBU.",
    "page_type": "Official page category, e.g. offer_holder, visa, accommodation, tuition, registration, orientation, faq.",
    "stage": "Offer-holder preparation stage used by the planner and retriever.",
    "url": "Official source URL from the school website.",
    "source_url": "Original official URL used as evidence source.",
    "final_url": "Final URL after redirects.",
    "priority": "Crawl priority; lower number means more important.",
    "need_dynamic": "Whether the page usually needs browser rendering.",
    "remark": "Human note about the source.",
    "status": "Crawler result status such as success, soft_blocked, request_error, or skipped_exists.",
    "http_status": "HTTP status returned by the source server.",
    "title": "Page title or inferred document title.",
    "crawled_at": "Timestamp when the page was archived.",
    "raw_file": "Relative path to the archived raw text file.",
    "content_type": "Detected response content type.",
    "char_count": "Text character count recorded during crawling.",
    "elapsed_ms": "Crawl duration in milliseconds.",
    "error": "Crawler error or attention reason.",
    "task_id": "Stable task identifier, usually school plus task code.",
    "task_name": "User-facing task name.",
    "description": "Task explanation shown to the student.",
    "trigger_condition": "Student state that makes the task relevant.",
    "deadline": "Deadline rule or official deadline evidence.",
    "required_documents": "Documents the student may need to prepare.",
    "action_url": "Official URL where the user should act or read instructions.",
    "risk_level": "Risk severity: high, medium, or low.",
    "updated_at": "Date or timestamp when the row was generated.",
    "question": "FAQ question.",
    "answer": "FAQ answer.",
    "category": "FAQ category inferred from the question and answer.",
    "risk_level": "Risk severity: high, medium, or low.",
    "evidence_id": "Stable evidence identifier.",
    "task_code": "Task template code inferred from official text.",
    "evidence_count": "Number of evidence rows matched to the task.",
    "candidate_evidence_count": "Number of candidate evidence rows before quality filtering.",
    "usable_evidence_count": "Number of evidence rows promoted into official task fields.",
    "review_evidence_count": "Number of evidence rows that need human review or are missing an audit decision.",
    "rejected_evidence_count": "Number of evidence rows rejected by the quality audit.",
    "evidence_types": "Evidence types matched to the task.",
    "official_deadline_evidence": "Official snippets related to deadlines.",
    "official_document_evidence": "Official snippets related to required documents.",
    "official_action_evidence": "Official snippets related to actions the student should take.",
    "official_action_urls": "Official URLs extracted from task evidence.",
    "official_fee_evidence": "Official snippets related to fees or payment amounts.",
    "evidence_ids": "Evidence row identifiers matched to the task.",
    "evidence_quality_status": "Whether task evidence quality filtering was applied.",
    "evidence_quality_notes": "Compact count summary from the task evidence quality audit.",
    "enrichment_status": "Whether official evidence was matched to the task row.",
    "enriched_at": "Date when the enriched task row was generated.",
    "review_priority": "Human-review priority for enriched task evidence, such as high or medium.",
    "review_reason": "Why this task row was routed into human review.",
    "suggested_action": "Suggested manual review action for the reviewer.",
    "generated_at": "Date when the review report row was generated.",
    "reviewer_decision": "Human decision for reviewed evidence: approve, approve_with_edits, or reject.",
    "reviewed_deadline_evidence": "Human-confirmed deadline evidence text.",
    "reviewed_document_evidence": "Human-confirmed document evidence text.",
    "reviewed_action_evidence": "Human-confirmed action evidence text.",
    "reviewed_action_urls": "Human-confirmed action URLs.",
    "reviewed_fee_evidence": "Human-confirmed fee evidence text.",
    "reviewer_notes": "Free-form reviewer notes recorded during review.",
    "review_decision": "Decision copied into the final reviewed task row.",
    "review_notes": "Reviewer notes copied into the final reviewed task row.",
    "human_review_status": "Whether human review was not required, pending, approved, or rejected.",
    "evidence_type": "Type of extracted task evidence such as deadline, required_document, action_url, fee_amount, or action_instruction.",
    "evidence_text": "Official-source snippet that supports the task field.",
    "normalized_value": "Normalized value extracted from the evidence when available.",
    "source_question": "FAQ question that produced the evidence.",
    "confidence": "Rule-based confidence label for the evidence row.",
    "text_char_count": "Character count of the audited evidence text.",
    "task_keyword_hit_count": "Number of task-specific keywords found in the evidence row.",
    "field_keyword_hit_count": "Number of field-specific keywords found in the evidence row.",
    "source_stage_match": "Whether the source page type or stage matches the inferred task.",
    "source_page_type": "Page type recorded in source_list.csv for the evidence source URL.",
    "normalized_value_present": "Whether the evidence row contains a normalized value.",
    "low_quality_flags": "Rule-based flags such as admission_noise, navigation_noise, or source_context_only.",
    "quality_score": "Rule-based evidence quality score from 0 to 100.",
    "quality_decision": "Quality decision for promotion into task fields: keep, review, or reject.",
    "reviewed_at": "Date when the quality audit was generated.",
    "chunk_id": "Retrieval chunk identifier.",
    "chunk_index": "Index of the chunk within one raw file.",
    "text": "Retrieval text content.",
    "token_count": "Total token frequency count stored in the sparse vector.",
    "vector_json": "JSON object storing sparse term-frequency weights.",
    "school_id": "Canonical school code.",
    "school_name": "Full school name.",
    "official_website": "School official website.",
    "offer_holder_url": "Official offer-holder or admissions URL.",
    "admitted_student_url": "Official admitted/new student URL.",
    "visa_url": "Official student visa or entry permit URL.",
    "accommodation_url": "Official accommodation URL.",
    "tuition_url": "Official tuition/fees/payment URL.",
    "orientation_url": "Official orientation or arrival URL.",
    "user_id": "Local user state identifier.",
    "origin": "Student origin, e.g. Mainland China.",
    "program_type": "Program type, e.g. TPG.",
    "has_conditional_offer": "Whether the student has a conditional offer.",
    "completed_flags": "Semicolon-separated completed task flags.",
    "status_updated_at": "Timestamp when a user task status was last updated.",
    "deadline_at": "User-confirmed task deadline from portal, offer letter, or school email.",
    "deadline_timezone": "Timezone attached to the user-confirmed deadline.",
    "deadline_source": "Where the user-confirmed deadline came from.",
    "deadline_source_ref": "Optional URL or note identifying the deadline source.",
    "reminder_at": "User reminder timestamp.",
    "reminder_timezone": "Timezone attached to the reminder timestamp.",
    "reminder_status": "Reminder state such as pending, sent, dismissed, or disabled.",
    "notes": "Human note for the row.",
}


def build_raw_page_index(raw_dir: Path | str = DEFAULT_RAW_DIR) -> pd.DataFrame:
    """Index archived raw text files and their header metadata."""

    rows: list[dict[str, object]] = []
    for path in sorted(Path(raw_dir).glob("*.txt")):
        if path.name == ".gitkeep":
            continue
        header, body = read_raw_page_parts(path)
        rows.append(
            {
                "raw_file": path.relative_to(ROOT_DIR).as_posix()
                if path.is_relative_to(ROOT_DIR)
                else path.as_posix(),
                "school": header.get("school", ""),
                "page_type": header.get("page_type", ""),
                "stage": header.get("stage", ""),
                "source_url": header.get("source_url", ""),
                "final_url": header.get("final_url", ""),
                "title": header.get("title", ""),
                "content_type": header.get("content_type", ""),
                "extraction_method": header.get("extraction_method", ""),
                "crawled_at": header.get("crawled_at", ""),
                "body_char_count": len(body),
                "total_char_count": path.stat().st_size,
                "line_count": len(body.splitlines()),
            }
        )
    return pd.DataFrame(rows, columns=RAW_PAGE_INDEX_COLUMNS)


def read_raw_page_parts(path: Path) -> tuple[dict[str, str], str]:
    """Read the metadata header and body from one raw page text file."""

    text = path.read_text(encoding="utf-8")
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


def build_phase1_manifest(root: Path | str = ROOT_DIR) -> pd.DataFrame:
    """Create a manifest of Phase 1 inputs, outputs, and metadata tables."""

    root_path = Path(root)
    targets = [
        ("source_list", DEFAULT_SOURCE_LIST, "input", "Official source registry."),
        ("raw_pages", DEFAULT_RAW_DIR, "archive", "Archived official-page text files."),
        ("crawl_log", DEFAULT_LOG_PATH, "crawl", "Append-only crawl attempt log."),
        ("crawl_summary", DEFAULT_SUMMARY_PATH, "crawl", "Latest status per source URL."),
        ("data_quality_report", DEFAULT_QUALITY_REPORT, "quality", "Coverage audit across sources, raw pages, chunks, FAQ, and tasks."),
        ("faq_quality_report", DEFAULT_FAQ_QUALITY_REPORT, "quality", "FAQ candidate quality decisions."),
        ("task_evidence_quality_report", DEFAULT_TASK_EVIDENCE_QUALITY_REPORT, "quality", "Task evidence keep/review/reject decisions before enriching tasks."),
        ("schools", DEFAULT_SCHOOLS_CSV, "cleaned", "School-level URL catalog."),
        ("tasks", DEFAULT_TASKS_CSV, "cleaned", "Seed task templates."),
        ("tasks_enriched", DEFAULT_TASKS_ENRICHED_CSV, "cleaned", "Task templates joined with official-source evidence snippets."),
        ("tasks_enriched_review", DEFAULT_TASK_REVIEW_REPORT, "quality", "Human-review queue generated from enriched task evidence."),
        ("task_review_decisions", DEFAULT_TASK_REVIEW_DECISIONS_CSV, "quality", "Human review decisions and optional edits for enriched tasks."),
        ("tasks_reviewed", DEFAULT_TASKS_REVIEWED_CSV, "cleaned", "Task table after human review approval or rejection decisions."),
        ("user_states", DEFAULT_USER_STATE_CSV, "state", "Local CSV-backed student state store."),
        ("user_task_states", DEFAULT_USER_TASK_STATE_CSV, "state", "Local per-user task status, deadline, and reminder store."),
        ("faq", DEFAULT_FAQ_CSV, "cleaned", "Raw FAQ candidates extracted from pages."),
        ("faq_cleaned", DEFAULT_CLEAN_FAQ_CSV, "cleaned", "Cleaned structured FAQ rows."),
        ("task_evidence", DEFAULT_TASK_EVIDENCE_CSV, "cleaned", "Task-field evidence extracted from official FAQ text."),
        ("chunks", DEFAULT_CHUNKS_CSV, "rag", "Local retrieval chunks."),
        ("vector_index", DEFAULT_VECTOR_INDEX_CSV, "rag", "Dependency-light sparse vector index for retrieval experimentation."),
        ("raw_page_index", DEFAULT_RAW_PAGE_INDEX, "metadata", "Index of archived raw text files."),
        ("schema_dictionary", DEFAULT_SCHEMA_DICTIONARY, "metadata", "Column dictionary for Phase 1 CSV outputs."),
    ]

    rows: list[dict[str, object]] = []
    for artifact, target, category, notes in targets:
        path = _resolve_under_root(root_path, target)
        exists = path.exists()
        row_count = ""
        file_count = ""
        if exists and path.is_dir():
            file_count = len([item for item in path.glob("*.txt") if item.name != ".gitkeep"])
        elif exists and path.suffix.lower() == ".csv":
            row_count = _csv_row_count(path)

        rows.append(
            {
                "artifact": artifact,
                "path": path.relative_to(root_path).as_posix()
                if path.is_relative_to(root_path)
                else path.as_posix(),
                "category": category,
                "exists": "yes" if exists else "no",
                "row_count": row_count,
                "file_count": file_count,
                "updated_at": _latest_mtime(path) if exists else "",
                "notes": notes,
            }
        )
    return pd.DataFrame(rows, columns=MANIFEST_COLUMNS)


def build_schema_dictionary() -> pd.DataFrame:
    """Build a compact data dictionary for Phase 1 CSV files."""

    datasets: dict[str, Iterable[str]] = {
        "source_list.csv": SOURCE_COLUMNS,
        "crawl_log.csv": LOG_COLUMNS,
        "crawl_summary.csv": SUMMARY_COLUMNS,
        "data_quality_report.csv": QUALITY_COLUMNS,
        "task_evidence_quality_report.csv": TASK_EVIDENCE_QUALITY_COLUMNS,
        "raw_page_index.csv": RAW_PAGE_INDEX_COLUMNS,
        "schools.csv": [
            "school_id",
            "school_name",
            "official_website",
            "offer_holder_url",
            "admitted_student_url",
            "visa_url",
            "accommodation_url",
            "tuition_url",
            "orientation_url",
        ],
        "tasks.csv": TASK_COLUMNS,
        "tasks_enriched.csv": TASK_ENRICHED_COLUMNS,
        "tasks_enriched_review.csv": TASK_REVIEW_COLUMNS,
        "task_review_decisions.csv": TASK_REVIEW_DECISION_COLUMNS,
        "tasks_reviewed.csv": TASK_REVIEWED_COLUMNS,
        "user_states.csv": USER_STATE_COLUMNS,
        "user_task_states.csv": USER_TASK_STATE_COLUMNS,
        "faq.csv": FAQ_COLUMNS,
        "faq_cleaned.csv": FAQ_COLUMNS,
        "task_evidence.csv": TASK_EVIDENCE_COLUMNS,
        "chunks.csv": [
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
        ],
        "vector_index.csv": VECTOR_INDEX_COLUMNS,
        "phase1_manifest.csv": MANIFEST_COLUMNS,
    }

    rows = []
    for dataset, columns in datasets.items():
        for column in columns:
            rows.append(
                {
                    "dataset": dataset,
                    "column": column,
                    "required": "yes",
                    "description": SCHEMA_DESCRIPTIONS.get(column, ""),
                }
            )
    return pd.DataFrame(rows, columns=SCHEMA_DICTIONARY_COLUMNS)


def write_phase1_outputs(
    *,
    root: Path | str = ROOT_DIR,
    raw_dir: Path | str = DEFAULT_RAW_DIR,
    raw_page_index: Path | str = DEFAULT_RAW_PAGE_INDEX,
    phase1_manifest: Path | str = DEFAULT_PHASE1_MANIFEST,
    schema_dictionary: Path | str = DEFAULT_SCHEMA_DICTIONARY,
) -> dict[str, int]:
    """Write Phase 1 catalog outputs and return compact counts."""

    raw_index_frame = build_raw_page_index(raw_dir)
    schema_frame = build_schema_dictionary()

    _write_csv(raw_index_frame, raw_page_index)
    _write_csv(schema_frame, schema_dictionary)

    # Build the manifest after writing the two metadata outputs so their row
    # counts and timestamps are reflected in the catalog.
    manifest_frame = build_phase1_manifest(root)
    _write_csv(manifest_frame, phase1_manifest)

    return {
        "raw_page_index_rows": len(raw_index_frame),
        "schema_dictionary_rows": len(schema_frame),
        "phase1_manifest_rows": len(manifest_frame),
    }


def _write_csv(frame: pd.DataFrame, path: Path | str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def _resolve_under_root(root: Path, target: Path) -> Path:
    if target.is_absolute():
        try:
            return root / target.relative_to(ROOT_DIR)
        except ValueError:
            return target
    return root / target


def _csv_row_count(path: Path) -> int | str:
    if path.stat().st_size == 0:
        return 0
    try:
        return int(len(pd.read_csv(path, dtype=str, keep_default_na=False)))
    except Exception:
        return ""


def _latest_mtime(path: Path) -> str:
    if path.is_dir():
        children = [item for item in path.iterdir() if item.name != ".gitkeep"]
        if not children:
            timestamp = path.stat().st_mtime
        else:
            timestamp = max(item.stat().st_mtime for item in children)
    else:
        timestamp = path.stat().st_mtime
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Phase 1 catalog outputs.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--raw-page-index", type=Path, default=DEFAULT_RAW_PAGE_INDEX)
    parser.add_argument("--phase1-manifest", type=Path, default=DEFAULT_PHASE1_MANIFEST)
    parser.add_argument("--schema-dictionary", type=Path, default=DEFAULT_SCHEMA_DICTIONARY)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    counts = write_phase1_outputs(
        raw_dir=args.raw_dir,
        raw_page_index=args.raw_page_index,
        phase1_manifest=args.phase1_manifest,
        schema_dictionary=args.schema_dictionary,
    )
    print(
        "已生成 Phase 1 归档元数据："
        f"raw_page_index={counts['raw_page_index_rows']} 行，"
        f"schema_dictionary={counts['schema_dictionary_rows']} 行，"
        f"phase1_manifest={counts['phase1_manifest_rows']} 行"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
