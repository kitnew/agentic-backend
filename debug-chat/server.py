#!/usr/bin/env python3
"""Tiny stdlib server for the LiveKit voice debug console."""

from __future__ import annotations

import html
import json
import logging
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
APP_ENV = os.getenv("APP_ENV", "development").lower()
STAGING_CREDENTIAL = os.getenv("LIVEKIT_STAGING_AUTH_CREDENTIAL", "")
STAGING_TENANT_IDS = tuple(
    tenant.strip()
    for tenant in os.getenv("LIVEKIT_STAGING_ALLOWED_TENANTS", "").split(",")
    if tenant.strip()
)
logger = logging.getLogger(__name__)


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
        tenant_id = "unknown"
        try:
            body = self._read_json()
            tenant_id = body.get("tenant_id")
            conversation_id = body.get("conversation_id")
            turn_overrides = body.get("turn_overrides")
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                raise ValueError("tenant_id must be a non-empty string")
            tenant_id = tenant_id.strip()
            if APP_ENV == "staging" and tenant_id not in STAGING_TENANT_IDS:
                logger.warning(
                    "Staging session proxy environment=staging tenant=%s outcome=forbidden",
                    tenant_id,
                )
                self._send_json(403, {"error": "Tenant access is forbidden"})
                return
            if conversation_id is not None and not isinstance(conversation_id, str):
                raise ValueError("conversation_id must be a string")
            payload = {"tenant_id": tenant_id}
            if conversation_id:
                payload["conversation_id"] = conversation_id
            if turn_overrides:
                payload["turn_overrides"] = turn_overrides
            status, response = self._post_json(
                f"{BACKEND_URL}/api/v1/voice/livekit/sessions", payload
            )
            if APP_ENV == "staging":
                logger.info(
                    "Staging session proxy environment=staging tenant=%s outcome=%s",
                    tenant_id,
                    "forwarded" if status < 400 else "rejected",
                )
            self._send_json(status, response)
        except ValueError as exc:
            if APP_ENV == "staging":
                logger.warning(
                    "Staging session proxy environment=staging tenant=%s outcome=invalid",
                    tenant_id,
                )
            self._send_json(400, {"error": str(exc)})
        except HTTPError as exc:
            if APP_ENV == "staging":
                logger.warning(
                    "Staging session proxy environment=staging tenant=%s outcome=rejected status=%s",
                    tenant_id,
                    exc.code,
                )
            self._send_json(exc.code, self._decode_response(exc.read()))
        except URLError as exc:
            if APP_ENV == "staging":
                logger.error(
                    "Staging session proxy environment=staging tenant=%s outcome=backend-unavailable",
                    tenant_id,
                )
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
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if APP_ENV == "staging":
            if STAGING_CREDENTIAL:
                headers["X-LiveKit-Staging-Auth"] = STAGING_CREDENTIAL
        else:
            headers["X-LiveKit-Debug-Auth"] = "debug-chat"
        request = Request(
            url,
            data=json.dumps(payload).encode(),
            headers=headers,
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
        if APP_ENV == "staging" and path.name == "index.html":
            options = "".join(
                f'<option value="{html.escape(tenant)}">{html.escape(tenant)}</option>'
                for tenant in STAGING_TENANT_IDS
            )
            start = b'<select id="tenant">'
            before, separator, rest = data.partition(start)
            if separator:
                _, end, after = rest.partition(b"</select>")
                if end:
                    data = before + start + options.encode() + end + after
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
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
