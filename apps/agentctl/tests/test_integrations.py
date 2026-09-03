from pathlib import Path
from uuid import UUID

import pytest
from agentctl.commands import integrations
from agentctl.settings import Settings


class Backend:
    def __enter__(self): return self
    def __exit__(self, *_): pass


class ControlPlane:
    def __init__(self): self.calls = []
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def managed(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "integration-connections":
            if method == "GET": return [{"id": "connection", "key": "http", "enabled": True, "generation": 2, "credential_ref": None}]
            return {"id": "connection"}
        return {"valid": True, "usable": True}


def setup(monkeypatch: pytest.MonkeyPatch) -> ControlPlane:
    cp = ControlPlane()
    monkeypatch.setattr(integrations, "_client", lambda _settings: Backend())
    monkeypatch.setattr(integrations, "_tenant", lambda _backend, _slug: type("Tenant", (), {"id": UUID(int=1)})())
    monkeypatch.setattr(integrations, "ControlPlaneClient", lambda _settings: cp)
    return cp


def test_http_integration_validate_uses_cp(monkeypatch: pytest.MonkeyPatch):
    cp = setup(monkeypatch)
    integrations.run_integration(Settings("https://backend", "token", Path("definitions")), "validate", "hotel", "http")
    assert cp.calls[-1][1] == "integration-connections/connection/validate"


def test_google_sheets_is_rejected(monkeypatch: pytest.MonkeyPatch):
    with pytest.raises(Exception, match="HTTP"):
        integrations.run_integration(Settings("https://backend", "token", Path("definitions")), "list", "hotel", kind="google_sheets")
