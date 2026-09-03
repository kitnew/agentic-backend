from pathlib import Path
from uuid import UUID

from agentctl.commands import did
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
        if method == "GET": return [{"id": "old", "enabled": True, "generation": 3}]
        return {"id": "new"}


def test_did_reassigns_without_delete_or_publish(monkeypatch):
    cp = ControlPlane()
    monkeypatch.setattr(did, "_client", lambda _settings: Backend())
    monkeypatch.setattr(did, "_tenant", lambda _backend, _slug: type("Tenant", (), {"id": UUID(int=1)})())
    monkeypatch.setattr(did, "ControlPlaneClient", lambda _settings: cp)
    did.run_did(Settings("https://backend", "token", Path("definitions")), "assign", "hotel", "+421900000001")
    assert cp.calls == [("GET", "phone-number-assignments", {"params": {"tenant_id": str(UUID(int=1))}}), ("POST", "phone-number-assignments/old/disable", {"json": {"expected_generation": 3}}), ("POST", "phone-number-assignments", {"json": {"tenant_id": str(UUID(int=1)), "phone_number": "+421900000001", "enabled": True}})]


def test_did_remove_disables_current_assignment(monkeypatch):
    cp = ControlPlane()
    monkeypatch.setattr(did, "_client", lambda _settings: Backend())
    monkeypatch.setattr(did, "_tenant", lambda _backend, _slug: type("Tenant", (), {"id": UUID(int=1)})())
    monkeypatch.setattr(did, "ControlPlaneClient", lambda _settings: cp)
    did.run_did(Settings("https://backend", "token", Path("definitions")), "remove", "hotel")
    assert cp.calls[-1][1] == "phone-number-assignments/old/disable"
