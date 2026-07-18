from app.agent_runtime.main import create_agent_runtime_app
from app.main import app as api_app


def test_runtime_exposes_health_and_both_websocket_aliases():
    runtime = create_agent_runtime_app()
    paths = [getattr(route, "path", None) for route in runtime.routes]
    assert "/health" in paths
    assert "/api/v1/voice/stream" in paths
    assert "/api/voice/stream" in paths


def test_main_api_has_no_websocket_routes_or_runtime_executor():
    assert all(getattr(route, "path", None) != "/api/v1/voice/stream" for route in api_app.routes)
    assert not hasattr(api_app.state, "voice_processing_executor")
