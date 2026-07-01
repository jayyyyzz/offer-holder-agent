"""Minimal OpenAI Responses API client for grounded answer generation."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import time
import sys
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
DEFAULT_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_RUN_METADATA_DIR = ROOT_DIR / "data" / "metadata" / "openai_runs"


def build_responses_payload(
    prompt: str,
    *,
    model: str = DEFAULT_OPENAI_MODEL,
    max_output_tokens: int = 1200,
    reasoning_effort: str = "medium",
    text_verbosity: str = "low",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "text": {"verbosity": text_verbosity},
    }
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    return payload


def generate_grounded_response(
    prompt: str,
    *,
    api_key_env: str = DEFAULT_OPENAI_API_KEY_ENV,
    model: str = DEFAULT_OPENAI_MODEL,
    max_output_tokens: int = 1200,
    timeout_seconds: int = 60,
    responses_url: str = DEFAULT_RESPONSES_URL,
    reasoning_effort: str = "medium",
    text_verbosity: str = "low",
    max_retries: int = 2,
    retry_backoff_seconds: float = 2.0,
    run_metadata: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    api_key = os.environ.get(api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"OpenAI API key not found in environment variable {api_key_env}.")

    payload = build_responses_payload(
        prompt,
        model=model,
        max_output_tokens=max_output_tokens,
        reasoning_effort=reasoning_effort,
        text_verbosity=text_verbosity,
    )
    metadata: dict[str, Any] = {
        "status": "started",
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "api_key_env": api_key_env,
        "model": model,
        "responses_url": responses_url,
        "prompt_chars": len(prompt),
        "max_output_tokens": max_output_tokens,
        "timeout_seconds": timeout_seconds,
        "reasoning_effort": reasoning_effort,
        "text_verbosity": text_verbosity,
        "max_retries": max_retries,
        "retry_backoff_seconds": retry_backoff_seconds,
        "attempts": [],
    }
    last_error: RuntimeError | None = None
    for attempt in range(max_retries + 1):
        attempt_record: dict[str, Any] = {
            "attempt": attempt + 1,
            "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        try:
            response = requests.post(
                responses_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_seconds,
            )
            attempt_record["http_status"] = response.status_code
            if response.status_code in {408, 409, 429, 500, 502, 503, 504} and attempt < max_retries:
                attempt_record["result"] = "retryable_http_status"
                metadata["attempts"].append(attempt_record)
                _sync_run_metadata(run_metadata, metadata)
                time.sleep(retry_backoff_seconds * (attempt + 1))
                continue
            response.raise_for_status()
            data = response.json()
            if str(data.get("status", "") or "").strip() == "incomplete":
                attempt_record["result"] = "incomplete"
                attempt_record["response_status"] = str(data.get("status", "") or "").strip()
                attempt_record["incomplete_reason"] = extract_incomplete_reason(data)
                metadata["attempts"].append(attempt_record)
                metadata.update(
                    {
                        "status": "incomplete",
                        "attempt_count": attempt + 1,
                        "retry_count": attempt,
                        "response_id": str(data.get("id", "") or "").strip(),
                        "response_status": str(data.get("status", "") or "").strip(),
                        "incomplete_reason": extract_incomplete_reason(data),
                        "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    }
                )
                _sync_run_metadata(run_metadata, metadata)
                raise RuntimeError(
                    "Responses API returned incomplete output"
                    f" ({extract_incomplete_reason(data)}). Consider increasing max_output_tokens."
                )
            text = extract_output_text(data)
            attempt_record["result"] = "success"
            attempt_record["response_status"] = str(data.get("status", "") or "").strip()
            metadata["attempts"].append(attempt_record)
            metadata.update(
                {
                    "status": "success",
                    "attempt_count": attempt + 1,
                    "retry_count": attempt,
                    "response_id": str(data.get("id", "") or "").strip(),
                    "response_status": str(data.get("status", "") or "").strip(),
                    "output_excerpt": summarize_output_text(text),
                    "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            _sync_run_metadata(run_metadata, metadata)
            return text, data
        except requests.Timeout:
            attempt_record["result"] = "timeout"
            metadata["attempts"].append(attempt_record)
            last_error = RuntimeError(
                f"Responses API request timed out after {timeout_seconds} seconds."
            )
            metadata.update(
                {
                    "status": "timeout",
                    "attempt_count": attempt + 1,
                    "retry_count": attempt,
                    "error": str(last_error),
                    "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            _sync_run_metadata(run_metadata, metadata)
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds * (attempt + 1))
                continue
        except requests.HTTPError as error:
            status_code = error.response.status_code if error.response is not None else "unknown"
            attempt_record["result"] = "http_error"
            attempt_record["http_status"] = status_code
            metadata["attempts"].append(attempt_record)
            last_error = RuntimeError(f"Responses API request failed with HTTP {status_code}.")
            metadata.update(
                {
                    "status": "http_error",
                    "attempt_count": attempt + 1,
                    "retry_count": attempt,
                    "http_status": status_code,
                    "error": str(last_error),
                    "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            _sync_run_metadata(run_metadata, metadata)
            if error.response is not None and error.response.status_code in {408, 409, 429, 500, 502, 503, 504} and attempt < max_retries:
                time.sleep(retry_backoff_seconds * (attempt + 1))
                continue
        except requests.RequestException as error:
            attempt_record["result"] = "request_error"
            metadata["attempts"].append(attempt_record)
            last_error = RuntimeError(f"Responses API request failed: {error}")
            metadata.update(
                {
                    "status": "request_error",
                    "attempt_count": attempt + 1,
                    "retry_count": attempt,
                    "error": str(last_error),
                    "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            _sync_run_metadata(run_metadata, metadata)
            if attempt < max_retries:
                time.sleep(retry_backoff_seconds * (attempt + 1))
                continue
        except RuntimeError as error:
            last_error = error
            metadata.update(
                {
                    "status": metadata.get("status", "runtime_error"),
                    "attempt_count": attempt + 1,
                    "retry_count": attempt,
                    "error": str(last_error),
                    "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            _sync_run_metadata(run_metadata, metadata)
            break
    metadata.update(
        {
            "status": metadata.get("status", "failed"),
            "attempt_count": metadata.get("attempt_count", max_retries + 1),
            "retry_count": metadata.get("retry_count", max_retries),
            "error": str(last_error or "Responses API request failed."),
            "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    _sync_run_metadata(run_metadata, metadata)
    raise last_error or RuntimeError("Responses API request failed.")


def extract_output_text(payload: dict[str, Any]) -> str:
    output_text = str(payload.get("output_text", "") or "").strip()
    if output_text:
        return output_text

    parts: list[str] = []
    for item in payload.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
            text_obj = content.get("text", {})
            if isinstance(text_obj, dict):
                nested_value = str(text_obj.get("value", "") or "").strip()
                if nested_value:
                    parts.append(nested_value)
    combined = "\n\n".join(parts).strip()
    if combined:
        return combined
    raise RuntimeError("Responses API returned no output_text.")


def extract_incomplete_reason(payload: dict[str, Any]) -> str:
    details = payload.get("incomplete_details", {}) or {}
    if isinstance(details, dict):
        reason = str(details.get("reason", "") or "").strip()
        if reason:
            return reason
    return "unknown"


def summarize_output_text(text: str, *, limit: int = 200) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def write_openai_run_metadata(
    metadata: dict[str, Any],
    *,
    output_dir: Path | str = DEFAULT_OPENAI_RUN_METADATA_DIR,
) -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    response_id = str(metadata.get("response_id", "") or "").strip() or "no_response_id"
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path = target_dir / f"{timestamp}_{response_id}.json"
    output_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _sync_run_metadata(target: dict[str, Any] | None, source: dict[str, Any]) -> None:
    if target is None:
        return
    target.clear()
    target.update(source)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a grounded prompt through the OpenAI Responses API.")
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL)
    parser.add_argument("--api-key-env", default=DEFAULT_OPENAI_API_KEY_ENV)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--responses-url", default=DEFAULT_RESPONSES_URL)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--text-verbosity", default="low")
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=2.0)
    parser.add_argument("--run-metadata-dir", type=Path, default=DEFAULT_OPENAI_RUN_METADATA_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    prompt = args.prompt_file.read_text(encoding="utf-8")
    metadata_capture: dict[str, Any] = {}
    try:
        text, raw = generate_grounded_response(
            prompt,
            api_key_env=args.api_key_env,
            model=args.model,
            max_output_tokens=args.max_output_tokens,
            timeout_seconds=args.timeout_seconds,
            responses_url=args.responses_url,
            reasoning_effort=args.reasoning_effort,
            text_verbosity=args.text_verbosity,
            max_retries=args.max_retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
            run_metadata=metadata_capture,
        )
    except RuntimeError:
        if metadata_capture:
            write_openai_run_metadata(metadata_capture, output_dir=args.run_metadata_dir)
        raise
    if metadata_capture:
        write_openai_run_metadata(metadata_capture, output_dir=args.run_metadata_dir)
    print(text)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    print(json.dumps({"id": raw.get("id", ""), "model": raw.get("model", args.model)}, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
