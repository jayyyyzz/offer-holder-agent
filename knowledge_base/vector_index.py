"""Build either a sparse fallback index or an optional Chroma-backed index."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import sys
from typing import Any

import requests

import pandas as pd

from agent.rag_retriever import CHUNK_COLUMNS, DEFAULT_CHUNKS_CSV, ROOT_DIR


DEFAULT_VECTOR_INDEX_CSV = ROOT_DIR / "knowledge_base" / "vector_index.csv"
DEFAULT_CHROMA_DIR = ROOT_DIR / "knowledge_base" / "chroma"
DEFAULT_CHROMA_COLLECTION = "offer_holder_chunks"
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"


VECTOR_INDEX_COLUMNS = [
    "chunk_id",
    "school",
    "page_type",
    "stage",
    "title",
    "source_url",
    "raw_file",
    "token_count",
    "vector_json",
    "updated_at",
]


VECTOR_BACKENDS = {"sparse", "chroma"}
EMBEDDING_PROVIDERS = {"hash", "openai"}


STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "you",
    "your",
    "will",
    "can",
    "may",
    "not",
    "all",
    "has",
    "have",
    "into",
    "their",
    "there",
    "please",
    "student",
    "students",
    "university",
    "hong",
    "kong",
}


@dataclass(frozen=True)
class VectorSearchResult:
    chunk_id: str
    score: float
    title: str
    source_url: str


def build_vector_index(
    chunks_csv: Path | str = DEFAULT_CHUNKS_CSV,
    *,
    backend: str = "sparse",
    max_terms: int = 80,
    chroma_dir: Path | str = DEFAULT_CHROMA_DIR,
    collection_name: str = DEFAULT_CHROMA_COLLECTION,
    embedding_provider: str = "hash",
    embedding_dimensions: int = 256,
    openai_api_key_env: str = "OPENAI_API_KEY",
    openai_embedding_model: str = DEFAULT_OPENAI_EMBEDDING_MODEL,
) -> pd.DataFrame:
    if backend not in VECTOR_BACKENDS:
        raise ValueError(f"unsupported vector backend: {backend}")

    chunks = _read_chunks(Path(chunks_csv))
    if backend == "chroma":
        build_chroma_index(
            chunks,
            chroma_dir=Path(chroma_dir),
            collection_name=collection_name,
            embedding_provider=embedding_provider,
            embedding_dimensions=embedding_dimensions,
            openai_api_key_env=openai_api_key_env,
            openai_embedding_model=openai_embedding_model,
        )
        return pd.DataFrame(
            [
                {
                    "chunk_id": "__chroma_collection__",
                    "school": "",
                    "page_type": "",
                    "stage": "",
                    "title": collection_name,
                    "source_url": "",
                    "raw_file": str(Path(chroma_dir)),
                    "token_count": len(chunks),
                    "vector_json": json.dumps(
                        {
                            "backend": "chroma",
                            "collection_name": collection_name,
                            "embedding_provider": embedding_provider,
                            "embedding_dimensions": embedding_dimensions,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            ],
            columns=VECTOR_INDEX_COLUMNS,
        )

    rows: list[dict[str, object]] = []
    updated_at = datetime.now(UTC).isoformat(timespec="seconds")

    for row in chunks.to_dict(orient="records"):
        text = " ".join(
            [
                row.get("school", ""),
                row.get("page_type", ""),
                row.get("stage", ""),
                row.get("title", ""),
                row.get("text", ""),
            ]
        )
        vector = sparse_vector(text, max_terms=max_terms)
        rows.append(
            {
                "chunk_id": row.get("chunk_id", ""),
                "school": row.get("school", ""),
                "page_type": row.get("page_type", ""),
                "stage": row.get("stage", ""),
                "title": row.get("title", ""),
                "source_url": row.get("source_url", "") or row.get("final_url", ""),
                "raw_file": row.get("raw_file", ""),
                "token_count": int(sum(vector.values())),
                "vector_json": json.dumps(vector, ensure_ascii=False, sort_keys=True),
                "updated_at": updated_at,
            }
        )

    return pd.DataFrame(rows, columns=VECTOR_INDEX_COLUMNS)


def write_vector_index(frame: pd.DataFrame, output_path: Path | str = DEFAULT_VECTOR_INDEX_CSV) -> None:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output, index=False, encoding="utf-8-sig")


def search_vector_index(
    query: str,
    index_csv: Path | str = DEFAULT_VECTOR_INDEX_CSV,
    *,
    backend: str = "sparse",
    school: str | None = None,
    top_k: int = 5,
    chunks_csv: Path | str = DEFAULT_CHUNKS_CSV,
    chroma_dir: Path | str = DEFAULT_CHROMA_DIR,
    collection_name: str = DEFAULT_CHROMA_COLLECTION,
    embedding_provider: str = "hash",
    embedding_dimensions: int = 256,
    openai_api_key_env: str = "OPENAI_API_KEY",
    openai_embedding_model: str = DEFAULT_OPENAI_EMBEDDING_MODEL,
) -> list[VectorSearchResult]:
    if backend == "chroma":
        return search_chroma_index(
            query,
            chunks_csv=chunks_csv,
            school=school,
            top_k=top_k,
            chroma_dir=chroma_dir,
            collection_name=collection_name,
            embedding_provider=embedding_provider,
            embedding_dimensions=embedding_dimensions,
            openai_api_key_env=openai_api_key_env,
            openai_embedding_model=openai_embedding_model,
        )

    path = Path(index_csv)
    if not path.exists() or path.stat().st_size == 0:
        return []

    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    query_vector = sparse_vector(query, max_terms=80)
    if not query_vector:
        return []

    results: list[VectorSearchResult] = []
    for row in frame.to_dict(orient="records"):
        if school and row.get("school", "").lower() != school.lower():
            continue
        vector = json.loads(row.get("vector_json") or "{}")
        score = cosine_similarity(query_vector, vector)
        if score <= 0:
            continue
        results.append(
            VectorSearchResult(
                chunk_id=row.get("chunk_id", ""),
                score=score,
                title=row.get("title", ""),
                source_url=row.get("source_url", ""),
            )
        )

    results.sort(key=lambda item: item.score, reverse=True)
    return results[:top_k]


def build_chroma_index(
    chunks: pd.DataFrame,
    *,
    chroma_dir: Path,
    collection_name: str,
    embedding_provider: str,
    embedding_dimensions: int,
    openai_api_key_env: str,
    openai_embedding_model: str,
) -> None:
    if embedding_provider not in EMBEDDING_PROVIDERS:
        raise ValueError(f"unsupported embedding provider: {embedding_provider}")

    chromadb = _require_chromadb()
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    collection = client.get_or_create_collection(name=collection_name, metadata={"source": "offer-holder-agent"})

    rows = chunks.to_dict(orient="records")
    if not rows:
        return

    texts = [
        " ".join(
            [
                str(row.get("title", "")),
                str(row.get("text", "")),
            ]
        ).strip()
        for row in rows
    ]
    embeddings = embed_texts(
        texts,
        provider=embedding_provider,
        dimensions=embedding_dimensions,
        openai_api_key_env=openai_api_key_env,
        openai_embedding_model=openai_embedding_model,
    )
    ids = [str(row.get("chunk_id", "")) for row in rows]
    metadatas = [
        {
            "school": str(row.get("school", "")),
            "page_type": str(row.get("page_type", "")),
            "stage": str(row.get("stage", "")),
            "title": str(row.get("title", "")),
            "source_url": str(row.get("source_url", "")),
        }
        for row in rows
    ]
    documents = [str(row.get("text", "")) for row in rows]

    batch_size = 100
    for start in range(0, len(rows), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            metadatas=metadatas[start:end],
            documents=documents[start:end],
        )


def search_chroma_index(
    query: str,
    *,
    chunks_csv: Path | str = DEFAULT_CHUNKS_CSV,
    school: str | None = None,
    top_k: int = 5,
    chroma_dir: Path | str = DEFAULT_CHROMA_DIR,
    collection_name: str = DEFAULT_CHROMA_COLLECTION,
    embedding_provider: str = "hash",
    embedding_dimensions: int = 256,
    openai_api_key_env: str = "OPENAI_API_KEY",
    openai_embedding_model: str = DEFAULT_OPENAI_EMBEDDING_MODEL,
) -> list[VectorSearchResult]:
    chromadb = _require_chromadb()
    client = chromadb.PersistentClient(path=str(Path(chroma_dir)))
    collection = client.get_collection(collection_name)
    query_embedding = embed_texts(
        [query],
        provider=embedding_provider,
        dimensions=embedding_dimensions,
        openai_api_key_env=openai_api_key_env,
        openai_embedding_model=openai_embedding_model,
    )[0]

    query_kwargs: dict[str, Any] = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
    }
    if school:
        query_kwargs["where"] = {"school": school}
    result = collection.query(**query_kwargs)
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]

    rows = []
    for chunk_id, distance, metadata in zip(ids, distances, metadatas, strict=False):
        score = 1.0 / (1.0 + float(distance))
        rows.append(
            VectorSearchResult(
                chunk_id=str(chunk_id),
                score=score,
                title=str((metadata or {}).get("title", "")),
                source_url=str((metadata or {}).get("source_url", "")),
            )
        )
    return rows


def sparse_vector(text: str, *, max_terms: int = 80) -> dict[str, int]:
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]{2,}", text.lower())
        if token not in STOPWORDS and not token.isdigit()
    ]
    counts = Counter(tokens)
    return dict(counts.most_common(max_terms))


def cosine_similarity(left: dict[str, int], right: dict[str, int]) -> float:
    if not left or not right:
        return 0.0

    shared = set(left) & set(right)
    dot = sum(left[term] * int(right.get(term, 0)) for term in shared)
    if dot == 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(int(value) * int(value) for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def embed_texts(
    texts: list[str],
    *,
    provider: str,
    dimensions: int,
    openai_api_key_env: str,
    openai_embedding_model: str,
) -> list[list[float]]:
    if provider == "hash":
        return [hash_embedding(text, dimensions=dimensions) for text in texts]
    if provider == "openai":
        return openai_embed_texts(
            texts,
            api_key_env=openai_api_key_env,
            model=openai_embedding_model,
            dimensions=dimensions,
        )
    raise ValueError(f"unsupported embedding provider: {provider}")


def hash_embedding(text: str, *, dimensions: int = 256) -> list[float]:
    vector = [0.0] * dimensions
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]{2,}", text.lower())
        if token not in STOPWORDS and not token.isdigit()
    ]
    if not tokens:
        return vector
    for token in tokens:
        slot = hash(token) % dimensions
        vector[slot] += 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def openai_embed_texts(
    texts: list[str],
    *,
    api_key_env: str,
    model: str,
    dimensions: int,
) -> list[list[float]]:
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"OpenAI embedding provider requires env var {api_key_env}.")
    response = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "input": texts,
            "model": model,
            "dimensions": dimensions,
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    return [item["embedding"] for item in payload.get("data", [])]


def _read_chunks(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=CHUNK_COLUMNS)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column in CHUNK_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    return frame[CHUNK_COLUMNS]


def _require_chromadb():
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("chromadb is not installed. Install project dependencies first.") from exc
    return chromadb


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a local sparse vector index from chunks.csv.")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_VECTOR_INDEX_CSV)
    parser.add_argument("--backend", choices=sorted(VECTOR_BACKENDS), default="sparse")
    parser.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--collection-name", default=DEFAULT_CHROMA_COLLECTION)
    parser.add_argument("--embedding-provider", choices=sorted(EMBEDDING_PROVIDERS), default="hash")
    parser.add_argument("--embedding-dimensions", type=int, default=256)
    parser.add_argument("--openai-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--openai-embedding-model", default=DEFAULT_OPENAI_EMBEDDING_MODEL)
    parser.add_argument("--max-terms", type=int, default=80)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    frame = build_vector_index(
        args.chunks,
        backend=args.backend,
        max_terms=args.max_terms,
        chroma_dir=args.chroma_dir,
        collection_name=args.collection_name,
        embedding_provider=args.embedding_provider,
        embedding_dimensions=args.embedding_dimensions,
        openai_api_key_env=args.openai_api_key_env,
        openai_embedding_model=args.openai_embedding_model,
    )
    write_vector_index(frame, args.output)
    if args.backend == "sparse":
        print(f"已生成本地 sparse vector index：{len(frame)} 条 -> {args.output}")
    else:
        print(
            f"已生成 Chroma vector index：collection={args.collection_name}，"
            f"chunks={int(frame.iloc[0]['token_count']) if not frame.empty else 0}，"
            f"dir={args.chroma_dir}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
