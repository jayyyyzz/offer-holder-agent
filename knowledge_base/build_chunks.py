"""Build ``knowledge_base/chunks.csv`` from archived raw official pages."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from agent.rag_retriever import (
    DEFAULT_CHUNKS_CSV,
    DEFAULT_CLEAN_FAQ_CSV,
    DEFAULT_RAW_DIR,
    LocalRagRetriever,
)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Build local retrieval chunks from raw pages.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_CHUNKS_CSV)
    parser.add_argument("--faq-csv", type=Path, default=DEFAULT_CLEAN_FAQ_CSV)
    parser.add_argument("--no-faq", action="store_true", help="Do not include structured cleaned FAQ chunks")
    args = parser.parse_args(argv)

    faq_csv = None if args.no_faq or not args.faq_csv.exists() else args.faq_csv
    chunks = LocalRagRetriever(raw_dir=args.raw_dir, chunks_csv=args.output).export_chunks(
        args.output,
        faq_csv=faq_csv,
    )
    print(f"已构建 {len(chunks)} 条 chunks -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
