"""Structured dashboard data for the local frontend."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from agent.intent_router import normalize_school
from agent.task_planner import DEFAULT_TASKS_CSV, PlannedTask, StudentProfile, TaskPlanner
from agent.task_state import (
    DEFAULT_USER_TASK_STATE_CSV,
    TaskState,
    VALID_REMINDER_STATUSES,
    VALID_STATUSES,
    load_user_task_states,
    upsert_user_task_state,
)
from agent.user_state import DEFAULT_USER_STATE_CSV, load_user_profile
from app.console import (
    build_task_agenda_rows,
    build_task_reminder_rows,
    collect_visible_task_states,
    filter_tasks_by_status,
    format_completed_flags,
    infer_school_from_task_states,
    resolve_agenda_date,
    resolve_timezone,
)
from knowledge_base.enrich_tasks import DEFAULT_TASKS_ENRICHED_CSV
from knowledge_base.reviewed_tasks import DEFAULT_TASKS_REVIEWED_CSV
from agent.task_planner import DEFAULT_SCHOOLS_CSV


DEFAULT_FRONTEND_STATE = {
    "school": "HKUST",
    "user_id": "",
    "task_source": "reviewed",
    "agenda_days": 7,
    "agenda_timezone": "Asia/Hong_Kong",
}


def build_dashboard_payload(
    *,
    school: str | None = None,
    user_id: str | None = None,
    task_source: str = "reviewed",
    agenda_days: int = 7,
    agenda_timezone: str = "Asia/Hong_Kong",
    agenda_date: str | None = None,
    tasks_csv: Path | str | None = None,
    tasks_enriched_csv: Path | str = DEFAULT_TASKS_ENRICHED_CSV,
    tasks_reviewed_csv: Path | str = DEFAULT_TASKS_REVIEWED_CSV,
    schools_csv: Path | str = DEFAULT_SCHOOLS_CSV,
    user_state_csv: Path | str = DEFAULT_USER_STATE_CSV,
    task_state_csv: Path | str = DEFAULT_USER_TASK_STATE_CSV,
) -> dict[str, Any]:
    normalized_school = normalize_school(school) or school or ""
    task_states = load_dashboard_task_states(user_id=user_id, school=normalized_school, task_state_csv=task_state_csv)
    profile = load_dashboard_profile(
        user_id=user_id,
        school=normalized_school,
        user_state_csv=user_state_csv,
        task_states=task_states,
    )
    source_summary = resolve_dashboard_task_source(
        task_source=task_source,
        tasks_csv=tasks_csv,
        tasks_enriched_csv=tasks_enriched_csv,
        tasks_reviewed_csv=tasks_reviewed_csv,
    )
    planner = TaskPlanner(
        tasks_csv=Path(tasks_csv) if tasks_csv else DEFAULT_TASKS_CSV,
        task_source_csv=source_summary["path"],
    )
    tasks = planner.plan(
        profile,
        intent=None,
        limit=24,
        task_states=task_states,
    )
    tasks = filter_tasks_by_status(tasks, None)
    lookup = build_task_lookup_from_tasks(tasks)

    tz = resolve_timezone(agenda_timezone)
    reference_date = resolve_agenda_date(agenda_date, tz)
    reminders = build_task_reminder_rows(
        task_states,
        tasks_by_key=lookup,
        include_completed=False,
        status_filter=None,
    )
    agenda = build_task_agenda_rows(
        task_states,
        tasks_by_key=lookup,
        include_completed=False,
        status_filter=None,
        reference_date=reference_date,
        agenda_days=max(agenda_days, 0),
        agenda_timezone=tz,
    )
    visible_states = collect_visible_task_states(
        task_states,
        include_completed=True,
        status_filter=None,
    )

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reference_date": reference_date.isoformat(),
            "agenda_days": max(agenda_days, 0),
            "agenda_timezone": agenda_timezone,
        },
        "filters": {
            "school": profile.school or normalized_school,
            "user_id": user_id or "",
            "task_source": source_summary["requested"],
            "task_source_effective": source_summary["effective"],
            "task_source_exists": source_summary["exists"],
            "task_source_path": str(source_summary["path"]) if source_summary["path"] else "",
        },
        "profile": {
            "user_id": user_id or "",
            "school": profile.school or normalized_school,
            "program_type": profile.program_type,
            "origin": profile.origin,
            "has_conditional_offer": profile.has_conditional_offer,
            "completed_flags": sorted(profile.completed_flags),
            "completed_flags_label": format_completed_flags(profile.completed_flags),
        },
        "summary": {
            "active_task_count": len(tasks),
            "tracked_state_count": len(visible_states),
            "reminder_count": len(reminders),
            "agenda_count": len(agenda),
            "overdue_count": sum(1 for item in agenda if item["bucket"] == "overdue"),
            "today_count": sum(1 for item in agenda if item["bucket"] == "today"),
            "upcoming_count": sum(1 for item in agenda if item["bucket"] == "upcoming"),
        },
        "catalog": {
            "schools": load_school_catalog(schools_csv),
            "task_statuses": sorted(status for status in VALID_STATUSES if status),
            "reminder_statuses": sorted(status for status in VALID_REMINDER_STATUSES if status),
            "timezones": ["Asia/Hong_Kong", "Asia/Shanghai", "UTC"],
        },
        "tasks": [serialize_task(task, task_states) for task in tasks],
        "reminders": [serialize_reminder(item, task_states) for item in reminders],
        "agenda": [serialize_agenda_item(item, task_states) for item in agenda],
        "states": [serialize_task_state(state) for state in visible_states],
        "empty_hints": build_empty_hints(
            user_id=user_id or "",
            source_summary=source_summary,
            task_states=task_states,
            tasks=tasks,
        ),
    }


def load_dashboard_profile(
    *,
    user_id: str | None,
    school: str,
    user_state_csv: Path | str,
    task_states: dict[str, TaskState],
) -> StudentProfile:
    inferred_school = school or infer_school_from_task_states(task_states) or ""
    stored = load_user_profile(user_id, user_state_csv) if user_id else None
    if stored is not None:
        return StudentProfile(
            school=stored.school or inferred_school or None,
            program_type=stored.program_type,
            origin=stored.origin,
            completed_flags=set(stored.completed_flags),
            has_conditional_offer=stored.has_conditional_offer,
        )
    return StudentProfile(school=inferred_school or None)


def load_dashboard_task_states(
    *,
    user_id: str | None,
    school: str,
    task_state_csv: Path | str,
) -> dict[str, TaskState]:
    if not user_id:
        return {}
    return load_user_task_states(user_id, task_state_csv, school=school or None)


def resolve_dashboard_task_source(
    *,
    task_source: str,
    tasks_csv: Path | str | None,
    tasks_enriched_csv: Path | str,
    tasks_reviewed_csv: Path | str,
) -> dict[str, Any]:
    requested = (task_source or "reviewed").strip().lower()
    reviewed_path = Path(tasks_reviewed_csv)
    enriched_path = Path(tasks_enriched_csv)
    default_tasks_path = Path(tasks_csv) if tasks_csv else None

    if requested == "reviewed":
        if reviewed_path.exists():
            return {
                "requested": "reviewed",
                "effective": "reviewed",
                "exists": True,
                "path": reviewed_path,
            }
        if enriched_path.exists():
            return {
                "requested": "reviewed",
                "effective": "enriched",
                "exists": False,
                "path": enriched_path,
            }
        return {
            "requested": "reviewed",
            "effective": "builtin",
            "exists": False,
            "path": None,
        }

    if requested == "enriched":
        if enriched_path.exists():
            return {
                "requested": "enriched",
                "effective": "enriched",
                "exists": True,
                "path": enriched_path,
            }
        return {
            "requested": "enriched",
            "effective": "builtin",
            "exists": False,
            "path": None,
        }

    return {
        "requested": "builtin",
        "effective": "builtin",
        "exists": bool(default_tasks_path and default_tasks_path.exists()),
        "path": None,
    }


def build_task_lookup_from_tasks(tasks: list[PlannedTask]) -> dict[str, PlannedTask]:
    lookup: dict[str, PlannedTask] = {}
    for task in tasks:
        lookup[task.task_id] = task
        if task.task_code:
            lookup[task.task_code] = task
    return lookup


def load_school_catalog(path: Path | str) -> list[dict[str, str]]:
    school_path = Path(path)
    if not school_path.exists() or school_path.stat().st_size == 0:
        return []
    frame = pd.read_csv(school_path, dtype=str, keep_default_na=False)
    rows: list[dict[str, str]] = []
    for row in frame.to_dict(orient="records"):
        code = str(row.get("school_id", "")).strip().upper()
        name = str(row.get("school_name", "")).strip()
        if not code:
            continue
        rows.append({"code": code, "name": name})
    return rows


def serialize_task(task: PlannedTask, task_states: dict[str, TaskState]) -> dict[str, Any]:
    state = task_states.get(task.task_id) or task_states.get(task.task_code)
    return {
        "task_id": task.task_id,
        "task_code": task.task_code,
        "task_name": task.task_name,
        "stage": task.stage,
        "risk_level": task.risk_level,
        "description": task.description,
        "trigger_condition": task.trigger_condition,
        "deadline": task.deadline,
        "required_documents": task.required_documents,
        "action_url": task.action_url,
        "source_url": task.source_url,
        "priority_score": task.priority_score,
        "reason": task.reason,
        "task_status": task.user_task_status,
        "personal_status_updated_at": state.status_updated_at if state else "",
        "personal_deadline_at": task.user_deadline_at,
        "personal_deadline_timezone": task.user_deadline_timezone,
        "personal_deadline_source": task.user_deadline_source,
        "personal_deadline_source_ref": state.deadline_source_ref if state else "",
        "personal_reminder_at": task.user_reminder_at,
        "personal_reminder_timezone": state.reminder_timezone if state else "",
        "personal_reminder_status": task.user_reminder_status,
        "personal_notes": task.user_task_notes,
        "personal_state_updated_at": state.updated_at if state else "",
        "evidence_count": task.evidence_count,
        "candidate_evidence_count": task.candidate_evidence_count,
        "usable_evidence_count": task.usable_evidence_count,
        "review_evidence_count": task.review_evidence_count,
        "rejected_evidence_count": task.rejected_evidence_count,
        "evidence_quality_status": task.evidence_quality_status,
        "evidence_quality_notes": task.evidence_quality_notes,
        "enrichment_status": task.enrichment_status,
        "review_priority": task.review_priority,
        "review_reason": task.review_reason,
        "review_decision": task.review_decision,
        "review_notes": task.review_notes,
        "human_review_status": task.human_review_status,
        "reviewed_at": task.reviewed_at,
        "official_deadline_evidence": task.official_deadline_evidence,
        "official_document_evidence": task.official_document_evidence,
        "official_action_evidence": task.official_action_evidence,
        "official_action_urls": task.official_action_urls,
        "official_fee_evidence": task.official_fee_evidence,
    }


def serialize_reminder(item: dict[str, str], task_states: dict[str, TaskState]) -> dict[str, Any]:
    state = task_states.get(item["task_id"], TaskState(user_id=""))
    return {
        **item,
        "deadline_source_ref": state.deadline_source_ref,
        "notes": state.notes,
    }


def serialize_agenda_item(item: dict[str, Any], task_states: dict[str, TaskState]) -> dict[str, Any]:
    state = task_states.get(item["task_id"], TaskState(user_id=""))
    return {
        "task_id": item["task_id"],
        "task_name": item["task_name"],
        "status": item["status"],
        "anchor_kind": item["anchor_kind"],
        "anchor_at": item["anchor_at"].isoformat(timespec="minutes"),
        "deadline_at": item["deadline_at"],
        "deadline_timezone": item["deadline_timezone"],
        "deadline_source_ref": state.deadline_source_ref,
        "reminder_at": item["reminder_at"],
        "reminder_timezone": item["reminder_timezone"],
        "reminder_status": item["reminder_status"],
        "action_url": item["action_url"],
        "bucket": item["bucket"],
        "notes": state.notes,
    }


def serialize_task_state(state: TaskState) -> dict[str, Any]:
    return asdict(state)


def save_task_state_from_payload(
    payload: dict[str, Any],
    *,
    task_state_csv: Path | str = DEFAULT_USER_TASK_STATE_CSV,
) -> TaskState:
    user_id = str(payload.get("user_id", "") or "").strip()
    if not user_id:
        raise ValueError("user_id is required")

    school = normalize_school(str(payload.get("school", "") or "").strip()) or str(payload.get("school", "") or "").strip()
    task_id = str(payload.get("task_id", "") or "").strip()
    task_code = str(payload.get("task_code", "") or "").strip()
    if not task_id and not task_code:
        raise ValueError("task_id or task_code is required")
    if not task_id and task_code and school:
        task_id = f"{school.lower()}-{task_code}"

    return upsert_user_task_state(
        user_id=user_id,
        path=task_state_csv,
        school=school,
        task_id=task_id,
        task_code=task_code,
        stage=str(payload.get("stage", "") or "").strip(),
        status=str(payload.get("status", "") or "").strip(),
        deadline_at=str(payload.get("deadline_at", "") or "").strip(),
        deadline_timezone=str(payload.get("deadline_timezone", "") or "").strip(),
        deadline_source=str(payload.get("deadline_source", "") or "").strip(),
        deadline_source_ref=str(payload.get("deadline_source_ref", "") or "").strip(),
        reminder_at=str(payload.get("reminder_at", "") or "").strip(),
        reminder_timezone=str(payload.get("reminder_timezone", "") or "").strip(),
        reminder_status=str(payload.get("reminder_status", "") or "").strip(),
        notes=str(payload.get("notes", "") or "").strip(),
    )


def build_empty_hints(
    *,
    user_id: str,
    source_summary: dict[str, Any],
    task_states: dict[str, TaskState],
    tasks: list[PlannedTask],
) -> list[str]:
    hints: list[str] = []
    if not user_id:
        hints.append("还没有选择 user_id，前端会先展示学校级任务模板，不展示个人 deadline / reminder。")
    elif not task_states:
        hints.append("这个 user_id 还没有写入个人任务状态，当前只展示任务模板和官方依据。")
    if source_summary["requested"] == "reviewed" and source_summary["effective"] != "reviewed":
        hints.append("`tasks_reviewed.csv` 还不存在，当前已自动回退到候选证据层或内置任务模板。")
    if not tasks:
        hints.append("当前筛不出进行中任务；可以先补充 user_state / user_task_states 或切换任务源。")
    return hints
