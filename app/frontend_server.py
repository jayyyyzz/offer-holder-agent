"""Local dashboard server for the frontend workspace."""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
import hmac
import json
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.dashboard_api import (
    DEFAULT_FRONTEND_STATE,
    build_dashboard_payload,
    save_task_state_from_payload,
)


ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8123


class OfferDashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str | None = None, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({"status": "ok", "read_only": read_only_mode_enabled()})
            return
        if not self.authorize_request():
            return
        if parsed.path == "/api/dashboard":
            self.handle_dashboard_api(parsed.query)
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self.authorize_request():
            return
        if parsed.path == "/api/task-state":
            if read_only_mode_enabled():
                self.send_json(
                    {"error": "server is running in read-only mode"},
                    status=HTTPStatus.FORBIDDEN,
                )
                return
            self.handle_task_state_api()
            return
        self.send_json({"error": "Not found."}, status=HTTPStatus.NOT_FOUND)

    def handle_dashboard_api(self, query: str) -> None:
        params = parse_qs(query)
        payload = build_dashboard_payload(
            school=first_value(params, "school", DEFAULT_FRONTEND_STATE["school"]),
            user_id=first_value(params, "user_id", DEFAULT_FRONTEND_STATE["user_id"]),
            task_source=first_value(params, "task_source", DEFAULT_FRONTEND_STATE["task_source"]),
            agenda_days=parse_int(first_value(params, "agenda_days", str(DEFAULT_FRONTEND_STATE["agenda_days"]))),
            agenda_timezone=first_value(
                params,
                "agenda_timezone",
                DEFAULT_FRONTEND_STATE["agenda_timezone"],
            ),
            agenda_date=first_value(params, "agenda_date", ""),
        )
        self.send_json(payload)

    def handle_task_state_api(self) -> None:
        try:
            payload = self.read_json_body()
            state = save_task_state_from_payload(payload)
        except ValueError as error:
            self.send_json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"status": "ok", "state": asdict(state)})

    def read_json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            raise ValueError("request body is required")
        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("invalid JSON body") from error
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorize_request(self) -> bool:
        credentials = get_basic_auth_credentials()
        if credentials is None:
            return True
        username, password = credentials
        header = self.headers.get("Authorization", "")
        if validate_basic_auth_header(header, expected_user=username, expected_password=password):
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Offer Holder Agent"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return False


def first_value(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    if not values:
        return default
    return values[0].strip() or default


def parse_int(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_FRONTEND_STATE["agenda_days"]


def resolve_server_host() -> str:
    return str(os.environ.get("OFFER_AGENT_HOST", DEFAULT_HOST) or DEFAULT_HOST).strip() or DEFAULT_HOST


def resolve_server_port() -> int:
    for key in ("PORT", "OFFER_AGENT_PORT"):
        value = str(os.environ.get(key, "") or "").strip()
        if not value:
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return DEFAULT_PORT


def read_only_mode_enabled() -> bool:
    return is_truthy_env(os.environ.get("OFFER_AGENT_READ_ONLY", ""))


def get_basic_auth_credentials() -> tuple[str, str] | None:
    username = str(os.environ.get("OFFER_AGENT_BASIC_AUTH_USER", "") or "").strip()
    password = str(os.environ.get("OFFER_AGENT_BASIC_AUTH_PASSWORD", "") or "").strip()
    if not username or not password:
        return None
    return username, password


def validate_basic_auth_header(
    header: str,
    *,
    expected_user: str,
    expected_password: str,
) -> bool:
    if not header.startswith("Basic "):
        return False
    encoded = header.split(" ", 1)[1].strip()
    if not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return hmac.compare_digest(username, expected_user) and hmac.compare_digest(
        password,
        expected_password,
    )


def is_truthy_env(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the local offer-holder dashboard frontend.")
    parser.add_argument("--host", default=resolve_server_host())
    parser.add_argument("--port", type=int, default=resolve_server_port())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), OfferDashboardHandler)
    print(f"Offer dashboard running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
