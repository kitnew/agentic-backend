from pathlib import Path

import pytest
from control_plane import main as cli
from control_plane.settings import Settings, SettingsError


def test_settings_validate_required_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTCTL_API_URL", raising=False)
    monkeypatch.delenv("AGENTCTL_TOKEN", raising=False)
    with pytest.raises(SettingsError, match="AGENTCTL_API_URL"):
        Settings.load()


def test_tenant_config_dispatches_component_authoring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_tenant_components",
        lambda settings, action, slug: seen.update(settings=settings, action=action, slug=slug),
    )
    assert cli.main(["--state-dir", str(tmp_path), "tenant", "config", "push", "demo"]) == 0
    assert seen["action"] == "push"
    assert seen["slug"] == "demo"


def test_sync_dispatches_component_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_sync",
        lambda settings, action, **kwargs: seen.update(action=action),
    )
    assert cli.main(["sync", "plan"]) == 0
    assert seen["action"] == "plan"
