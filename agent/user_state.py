"""CSV-backed user state persistence for the initial agent."""

from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
import sys

import pandas as pd

from agent.task_planner import StudentProfile


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_USER_STATE_CSV = ROOT_DIR / "data" / "cleaned" / "user_states.csv"


USER_STATE_COLUMNS = [
    "user_id",
    "school",
    "origin",
    "program_type",
    "has_conditional_offer",
    "completed_flags",
    "notes",
    "updated_at",
]


def load_user_profile(
    user_id: str,
    path: Path | str = DEFAULT_USER_STATE_CSV,
) -> StudentProfile | None:
    frame = read_user_state(path)
    if frame.empty:
        return None
    rows = frame[frame["user_id"] == user_id]
    if rows.empty:
        return None
    row = rows.iloc[-1].to_dict()
    return row_to_profile(row)


def save_user_profile(
    user_id: str,
    profile: StudentProfile,
    *,
    path: Path | str = DEFAULT_USER_STATE_CSV,
    notes: str = "",
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame = read_user_state(output)
    row = profile_to_row(user_id, profile, notes=notes)

    if frame.empty:
        frame = pd.DataFrame([row], columns=USER_STATE_COLUMNS)
    elif user_id in set(frame["user_id"]):
        frame = frame[frame["user_id"] != user_id]
        frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    else:
        frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)

    frame[USER_STATE_COLUMNS].to_csv(output, index=False, encoding="utf-8-sig")


def merge_profiles(stored: StudentProfile | None, current: StudentProfile) -> StudentProfile:
    if stored is None:
        return current

    return replace(
        stored,
        school=current.school or stored.school,
        origin=current.origin or stored.origin,
        program_type=current.program_type or stored.program_type,
        completed_flags=set(stored.completed_flags) | set(current.completed_flags),
        has_conditional_offer=(
            current.has_conditional_offer
            if current.has_conditional_offer is not None
            else stored.has_conditional_offer
        ),
    )


def profile_to_row(user_id: str, profile: StudentProfile, *, notes: str = "") -> dict[str, str]:
    return {
        "user_id": user_id,
        "school": profile.school or "",
        "origin": profile.origin,
        "program_type": profile.program_type,
        "has_conditional_offer": _bool_to_text(profile.has_conditional_offer),
        "completed_flags": ";".join(sorted(profile.completed_flags)),
        "notes": notes,
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def row_to_profile(row: dict[str, object]) -> StudentProfile:
    return StudentProfile(
        school=str(row.get("school", "") or "") or None,
        origin=str(row.get("origin", "") or "Mainland China"),
        program_type=str(row.get("program_type", "") or "TPG"),
        completed_flags={
            item.strip()
            for item in str(row.get("completed_flags", "")).split(";")
            if item.strip()
        },
        has_conditional_offer=_text_to_bool(str(row.get("has_conditional_offer", ""))),
    )


def read_user_state(path: Path | str = DEFAULT_USER_STATE_CSV) -> pd.DataFrame:
    state_path = Path(path)
    if not state_path.exists() or state_path.stat().st_size == 0:
        return pd.DataFrame(columns=USER_STATE_COLUMNS)
    frame = pd.read_csv(state_path, dtype=str, keep_default_na=False)
    for column in USER_STATE_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[USER_STATE_COLUMNS]


def _bool_to_text(value: bool | None) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return ""


def _text_to_bool(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "1"}:
        return True
    if lowered in {"false", "no", "0"}:
        return False
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect user state CSV.")
    parser.add_argument("--state-csv", type=Path, default=DEFAULT_USER_STATE_CSV)
    parser.add_argument("--user-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = read_user_state(args.state_csv)
    if args.user_id:
        frame = frame[frame["user_id"] == args.user_id]
    if frame.empty:
        print("暂无用户状态记录")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=USER_STATE_COLUMNS)
        writer.writeheader()
        for row in frame.to_dict(orient="records"):
            writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
