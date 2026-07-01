"""Build a manual-review report for evidence-enriched tasks."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

import pandas as pd

from knowledge_base.enrich_tasks import DEFAULT_TASKS_ENRICHED_CSV, TASK_ENRICHED_COLUMNS


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TASK_REVIEW_REPORT = ROOT_DIR / "data" / "metadata" / "tasks_enriched_review.csv"


TASK_REVIEW_COLUMNS = [
    "task_id",
    "school",
    "task_code",
    "stage",
    "task_name",
    "candidate_evidence_count",
    "usable_evidence_count",
    "review_evidence_count",
    "rejected_evidence_count",
    "evidence_quality_status",
    "enrichment_status",
    "official_deadline_evidence",
    "official_document_evidence",
    "official_action_evidence",
    "official_action_urls",
    "official_fee_evidence",
    "review_priority",
    "review_reason",
    "suggested_action",
    "generated_at",
]


ALWAYS_REVIEW_TASK_CODES = {
    "pay_deposit",
    "submit_conditions",
}


def build_task_review_report(
    tasks_enriched_csv: Path | str = DEFAULT_TASKS_ENRICHED_CSV,
) -> pd.DataFrame:
    frame = _read_csv(Path(tasks_enriched_csv), required=TASK_ENRICHED_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=TASK_REVIEW_COLUMNS)

    generated_at = datetime.now(UTC).date().isoformat()
    rows = []
    for row in frame.to_dict(orient="records"):
        review_priority, review_reason, suggested_action = assess_review_need(row)
        if review_priority == "none":
            continue
        rows.append(
            {
                "task_id": row.get("task_id", ""),
                "school": row.get("school", ""),
                "task_code": row.get("task_code", ""),
                "stage": row.get("stage", ""),
                "task_name": row.get("task_name", ""),
                "candidate_evidence_count": row.get("candidate_evidence_count", ""),
                "usable_evidence_count": row.get("usable_evidence_count", ""),
                "review_evidence_count": row.get("review_evidence_count", ""),
                "rejected_evidence_count": row.get("rejected_evidence_count", ""),
                "evidence_quality_status": row.get("evidence_quality_status", ""),
                "enrichment_status": row.get("enrichment_status", ""),
                "official_deadline_evidence": row.get("official_deadline_evidence", ""),
                "official_document_evidence": row.get("official_document_evidence", ""),
                "official_action_evidence": row.get("official_action_evidence", ""),
                "official_action_urls": row.get("official_action_urls", ""),
                "official_fee_evidence": row.get("official_fee_evidence", ""),
                "review_priority": review_priority,
                "review_reason": review_reason,
                "suggested_action": suggested_action,
                "generated_at": generated_at,
            }
        )

    report = pd.DataFrame(rows, columns=TASK_REVIEW_COLUMNS)
    if report.empty:
        return report
    return report.sort_values(
        ["review_priority", "school", "task_code", "task_id"],
        ascending=[True, True, True, True],
        kind="stable",
    )


def assess_review_need(row: dict[str, object]) -> tuple[str, str, str]:
    task_code = str(row.get("task_code", "")).strip()
    candidate_count = _to_int(row.get("candidate_evidence_count", 0))
    usable_count = _to_int(row.get("usable_evidence_count", 0))
    review_count = _to_int(row.get("review_evidence_count", 0))
    rejected_count = _to_int(row.get("rejected_evidence_count", 0))
    quality_status = str(row.get("evidence_quality_status", "")).strip()
    enrichment_status = str(row.get("enrichment_status", "")).strip()

    reasons: list[str] = []
    priority = "none"
    suggested_action = ""

    if task_code in ALWAYS_REVIEW_TASK_CODES and candidate_count:
        priority = "high"
        reasons.append("该任务类型容易混入 general admission FAQ，需要人工确认是否真的是 offer-holder 后续动作")
        suggested_action = "逐条对照原始 FAQ、portal 和 offer letter，确认该证据是否只适用于已拿 offer 的学生。"

    if quality_status == "not_audited" and candidate_count:
        priority = max_priority(priority, "high")
        reasons.append("当前证据尚未经过 quality report 审计")
        suggested_action = suggested_action or "先运行 task evidence quality audit，再决定是否写回任务字段。"

    if candidate_count and usable_count == 0:
        priority = max_priority(priority, "high")
        reasons.append("有候选证据，但没有任何 keep 级可用证据")
        suggested_action = suggested_action or "检查 source_question、source_url 和 evidence_text，确认是否被误判或需要人工挑选。"

    if review_count:
        priority = max_priority(priority, "medium")
        reasons.append(f"仍有 {review_count} 条 review/missing 证据未处理")
        suggested_action = suggested_action or "优先处理 review/missing 证据，决定 keep 或 reject。"

    if rejected_count and usable_count:
        priority = max_priority(priority, "medium")
        reasons.append(f"同一任务同时存在 {usable_count} 条 keep 和 {rejected_count} 条 reject 证据")
        suggested_action = suggested_action or "检查是否有同名任务混入其他场景的 FAQ 证据。"

    if enrichment_status == "evidence_needs_review":
        priority = max_priority(priority, "medium")
        reasons.append("增强结果明确标记为 evidence_needs_review")
        suggested_action = suggested_action or "复核后再将官方候选证据暴露给最终问答链路。"

    return priority, "；".join(reasons), suggested_action


def max_priority(left: str, right: str) -> str:
    order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    return left if order[left] >= order[right] else right


def write_task_review_report(
    frame: pd.DataFrame,
    output_path: Path | str = DEFAULT_TASK_REVIEW_REPORT,
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


def _to_int(value: object) -> int:
    try:
        if value == "":
            return 0
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a manual-review report for tasks_enriched.csv.")
    parser.add_argument("--tasks-enriched", type=Path, default=DEFAULT_TASKS_ENRICHED_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_TASK_REVIEW_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = build_task_review_report(args.tasks_enriched)
    write_task_review_report(frame, args.output)
    print(f"已生成 tasks_enriched review report：{len(frame)} 条 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
