"""Create an evidence-enriched task table without overwriting tasks.csv."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import re
import sys

import pandas as pd

from agent.task_planner import DEFAULT_TASKS_CSV, TASK_COLUMNS
from knowledge_base.extract_task_evidence import (
    DEFAULT_TASK_EVIDENCE_CSV,
    TASK_EVIDENCE_COLUMNS,
)
from knowledge_base.audit_task_evidence_quality import (
    DEFAULT_TASK_EVIDENCE_QUALITY_REPORT,
    TASK_EVIDENCE_QUALITY_COLUMNS,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TASKS_ENRICHED_CSV = ROOT_DIR / "data" / "cleaned" / "tasks_enriched.csv"


TASK_ENRICHED_COLUMNS = [
    *TASK_COLUMNS,
    "task_code",
    "evidence_count",
    "candidate_evidence_count",
    "usable_evidence_count",
    "review_evidence_count",
    "rejected_evidence_count",
    "evidence_types",
    "official_deadline_evidence",
    "official_document_evidence",
    "official_action_evidence",
    "official_action_urls",
    "official_fee_evidence",
    "evidence_ids",
    "evidence_quality_status",
    "evidence_quality_notes",
    "enrichment_status",
    "enriched_at",
]


SPECIFIC_EVIDENCE_TYPES = {
    "deadline",
    "required_document",
    "action_instruction",
    "action_url",
    "fee_amount",
}


def build_enriched_tasks(
    tasks_csv: Path | str = DEFAULT_TASKS_CSV,
    task_evidence_csv: Path | str = DEFAULT_TASK_EVIDENCE_CSV,
    task_evidence_quality_csv: Path | str | None = None,
    *,
    max_items_per_field: int = 3,
) -> pd.DataFrame:
    """Merge task templates with official-source evidence snippets."""

    tasks = _read_csv(Path(tasks_csv), required=TASK_COLUMNS)
    evidence = _read_csv(Path(task_evidence_csv), required=TASK_EVIDENCE_COLUMNS)
    quality_by_id = load_quality_decisions(task_evidence_quality_csv)

    if tasks.empty:
        return pd.DataFrame(columns=TASK_ENRICHED_COLUMNS)

    if evidence.empty:
        rows = []
        for task in tasks.to_dict(orient="records"):
            rows.append(_empty_enriched_row(task, status="no_evidence_file"))
        return pd.DataFrame(rows, columns=TASK_ENRICHED_COLUMNS)

    evidence = evidence[evidence["evidence_type"].isin(SPECIFIC_EVIDENCE_TYPES)].copy()

    rows: list[dict[str, object]] = []
    for task in tasks.to_dict(orient="records"):
        task_code = infer_task_code(task)
        candidate_evidence = evidence[
            (evidence["school"].str.lower() == str(task.get("school", "")).lower())
            & (evidence["task_code"] == task_code)
        ].copy()
        task_evidence = filter_usable_evidence(candidate_evidence, quality_by_id)
        quality_counts = count_quality_decisions(candidate_evidence, quality_by_id)

        row = dict(task)
        row["task_code"] = task_code
        row["evidence_count"] = int(len(task_evidence))
        row["candidate_evidence_count"] = int(len(candidate_evidence))
        row["usable_evidence_count"] = quality_counts["usable"]
        row["review_evidence_count"] = quality_counts["review"]
        row["rejected_evidence_count"] = quality_counts["rejected"]
        row["evidence_types"] = ", ".join(sorted(set(task_evidence["evidence_type"])))
        row["official_deadline_evidence"] = join_evidence(
            task_evidence, "deadline", max_items=max_items_per_field
        )
        row["official_document_evidence"] = join_evidence(
            task_evidence, "required_document", max_items=max_items_per_field
        )
        row["official_action_evidence"] = join_evidence(
            task_evidence, "action_instruction", max_items=max_items_per_field
        )
        row["official_action_urls"] = join_evidence(
            task_evidence,
            "action_url",
            value_column="normalized_value",
            max_items=max_items_per_field,
        )
        row["official_fee_evidence"] = join_evidence(
            task_evidence, "fee_amount", max_items=max_items_per_field
        )
        row["evidence_ids"] = "; ".join(task_evidence["evidence_id"].head(12))
        row["evidence_quality_status"] = quality_counts["status"]
        row["evidence_quality_notes"] = quality_counts["notes"]
        row["enrichment_status"] = enrichment_status(
            candidate_count=len(candidate_evidence),
            usable_count=len(task_evidence),
            quality_available=bool(quality_by_id),
        )
        row["enriched_at"] = datetime.now(UTC).date().isoformat()
        rows.append(row)

    return pd.DataFrame(rows, columns=TASK_ENRICHED_COLUMNS)


def write_enriched_tasks(frame: pd.DataFrame, output_path: Path | str = DEFAULT_TASKS_ENRICHED_CSV) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def load_quality_decisions(task_evidence_quality_csv: Path | str | None) -> dict[str, str]:
    """Load evidence_id -> quality_decision when an audit file is available.

    No audit file means legacy behavior: every extracted evidence row remains
    usable.  A present audit file is stricter: only rows marked ``keep`` are
    promoted into the official_* task fields.
    """

    if not task_evidence_quality_csv:
        return {}
    path = Path(task_evidence_quality_csv)
    if not path.exists() or path.stat().st_size == 0:
        return {}

    frame = _read_csv(path, required=TASK_EVIDENCE_QUALITY_COLUMNS)
    decisions: dict[str, str] = {}
    for row in frame.to_dict(orient="records"):
        evidence_id = str(row.get("evidence_id", "")).strip()
        if not evidence_id:
            continue
        decisions[evidence_id] = str(row.get("quality_decision", "")).strip().lower()
    return decisions


def filter_usable_evidence(frame: pd.DataFrame, quality_by_id: dict[str, str]) -> pd.DataFrame:
    if frame.empty or not quality_by_id:
        return frame.copy()
    return frame[frame["evidence_id"].map(lambda evidence_id: quality_by_id.get(str(evidence_id), "") == "keep")].copy()


def count_quality_decisions(frame: pd.DataFrame, quality_by_id: dict[str, str]) -> dict[str, object]:
    if frame.empty:
        return {
            "usable": 0,
            "review": 0,
            "rejected": 0,
            "status": "no_evidence",
            "notes": "",
        }

    if not quality_by_id:
        return {
            "usable": int(len(frame)),
            "review": 0,
            "rejected": 0,
            "status": "not_audited",
            "notes": "No task evidence quality report was provided; all candidate evidence is treated as usable.",
        }

    decisions = [quality_by_id.get(str(evidence_id), "missing") for evidence_id in frame["evidence_id"]]
    usable = decisions.count("keep")
    rejected = decisions.count("reject")
    review = len(decisions) - usable - rejected
    notes = []
    if usable:
        notes.append(f"{usable} keep")
    if review:
        notes.append(f"{review} review/missing")
    if rejected:
        notes.append(f"{rejected} reject")
    return {
        "usable": int(usable),
        "review": int(review),
        "rejected": int(rejected),
        "status": "audited",
        "notes": "; ".join(notes),
    }


def enrichment_status(*, candidate_count: int, usable_count: int, quality_available: bool) -> str:
    if usable_count:
        return "evidence_found"
    if candidate_count and quality_available:
        return "evidence_needs_review"
    if candidate_count:
        return "evidence_found"
    return "no_evidence"


def infer_task_code(task: dict[str, object]) -> str:
    task_id = str(task.get("task_id", ""))
    if "-" in task_id:
        return task_id.split("-", 1)[1]

    name = " ".join(str(task.get(field, "")) for field in ("task_name", "description")).lower()
    if "visa" in name or "签证" in name or "进入许可" in name:
        return "apply_student_visa"
    if "deposit" in name or "留位费" in name:
        return "pay_deposit"
    if "accept" in name or "接受" in name:
        return "accept_offer"
    if "conditional" in name or "补交" in name:
        return "submit_conditions"
    if "accommodation" in name or "housing" in name or "宿舍" in name:
        return "apply_accommodation"
    if "tuition" in name or "学费" in name:
        return "pay_tuition"
    if "registration" in name or "注册" in name:
        return "complete_registration"
    if "orientation" in name or "arrival" in name:
        return "prepare_arrival_orientation"
    return ""


def join_evidence(
    frame: pd.DataFrame,
    evidence_type: str,
    *,
    value_column: str = "evidence_text",
    max_items: int = 3,
) -> str:
    if frame.empty:
        return ""

    subset = frame[frame["evidence_type"] == evidence_type].copy()
    if subset.empty:
        return ""

    subset["_rank"] = subset["confidence"].map({"high": 0, "medium": 1, "low": 2}).fillna(3)
    subset = subset.sort_values(["_rank", "updated_at"], kind="stable")

    values: list[str] = []
    seen: set[str] = set()
    for row in subset.to_dict(orient="records"):
        value = str(row.get(value_column) or row.get("evidence_text", "")).strip()
        if not value:
            continue
        value = normalize_evidence_text(value)
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
        if len(values) >= max_items:
            break
    return " | ".join(values)


def normalize_evidence_text(value: str, *, max_chars: int = 360) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3].rstrip() + "..."


def _empty_enriched_row(task: dict[str, object], *, status: str) -> dict[str, object]:
    row = dict(task)
    row.update(
        {
            "task_code": infer_task_code(task),
            "evidence_count": 0,
            "candidate_evidence_count": 0,
            "usable_evidence_count": 0,
            "review_evidence_count": 0,
            "rejected_evidence_count": 0,
            "evidence_types": "",
            "official_deadline_evidence": "",
            "official_document_evidence": "",
            "official_action_evidence": "",
            "official_action_urls": "",
            "official_fee_evidence": "",
            "evidence_ids": "",
            "evidence_quality_status": status,
            "evidence_quality_notes": "",
            "enrichment_status": status,
            "enriched_at": datetime.now(UTC).date().isoformat(),
        }
    )
    return row


def _read_csv(path: Path, *, required: list[str]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=required)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column in required:
        if column not in frame.columns:
            frame[column] = ""
    return frame


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build tasks_enriched.csv from task evidence.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_CSV)
    parser.add_argument("--task-evidence", type=Path, default=DEFAULT_TASK_EVIDENCE_CSV)
    parser.add_argument("--task-evidence-quality", type=Path, default=DEFAULT_TASK_EVIDENCE_QUALITY_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_TASKS_ENRICHED_CSV)
    parser.add_argument("--max-items-per-field", type=int, default=3)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = build_enriched_tasks(
        args.tasks,
        args.task_evidence,
        args.task_evidence_quality if args.task_evidence_quality.exists() else None,
        max_items_per_field=args.max_items_per_field,
    )
    write_enriched_tasks(frame, args.output)
    found = int((frame["enrichment_status"] == "evidence_found").sum()) if not frame.empty else 0
    print(f"已生成 tasks_enriched：{len(frame)} 条 -> {args.output}，其中 {found} 条匹配到任务证据")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
