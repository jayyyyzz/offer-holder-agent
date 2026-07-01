"""Human-reviewed task table workflow built on top of tasks_enriched.csv."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

import pandas as pd

from knowledge_base.enrich_tasks import DEFAULT_TASKS_ENRICHED_CSV, TASK_ENRICHED_COLUMNS
from knowledge_base.review_enriched_tasks import DEFAULT_TASK_REVIEW_REPORT, TASK_REVIEW_COLUMNS


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TASK_REVIEW_DECISIONS_CSV = ROOT_DIR / "data" / "metadata" / "task_review_decisions.csv"
DEFAULT_TASKS_REVIEWED_CSV = ROOT_DIR / "data" / "cleaned" / "tasks_reviewed.csv"
DEFAULT_TASK_REVIEW_SUMMARY_CSV = ROOT_DIR / "data" / "metadata" / "task_review_pending_summary.csv"
DEFAULT_TASK_REVIEW_PENDING_EXPORT_CSV = ROOT_DIR / "data" / "metadata" / "task_review_pending_export.csv"


VALID_REVIEW_DECISIONS = {
    "",
    "approve",
    "approve_with_edits",
    "reject",
}


TASK_REVIEW_DECISION_COLUMNS = [
    "task_id",
    "school",
    "task_code",
    "stage",
    "task_name",
    "review_priority",
    "review_reason",
    "reviewer_decision",
    "reviewed_deadline_evidence",
    "reviewed_document_evidence",
    "reviewed_action_evidence",
    "reviewed_action_urls",
    "reviewed_fee_evidence",
    "reviewer_notes",
    "reviewed_at",
]


TASK_REVIEWED_COLUMNS = [
    *TASK_ENRICHED_COLUMNS,
    "review_priority",
    "review_reason",
    "review_decision",
    "review_notes",
    "human_review_status",
    "reviewed_at",
]


TASK_REVIEW_SUMMARY_COLUMNS = [
    "school",
    "review_priority",
    "total_review_rows",
    "pending_count",
    "approved_count",
    "approved_with_edits_count",
    "rejected_count",
]


TASK_REVIEW_PENDING_EXPORT_COLUMNS = [
    "school",
    "review_priority",
    "task_id",
    "task_code",
    "stage",
    "task_name",
    "review_reason",
    "candidate_evidence_count",
    "usable_evidence_count",
    "review_evidence_count",
    "rejected_evidence_count",
    "official_deadline_evidence",
    "official_document_evidence",
    "official_action_evidence",
    "official_action_urls",
    "official_fee_evidence",
    "suggested_action",
    "reviewer_decision",
    "reviewer_notes",
    "reviewed_at",
]


def init_task_review_decisions(
    task_review_report_csv: Path | str = DEFAULT_TASK_REVIEW_REPORT,
    *,
    task_review_decisions_csv: Path | str | None = None,
    school_filter: str | None = None,
    pending_only: bool = False,
) -> pd.DataFrame:
    report = _read_csv(Path(task_review_report_csv), required=TASK_REVIEW_COLUMNS)
    report = filter_rows_by_school(report, school_filter)
    if report.empty:
        return pd.DataFrame(columns=TASK_REVIEW_DECISION_COLUMNS)

    existing_decisions = (
        _read_csv(Path(task_review_decisions_csv), required=TASK_REVIEW_DECISION_COLUMNS)
        if task_review_decisions_csv and Path(task_review_decisions_csv).exists()
        else pd.DataFrame(columns=TASK_REVIEW_DECISION_COLUMNS)
    )
    existing_by_id = {
        str(row.get("task_id", "")).strip(): row
        for row in existing_decisions.to_dict(orient="records")
        if str(row.get("task_id", "")).strip()
    }

    rows = []
    for row in report.to_dict(orient="records"):
        task_id = str(row.get("task_id", "")).strip()
        existing_row = existing_by_id.get(task_id, {})
        existing_decision = str(existing_row.get("reviewer_decision", "")).strip().lower()
        if pending_only and existing_decision:
            continue
        rows.append(
            {
                "task_id": row.get("task_id", ""),
                "school": row.get("school", ""),
                "task_code": row.get("task_code", ""),
                "stage": row.get("stage", ""),
                "task_name": row.get("task_name", ""),
                "review_priority": row.get("review_priority", ""),
                "review_reason": row.get("review_reason", ""),
                "reviewer_decision": existing_row.get("reviewer_decision", ""),
                "reviewed_deadline_evidence": existing_row.get("reviewed_deadline_evidence", "") or row.get("official_deadline_evidence", ""),
                "reviewed_document_evidence": existing_row.get("reviewed_document_evidence", "") or row.get("official_document_evidence", ""),
                "reviewed_action_evidence": existing_row.get("reviewed_action_evidence", "") or row.get("official_action_evidence", ""),
                "reviewed_action_urls": existing_row.get("reviewed_action_urls", "") or row.get("official_action_urls", ""),
                "reviewed_fee_evidence": existing_row.get("reviewed_fee_evidence", "") or row.get("official_fee_evidence", ""),
                "reviewer_notes": existing_row.get("reviewer_notes", ""),
                "reviewed_at": existing_row.get("reviewed_at", ""),
            }
        )
    return pd.DataFrame(rows, columns=TASK_REVIEW_DECISION_COLUMNS)


def write_task_review_decisions(
    frame: pd.DataFrame,
    output_path: Path | str = DEFAULT_TASK_REVIEW_DECISIONS_CSV,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def build_reviewed_tasks(
    tasks_enriched_csv: Path | str = DEFAULT_TASKS_ENRICHED_CSV,
    task_review_report_csv: Path | str = DEFAULT_TASK_REVIEW_REPORT,
    task_review_decisions_csv: Path | str | None = None,
    *,
    school_filter: str | None = None,
    pending_only: bool = False,
) -> pd.DataFrame:
    tasks = _read_csv(Path(tasks_enriched_csv), required=TASK_ENRICHED_COLUMNS)
    report = _read_csv(Path(task_review_report_csv), required=TASK_REVIEW_COLUMNS)
    decisions = (
        _read_csv(Path(task_review_decisions_csv), required=TASK_REVIEW_DECISION_COLUMNS)
        if task_review_decisions_csv and Path(task_review_decisions_csv).exists()
        else pd.DataFrame(columns=TASK_REVIEW_DECISION_COLUMNS)
    )
    tasks = filter_rows_by_school(tasks, school_filter)
    report = filter_rows_by_school(report, school_filter)
    decisions = filter_rows_by_school(decisions, school_filter)
    if tasks.empty:
        return pd.DataFrame(columns=TASK_REVIEWED_COLUMNS)

    report_by_id = {
        str(row.get("task_id", "")).strip(): row
        for row in report.to_dict(orient="records")
        if str(row.get("task_id", "")).strip()
    }
    decisions_by_id = {
        str(row.get("task_id", "")).strip(): row
        for row in decisions.to_dict(orient="records")
        if str(row.get("task_id", "")).strip()
    }

    rows = []
    for row in tasks.to_dict(orient="records"):
        task_id = str(row.get("task_id", "")).strip()
        report_row = report_by_id.get(task_id, {})
        decision_row = decisions_by_id.get(task_id, {})
        reviewed = build_reviewed_task_row(row, report_row=report_row, decision_row=decision_row)
        rows.append(reviewed)
    frame = pd.DataFrame(rows, columns=TASK_REVIEWED_COLUMNS)
    if pending_only and not frame.empty:
        frame = frame[frame["human_review_status"] == "review_pending"].copy()
    return frame


def build_review_pending_summary(
    task_review_report_csv: Path | str = DEFAULT_TASK_REVIEW_REPORT,
    task_review_decisions_csv: Path | str | None = None,
    *,
    school_filter: str | None = None,
) -> pd.DataFrame:
    report = _read_csv(Path(task_review_report_csv), required=TASK_REVIEW_COLUMNS)
    report = filter_rows_by_school(report, school_filter)
    decisions = (
        _read_csv(Path(task_review_decisions_csv), required=TASK_REVIEW_DECISION_COLUMNS)
        if task_review_decisions_csv and Path(task_review_decisions_csv).exists()
        else pd.DataFrame(columns=TASK_REVIEW_DECISION_COLUMNS)
    )
    decisions = filter_rows_by_school(decisions, school_filter)
    if report.empty:
        return pd.DataFrame(columns=TASK_REVIEW_SUMMARY_COLUMNS)

    decision_by_id = {
        str(row.get("task_id", "")).strip(): str(row.get("reviewer_decision", "")).strip().lower()
        for row in decisions.to_dict(orient="records")
        if str(row.get("task_id", "")).strip()
    }

    counts: dict[tuple[str, str], dict[str, int]] = {}
    for row in report.to_dict(orient="records"):
        school = str(row.get("school", "")).strip()
        priority = str(row.get("review_priority", "")).strip()
        key = (school, priority)
        bucket = counts.setdefault(
            key,
            {
                "total_review_rows": 0,
                "pending_count": 0,
                "approved_count": 0,
                "approved_with_edits_count": 0,
                "rejected_count": 0,
            },
        )
        bucket["total_review_rows"] += 1
        decision = decision_by_id.get(str(row.get("task_id", "")).strip(), "")
        if decision == "approve":
            bucket["approved_count"] += 1
        elif decision == "approve_with_edits":
            bucket["approved_with_edits_count"] += 1
        elif decision == "reject":
            bucket["rejected_count"] += 1
        else:
            bucket["pending_count"] += 1

    rows = []
    for (school, priority), values in sorted(counts.items()):
        rows.append(
            {
                "school": school,
                "review_priority": priority,
                **values,
            }
        )
    return pd.DataFrame(rows, columns=TASK_REVIEW_SUMMARY_COLUMNS)


def build_review_pending_export(
    task_review_report_csv: Path | str = DEFAULT_TASK_REVIEW_REPORT,
    task_review_decisions_csv: Path | str | None = None,
    *,
    school_filter: str | None = None,
) -> pd.DataFrame:
    report = _read_csv(Path(task_review_report_csv), required=TASK_REVIEW_COLUMNS)
    report = filter_rows_by_school(report, school_filter)
    decisions = (
        _read_csv(Path(task_review_decisions_csv), required=TASK_REVIEW_DECISION_COLUMNS)
        if task_review_decisions_csv and Path(task_review_decisions_csv).exists()
        else pd.DataFrame(columns=TASK_REVIEW_DECISION_COLUMNS)
    )
    decisions = filter_rows_by_school(decisions, school_filter)
    if report.empty:
        return pd.DataFrame(columns=TASK_REVIEW_PENDING_EXPORT_COLUMNS)

    decisions_by_id = {
        str(row.get("task_id", "")).strip(): row
        for row in decisions.to_dict(orient="records")
        if str(row.get("task_id", "")).strip()
    }

    rows: list[dict[str, object]] = []
    for row in report.to_dict(orient="records"):
        task_id = str(row.get("task_id", "")).strip()
        decision_row = decisions_by_id.get(task_id, {})
        reviewer_decision = str(decision_row.get("reviewer_decision", "")).strip().lower()
        if reviewer_decision:
            continue
        rows.append(
            {
                "school": row.get("school", ""),
                "review_priority": row.get("review_priority", ""),
                "task_id": row.get("task_id", ""),
                "task_code": row.get("task_code", ""),
                "stage": row.get("stage", ""),
                "task_name": row.get("task_name", ""),
                "review_reason": row.get("review_reason", ""),
                "candidate_evidence_count": row.get("candidate_evidence_count", ""),
                "usable_evidence_count": row.get("usable_evidence_count", ""),
                "review_evidence_count": row.get("review_evidence_count", ""),
                "rejected_evidence_count": row.get("rejected_evidence_count", ""),
                "official_deadline_evidence": row.get("official_deadline_evidence", ""),
                "official_document_evidence": row.get("official_document_evidence", ""),
                "official_action_evidence": row.get("official_action_evidence", ""),
                "official_action_urls": row.get("official_action_urls", ""),
                "official_fee_evidence": row.get("official_fee_evidence", ""),
                "suggested_action": row.get("suggested_action", ""),
                "reviewer_decision": "",
                "reviewer_notes": str(decision_row.get("reviewer_notes", "")).strip(),
                "reviewed_at": str(decision_row.get("reviewed_at", "")).strip(),
            }
        )

    frame = pd.DataFrame(rows, columns=TASK_REVIEW_PENDING_EXPORT_COLUMNS)
    if frame.empty:
        return frame

    sort_key = frame["review_priority"].map(priority_sort_value)
    frame = (
        frame.assign(_priority_sort=sort_key)
        .sort_values(by=["school", "_priority_sort", "stage", "task_id"], kind="stable")
        .drop(columns="_priority_sort")
        .reset_index(drop=True)
    )
    return frame[TASK_REVIEW_PENDING_EXPORT_COLUMNS]


def build_reviewed_task_row(
    task_row: dict[str, object],
    *,
    report_row: dict[str, object],
    decision_row: dict[str, object],
) -> dict[str, object]:
    row = dict(task_row)
    review_priority = str(report_row.get("review_priority", "")).strip()
    review_reason = str(report_row.get("review_reason", "")).strip()
    review_decision = str(decision_row.get("reviewer_decision", "")).strip().lower()
    if review_decision not in VALID_REVIEW_DECISIONS:
        raise ValueError(f"invalid reviewer_decision for {row.get('task_id', '')}: {review_decision}")

    row["review_priority"] = review_priority
    row["review_reason"] = review_reason
    row["review_decision"] = review_decision
    row["review_notes"] = str(decision_row.get("reviewer_notes", "")).strip()
    row["reviewed_at"] = (
        str(decision_row.get("reviewed_at", "")).strip() or datetime.now(UTC).date().isoformat()
        if review_decision
        else ""
    )

    if not review_priority:
        row["human_review_status"] = "not_required"
        return row

    if review_decision in {"approve", "approve_with_edits"}:
        row["official_deadline_evidence"] = select_reviewed_field(
            decision_row,
            "reviewed_deadline_evidence",
            row.get("official_deadline_evidence", ""),
        )
        row["official_document_evidence"] = select_reviewed_field(
            decision_row,
            "reviewed_document_evidence",
            row.get("official_document_evidence", ""),
        )
        row["official_action_evidence"] = select_reviewed_field(
            decision_row,
            "reviewed_action_evidence",
            row.get("official_action_evidence", ""),
        )
        row["official_action_urls"] = select_reviewed_field(
            decision_row,
            "reviewed_action_urls",
            row.get("official_action_urls", ""),
        )
        row["official_fee_evidence"] = select_reviewed_field(
            decision_row,
            "reviewed_fee_evidence",
            row.get("official_fee_evidence", ""),
        )
        row["evidence_quality_status"] = "human_reviewed"
        row["evidence_quality_notes"] = row["review_notes"] or review_reason or "Human review approved."
        row["enrichment_status"] = "review_approved" if review_decision == "approve" else "review_approved_with_edits"
        row["human_review_status"] = row["enrichment_status"]
        return row

    if review_decision == "reject":
        clear_reviewed_evidence(row)
        row["evidence_quality_status"] = "human_reviewed_rejected"
        row["evidence_quality_notes"] = row["review_notes"] or review_reason or "Human review rejected candidate evidence."
        row["enrichment_status"] = "review_rejected"
        row["human_review_status"] = "review_rejected"
        return row

    clear_reviewed_evidence(row)
    row["evidence_quality_status"] = "review_pending"
    row["evidence_quality_notes"] = review_reason or "Human review pending."
    row["enrichment_status"] = "review_pending"
    row["human_review_status"] = "review_pending"
    return row


def write_reviewed_tasks(
    frame: pd.DataFrame,
    output_path: Path | str = DEFAULT_TASKS_REVIEWED_CSV,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def write_task_review_summary(
    frame: pd.DataFrame,
    output_path: Path | str = DEFAULT_TASK_REVIEW_SUMMARY_CSV,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def write_task_review_pending_export(
    frame: pd.DataFrame,
    output_path: Path | str = DEFAULT_TASK_REVIEW_PENDING_EXPORT_CSV,
) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def select_reviewed_field(
    decision_row: dict[str, object],
    decision_key: str,
    default_value: object,
) -> str:
    value = str(decision_row.get(decision_key, "")).strip()
    if value:
        return value
    return str(default_value or "").strip()


def clear_reviewed_evidence(row: dict[str, object]) -> None:
    row["official_deadline_evidence"] = ""
    row["official_document_evidence"] = ""
    row["official_action_evidence"] = ""
    row["official_action_urls"] = ""
    row["official_fee_evidence"] = ""
    row["evidence_ids"] = ""
    row["evidence_types"] = ""
    row["evidence_count"] = 0
    row["usable_evidence_count"] = 0


def priority_sort_value(value: object) -> int:
    normalized = str(value or "").strip().lower()
    order = {
        "high": 0,
        "medium": 1,
        "low": 2,
        "": 9,
    }
    return order.get(normalized, 8)


def filter_rows_by_school(
    frame: pd.DataFrame,
    school_filter: str | None,
) -> pd.DataFrame:
    if frame.empty or not school_filter:
        return frame
    normalized = str(school_filter).strip().upper()
    if not normalized or "school" not in frame.columns:
        return frame
    return frame[frame["school"].str.upper() == normalized].copy()


def _read_csv(path: Path, *, required: list[str]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=required)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column in required:
        if column not in frame.columns:
            frame[column] = ""
    return frame[required]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create human-review artifacts for enriched tasks.")
    parser.add_argument("--tasks-enriched", type=Path, default=DEFAULT_TASKS_ENRICHED_CSV)
    parser.add_argument("--task-review-report", type=Path, default=DEFAULT_TASK_REVIEW_REPORT)
    parser.add_argument("--task-review-decisions", type=Path, default=DEFAULT_TASK_REVIEW_DECISIONS_CSV)
    parser.add_argument("--tasks-reviewed", type=Path, default=DEFAULT_TASKS_REVIEWED_CSV)
    parser.add_argument("--task-review-summary", type=Path, default=DEFAULT_TASK_REVIEW_SUMMARY_CSV)
    parser.add_argument("--task-review-pending-export", type=Path, default=DEFAULT_TASK_REVIEW_PENDING_EXPORT_CSV)
    parser.add_argument("--init-decisions", action="store_true")
    parser.add_argument("--build-reviewed", action="store_true")
    parser.add_argument("--build-pending-summary", action="store_true")
    parser.add_argument("--build-pending-export", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    if args.init_decisions:
        frame = init_task_review_decisions(args.task_review_report)
        write_task_review_decisions(frame, args.task_review_decisions)
        print(f"已生成 task review decisions：{len(frame)} 条 -> {args.task_review_decisions}")
        return 0
    if args.build_reviewed:
        frame = build_reviewed_tasks(
            args.tasks_enriched,
            args.task_review_report,
            args.task_review_decisions if args.task_review_decisions.exists() else None,
        )
        write_reviewed_tasks(frame, args.tasks_reviewed)
        print(f"已生成 tasks_reviewed：{len(frame)} 条 -> {args.tasks_reviewed}")
        return 0
    if args.build_pending_summary:
        frame = build_review_pending_summary(
            args.task_review_report,
            args.task_review_decisions if args.task_review_decisions.exists() else None,
        )
        write_task_review_summary(frame, args.task_review_summary)
        print(f"已生成 task review pending summary：{len(frame)} 条 -> {args.task_review_summary}")
        return 0
    if args.build_pending_export:
        frame = build_review_pending_export(
            args.task_review_report,
            args.task_review_decisions if args.task_review_decisions.exists() else None,
        )
        write_task_review_pending_export(frame, args.task_review_pending_export)
        print(f"已生成 task review pending export：{len(frame)} 条 -> {args.task_review_pending_export}")
        return 0
    raise SystemExit("请提供 --init-decisions、--build-reviewed、--build-pending-summary 或 --build-pending-export。")


if __name__ == "__main__":
    raise SystemExit(main())
