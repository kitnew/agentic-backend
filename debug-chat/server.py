#!/usr/bin/env python3
"""Tiny stdlib debug chat server for the agentic backend.

Serves index.html and proxies browser requests to the backend to avoid CORS issues.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DEFAULT_BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
DEFAULT_API_PATH = os.getenv("API_PATH", "/api/v1/messages")
HOST = os.getenv("DEBUG_CHAT_HOST", "127.0.0.1")
PORT = int(os.getenv("DEBUG_CHAT_PORT", "8080"))


class DebugChatHandler(BaseHTTPRequestHandler):
    server_version = "DebugChat/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if self.path in ("/", "/index.html"):
            self._send_file(ROOT / "index.html", "text/html; charset=utf-8")
            return

        if self.path == "/config":
            self._send_json(
                200,
                {
                    "backend_url": DEFAULT_BACKEND_URL,
                    "api_path": DEFAULT_API_PATH,
                },
            )
            return

        self._send_json(404, {"error": "Not found"})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib API
        if self.path in ("/", "/index.html"):
            self._send_headers(200, "text/html; charset=utf-8", (ROOT / "index.html").stat().st_size)
            return

        if self.path == "/config":
            self._send_headers(200, "application/json; charset=utf-8", 0)
            return

        self._send_headers(404, "application/json; charset=utf-8", 0)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/debug/message":
            self._handle_debug_message()
            return

        if parsed_path.path == "/debug/voice-message":
            self._handle_debug_voice_message(parsed_path.query)
            return

        self._send_json(404, {"error": "Not found"})

    def _handle_debug_message(self) -> None:
        try:
            request_body = self._read_json()
            backend_url = str(request_body.get("backend_url") or DEFAULT_BACKEND_URL).rstrip("/")
            api_path = self._normalize_api_path(str(request_body.get("api_path") or DEFAULT_API_PATH))

            payload = request_body["payload"]
            status_code, response_body = self._post_json(f"{backend_url}{api_path}", payload)
            self._send_json(
                200,
                {
                    "proxied_status": status_code,
                    "backend_url": backend_url,
                    "api_path": api_path,
                    "request_payload": payload,
                    "response": response_body,
                },
            )
        except KeyError:
            self._send_json(400, {"error": "Missing required field: payload"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except HTTPError as exc:
            self._send_json(
                200,
                {
                    "proxied_status": exc.code,
                    "response": self._decode_response(exc.read()),
                },
            )
        except URLError as exc:
            self._send_json(502, {"error": f"Backend request failed: {exc.reason}"})

    def _handle_debug_voice_message(self, query: str) -> None:
        try:
            params = parse_qs(query)
            backend_url = str(
                self._first_query_value(params, "backend_url") or DEFAULT_BACKEND_URL
            ).rstrip("/")
            api_path = self._normalize_api_path(
                self._first_query_value(params, "api_path") or "/api/v1/voice/messages"
            )
            content_type = self.headers.get("Content-Type", "")
            if not content_type.startswith("multipart/form-data"):
                raise ValueError("Voice debug proxy expects multipart/form-data")

            request_body = self._read_raw_body()
            status_code, response_body = self._post_multipart(
                f"{backend_url}{api_path}",
                request_body,
                content_type,
            )
            self._send_json(
                200,
                {
                    "proxied_status": status_code,
                    "backend_url": backend_url,
                    "api_path": api_path,
                    "response": response_body,
                },
            )
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except HTTPError as exc:
            self._send_json(
                200,
                {
                    "proxied_status": exc.code,
                    "response": self._decode_response(exc.read()),
                },
            )
        except URLError as exc:
            self._send_json(502, {"error": f"Backend request failed: {exc.reason}"})

    def _first_query_value(self, params: dict[str, list[str]], name: str) -> str | None:
        values = params.get(name)
        if not values:
            return None
        return values[0]

    def _normalize_api_path(self, api_path: str) -> str:
        if not api_path.startswith("/"):
            return f"/{api_path}"
        return api_path

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json(self) -> dict:
        raw_body = self._read_raw_body()
        if not raw_body:
            raise ValueError("Request body is empty")

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        return body

    def _read_raw_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            raise ValueError("Request body is empty")

        return self.rfile.read(content_length)

    def _post_json(self, url: str, payload: dict) -> tuple[int, object]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid backend URL: {url}")

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=120) as response:  # noqa: S310 - local debug proxy
            return response.status, self._decode_response(response.read())

    def _post_multipart(
        self,
        url: str,
        body: bytes,
        content_type: str,
    ) -> tuple[int, object]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid backend URL: {url}")

        request = Request(
            url,
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=180) as response:  # noqa: S310 - local debug proxy
            return response.status, self._decode_response(response.read())

    def _decode_response(self, data: bytes) -> object:
        text = data.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _send_file(self, path: Path, content_type: str) -> None:
        data = path.read_bytes()
        self._send_headers(200, content_type, len(data))
        self.wfile.write(data)

    def _send_json(self, status_code: int, body: object) -> None:
        data = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self._send_headers(status_code, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _send_headers(self, status_code: int, content_type: str, content_length: int) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.end_headers()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DebugChatHandler)
    print(f"Debug chat: http://{HOST}:{PORT}")
    print(f"Backend default: {DEFAULT_BACKEND_URL}{DEFAULT_API_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping debug chat")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
