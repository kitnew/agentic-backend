import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "debug_chat_server", Path(__file__).parents[1] / "debug-chat" / "server.py"
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_voice_session_proxy_forwards_call_mode():
    handler = object.__new__(server.DebugChatHandler)
    handler._read_json = lambda: {"tenant_id": " tenant-1 ", "mode": "call"}
    forwarded = []
    handler._post_json = lambda url, payload: (201, forwarded.append(payload) or {})
    handler._send_json = lambda status, response: None

    handler._handle_voice_session()

    assert forwarded == [{"tenant_id": "tenant-1", "mode": "call"}]
