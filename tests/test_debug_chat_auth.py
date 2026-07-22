import importlib.util
from pathlib import Path


def load_server():
    path = Path(__file__).parents[1] / "debug-chat" / "server.py"
    spec = importlib.util.spec_from_file_location("debug_chat_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_debug_chat_proxy_keeps_development_auth_server_side(monkeypatch):
    server = load_server()
    captured = {}

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"runtime":"livekit"}'

    def urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(server, "urlopen", urlopen)
    handler = object.__new__(server.DebugChatHandler)
    status, _ = handler._post_json(
        "http://api/livekit/sessions", {"tenant_id": "demo_restaurant"}
    )
    assert status == 201
    assert captured["headers"]["X-livekit-debug-auth"] == "debug-chat"
