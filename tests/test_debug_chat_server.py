import importlib.util
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
