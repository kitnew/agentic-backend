import importlib.util
import io
import json
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "debug_chat_server", Path(__file__).parents[1] / "debug-chat" / "server.py"
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_livekit_session_proxy_forwards_only_server_safe_context():
    handler = object.__new__(server.DebugChatHandler)
    handler._read_json = lambda: {
        "tenant_id": " tenant-1 ",
        "conversation_id": "conversation-1",
        "system_prompt": "ignored",
    }
    forwarded = []
    handler._post_json = lambda url, payload: (201, forwarded.append((url, payload)) or {})
    handler._send_json = lambda status, response: None

    handler._handle_livekit_session()

    assert forwarded == [
        (
            "http://127.0.0.1:8000/api/v1/voice/livekit/sessions",
            {"tenant_id": "tenant-1", "conversation_id": "conversation-1"},
        )
    ]


def test_livekit_session_proxy_forwards_typed_turn_debug_fields():
    handler = object.__new__(server.DebugChatHandler)
    handler._read_json = lambda: {
        "tenant_id": "tenant-1",
        "turn_overrides": {"endpointing": {"min_delay_ms": 300}},
        "model": "ignored",
    }
    forwarded = []
    handler._post_json = lambda url, payload: (201, forwarded.append(payload) or {})
    handler._send_json = lambda status, response: None

    handler._handle_livekit_session()

    assert forwarded == [{
        "tenant_id": "tenant-1",
        "turn_overrides": {"endpointing": {"min_delay_ms": 300}},
    }]


def test_staging_proxy_adds_credential_only_to_server_side_request(monkeypatch):
    credential = "staging-access-secret-32-bytes-long"
    monkeypatch.setattr(server, "APP_ENV", "staging")
    monkeypatch.setattr(server, "STAGING_CREDENTIAL", credential)
    captured = []

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b'{"participant_token":"short-lived-token"}'

    def fake_urlopen(request, timeout):
        captured.append((request, timeout))
        return Response()

    monkeypatch.setattr(server, "urlopen", fake_urlopen)
    handler = object.__new__(server.DebugChatHandler)
    status, response = handler._post_json(
        "http://backend/api/v1/voice/livekit/sessions",
        {"tenant_id": "tenant-1"},
    )

    request, timeout = captured[0]
    assert status == 201
    assert response == {"participant_token": "short-lived-token"}
    assert timeout == 120
    assert request.get_header("X-livekit-staging-auth") == credential
    assert credential not in request.data.decode()
    assert credential not in json.dumps(response)


def test_staging_proxy_rejects_disallowed_tenant_before_backend(monkeypatch):
    monkeypatch.setattr(server, "APP_ENV", "staging")
    monkeypatch.setattr(server, "STAGING_TENANT_IDS", ("tenant-1",))
    handler = object.__new__(server.DebugChatHandler)
    handler._read_json = lambda: {"tenant_id": "tenant-2"}
    handler._post_json = lambda *_: (_ for _ in ()).throw(
        AssertionError("backend must not be called")
    )
    responses = []
    handler._send_json = lambda status, response: responses.append((status, response))

    handler._handle_livekit_session()

    assert responses == [(403, {"error": "Tenant access is forbidden"})]


def test_staging_page_exposes_only_allowlisted_tenants_and_no_credential(monkeypatch):
    credential = "staging-access-secret-32-bytes-long"
    monkeypatch.setattr(server, "APP_ENV", "staging")
    monkeypatch.setattr(server, "STAGING_CREDENTIAL", credential)
    monkeypatch.setattr(server, "STAGING_TENANT_IDS", ("tenant-1",))
    handler = object.__new__(server.DebugChatHandler)
    handler.wfile = io.BytesIO()
    handler._send_headers = lambda *_: None

    handler._send_file(
        Path(__file__).parents[1] / "debug-chat" / "index.html",
        "text/html; charset=utf-8",
    )

    page = handler.wfile.getvalue().decode()
    assert '<option value="tenant-1">tenant-1</option>' in page
    assert "penzion_grand" not in page
    assert "demo_restaurant" not in page
    assert credential not in page
    assert "LIVEKIT_STAGING_AUTH_CREDENTIAL" not in page


def test_debug_page_uses_grouped_millisecond_controls_without_raw_json():
    page = (Path(__file__).parents[1] / "debug-chat" / "index.html").read_text()
    assert all(group in page for group in (
        "Speech detection", "Turn completion", "Interruptions", "STT segmentation",
        "Preemptive LLM generation",
    ))
    assert page.count("data-turn=") == 17
    assert "Advanced overrides (JSON)" not in page
    assert "Use recommended defaults" in page and "Reset changes" in page


def test_debug_page_is_livekit_voice_only():
    page = (Path(__file__).parents[1] / "debug-chat" / "index.html").read_text()
    assert "LiveKitDebug.LiveKitController" in page
    assert all(value not in page for value in (
        'id="backendUrl"', 'id="apiPath"', 'id="textModeButton"',
        'id="voiceRuntime"', "/debug/message", "/debug/voice-session",
    ))
    assert not (Path(__file__).parents[1] / "debug-chat" / "voice-protocol.js").exists()
