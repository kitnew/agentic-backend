#!/usr/bin/env python3
"""Tiny stdlib server for the LiveKit voice debug console."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
HOST = os.getenv("DEBUG_CHAT_HOST", "127.0.0.1")
PORT = int(os.getenv("DEBUG_CHAT_PORT", "8080"))


class DebugChatHandler(BaseHTTPRequestHandler):
    server_version = "VoiceDebug/1.0"

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/livekit-controller.js": (
                "livekit-controller.js",
                "text/javascript; charset=utf-8",
            ),
            "/vendor/livekit-client.umd.js": (
                "node_modules/livekit-client/dist/livekit-client.umd.js",
                "text/javascript; charset=utf-8",
            ),
        }
        if asset := files.get(self.path):
            self._send_file(ROOT / asset[0], asset[1])
            return
        self._send_json(404, {"error": "Not found"})

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib API
        content_types = {
            "/": "text/html; charset=utf-8",
            "/index.html": "text/html; charset=utf-8",
            "/livekit-controller.js": "text/javascript; charset=utf-8",
            "/vendor/livekit-client.umd.js": "text/javascript; charset=utf-8",
        }
        if content_type := content_types.get(self.path):
            self._send_headers(200, content_type, 0)
            return
        self._send_headers(404, "application/json; charset=utf-8", 0)

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        if urlparse(self.path).path != "/debug/livekit-session":
            self._send_json(404, {"error": "Not found"})
            return
        self._handle_livekit_session()

    def _handle_livekit_session(self) -> None:
        try:
            body = self._read_json()
            tenant_id = body.get("tenant_id")
            conversation_id = body.get("conversation_id")
            turn_overrides = body.get("turn_overrides")
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                raise ValueError("tenant_id must be a non-empty string")
            if conversation_id is not None and not isinstance(conversation_id, str):
                raise ValueError("conversation_id must be a string")
            payload = {"tenant_id": tenant_id.strip()}
            if conversation_id:
                payload["conversation_id"] = conversation_id
            if turn_overrides:
                payload["turn_overrides"] = turn_overrides
            status, response = self._post_json(
                f"{BACKEND_URL}/api/v1/voice/livekit/sessions", payload
            )
            self._send_json(status, response)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except HTTPError as exc:
            self._send_json(exc.code, self._decode_response(exc.read()))
        except URLError as exc:
            self._send_json(502, {"error": f"Backend request failed: {exc.reason}"})

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Request body is empty")
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        return body

    def _post_json(self, url: str, payload: dict) -> tuple[int, object]:
        request = Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=120) as response:  # noqa: S310 - local proxy
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
        data = json.dumps(body, ensure_ascii=False, indent=2).encode()
        self._send_headers(status_code, "application/json; charset=utf-8", len(data))
        self.wfile.write(data)

    def _send_headers(self, status_code: int, content_type: str, length: int) -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.end_headers()


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DebugChatHandler)
    print(f"Voice debug console: http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
