"""CSV-backed per-task state for user-specific offer-holder workflows."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_USER_TASK_STATE_CSV = ROOT_DIR / "data" / "cleaned" / "user_task_states.csv"


USER_TASK_STATE_COLUMNS = [
    "user_id",
    "school",
    "task_id",
    "task_code",
    "stage",
    "status",
    "status_updated_at",
    "deadline_at",
    "deadline_timezone",
    "deadline_source",
    "deadline_source_ref",
    "reminder_at",
    "reminder_timezone",
    "reminder_status",
    "notes",
    "updated_at",
]


VALID_STATUSES = {
    "",
    "not_started",
    "in_progress",
    "waiting",
    "blocked",
    "done",
    "skipped",
}

VALID_REMINDER_STATUSES = {
    "",
    "pending",
    "sent",
    "dismissed",
    "disabled",
}


@dataclass(frozen=True)
class TaskState:
    user_id: str
    school: str = ""
    task_id: str = ""
    task_code: str = ""
    stage: str = ""
    status: str = ""
    status_updated_at: str = ""
    deadline_at: str = ""
    deadline_timezone: str = ""
    deadline_source: str = ""
    deadline_source_ref: str = ""
    reminder_at: str = ""
    reminder_timezone: str = ""
    reminder_status: str = ""
    notes: str = ""
    updated_at: str = ""


def read_user_task_states(path: Path | str = DEFAULT_USER_TASK_STATE_CSV) -> pd.DataFrame:
    state_path = Path(path)
    if not state_path.exists() or state_path.stat().st_size == 0:
        return pd.DataFrame(columns=USER_TASK_STATE_COLUMNS)
    frame = pd.read_csv(state_path, dtype=str, keep_default_na=False)
    for column in USER_TASK_STATE_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[USER_TASK_STATE_COLUMNS]


def load_user_task_states(
    user_id: str,
    path: Path | str = DEFAULT_USER_TASK_STATE_CSV,
    *,
    school: str | None = None,
) -> dict[str, TaskState]:
    frame = read_user_task_states(path)
    if frame.empty:
        return {}

    rows = frame[frame["user_id"] == user_id].copy()
    if school:
        rows = rows[
            (rows["school"].str.lower() == school.lower())
            | (rows["school"].str.strip() == "")
        ]

    result: dict[str, TaskState] = {}
    for row in rows.to_dict(orient="records"):
        state = row_to_task_state(row)
        if state.task_id:
            result[state.task_id] = state
        if state.task_code and state.task_code not in result:
            result[state.task_code] = state
    return result


def upsert_user_task_state(
    *,
    user_id: str,
    path: Path | str = DEFAULT_USER_TASK_STATE_CSV,
    school: str = "",
    task_id: str = "",
    task_code: str = "",
    stage: str = "",
    status: str = "",
    deadline_at: str = "",
    deadline_timezone: str = "",
    deadline_source: str = "",
    deadline_source_ref: str = "",
    reminder_at: str = "",
    reminder_timezone: str = "",
    reminder_status: str = "",
    notes: str = "",
) -> TaskState:
    if not user_id:
        raise ValueError("user_id is required")
    if not task_id and not task_code:
        raise ValueError("task_id or task_code is required")
    validate_status(status)
    validate_reminder_status(reminder_status)

    now = datetime.now(UTC).isoformat(timespec="seconds")
    state = TaskState(
        user_id=user_id,
        school=school,
        task_id=task_id,
        task_code=task_code,
        stage=stage,
        status=status,
        status_updated_at=now if status else "",
        deadline_at=deadline_at,
        deadline_timezone=deadline_timezone,
        deadline_source=deadline_source,
        deadline_source_ref=deadline_source_ref,
        reminder_at=reminder_at,
        reminder_timezone=reminder_timezone,
        reminder_status=reminder_status,
        notes=notes,
        updated_at=now,
    )

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = read_user_task_states(output)

    key_task_id = task_id.strip()
    key_task_code = task_code.strip()
    keep_rows = []
    for row in frame.to_dict(orient="records"):
        same_user = row.get("user_id", "") == user_id
        same_task_id = bool(key_task_id) and row.get("task_id", "") == key_task_id
        same_task_code = bool(key_task_code) and row.get("task_code", "") == key_task_code
        if same_user and (same_task_id or same_task_code):
            continue
        keep_rows.append(row)

    new_frame = pd.DataFrame([*keep_rows, task_state_to_row(state)], columns=USER_TASK_STATE_COLUMNS)
    new_frame.to_csv(output, index=False, encoding="utf-8-sig")
    return state


def validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid task status: {status}")


def validate_reminder_status(status: str) -> None:
    if status not in VALID_REMINDER_STATUSES:
        raise ValueError(f"invalid reminder status: {status}")


def row_to_task_state(row: dict[str, object]) -> TaskState:
    values = {column: str(row.get(column, "") or "") for column in USER_TASK_STATE_COLUMNS}
    return TaskState(**values)


def task_state_to_row(state: TaskState) -> dict[str, str]:
    return {column: str(getattr(state, column)) for column in USER_TASK_STATE_COLUMNS}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect or update per-task user state CSV.")
    parser.add_argument("--state-csv", type=Path, default=DEFAULT_USER_TASK_STATE_CSV)
    parser.add_argument("--user-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = read_user_task_states(args.state_csv)
    if args.user_id:
        frame = frame[frame["user_id"] == args.user_id]
    if frame.empty:
        print("暂无用户任务状态记录")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=USER_TASK_STATE_COLUMNS)
        writer.writeheader()
        for row in frame.to_dict(orient="records"):
            writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
