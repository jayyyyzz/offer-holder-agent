"""Bootstrap persistent runtime data for deployment environments."""

from __future__ import annotations

import os
from pathlib import Path
import shutil


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_DATA_ROOT = ROOT_DIR / "data"
DEFAULT_SEED_DATA_ROOT = ROOT_DIR / "data"


def ensure_runtime_data_seeded() -> bool:
    runtime_root = resolve_runtime_data_root()
    seed_root = resolve_seed_data_root()
    if runtime_root.resolve() == seed_root.resolve():
        _ensure_runtime_subdirs(runtime_root)
        return False

    runtime_root.mkdir(parents=True, exist_ok=True)
    if not seed_root.exists():
        _ensure_runtime_subdirs(runtime_root)
        return False

    copied = False
    for subdir_name in ("cleaned", "metadata"):
        copied = _copy_missing_tree(seed_root / subdir_name, runtime_root / subdir_name) or copied
    _ensure_runtime_subdirs(runtime_root)
    return copied


def resolve_runtime_data_root() -> Path:
    value = str(os.environ.get("OFFER_AGENT_RUNTIME_DATA_ROOT", "") or "").strip()
    if value:
        return Path(value)
    return DEFAULT_RUNTIME_DATA_ROOT


def resolve_seed_data_root() -> Path:
    value = str(os.environ.get("OFFER_AGENT_SEED_DATA_ROOT", "") or "").strip()
    if value:
        return Path(value)
    return DEFAULT_SEED_DATA_ROOT


def _copy_missing_tree(source_dir: Path, target_dir: Path) -> bool:
    if not source_dir.exists():
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = False
    for path in source_dir.rglob("*"):
        relative = path.relative_to(source_dir)
        destination = target_dir / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        copied = True
    return copied


def _ensure_runtime_subdirs(root: Path) -> None:
    (root / "cleaned").mkdir(parents=True, exist_ok=True)
    (root / "metadata").mkdir(parents=True, exist_ok=True)
    (root / "metadata" / "openai_runs").mkdir(parents=True, exist_ok=True)
