"""Deployment-friendly entrypoint that seeds runtime data before serving."""

from __future__ import annotations

from app.frontend_server import main as frontend_server_main
from app.runtime_data import ensure_runtime_data_seeded


def main(argv: list[str] | None = None) -> int:
    ensure_runtime_data_seeded()
    return frontend_server_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
