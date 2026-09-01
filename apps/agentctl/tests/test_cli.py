from pathlib import Path

import pytest
from agentctl import main as cli
from agentctl.settings import Settings, SettingsError


def test_settings_validate_required_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTCTL_API_URL", raising=False)
    monkeypatch.delenv("AGENTCTL_TOKEN", raising=False)
    with pytest.raises(SettingsError, match="AGENTCTL_API_URL"):
        Settings.load()


def test_workspace_commands_dispatch_tenant_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_workspace",
        lambda settings, action, selection: seen.update(action=action, selection=selection),
    )
    assert cli.main(["--state-dir", str(tmp_path), "push", "tenant", "demo"]) == 0
    assert seen["action"] == "push"
    assert seen["selection"].scope == "tenant"
    assert seen["selection"].tenant_slug == "demo"


def test_workspace_commands_dispatch_platform_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_workspace",
        lambda settings, action, selection: seen.update(action=action, selection=selection),
    )
    assert cli.main(["--state-dir", str(tmp_path), "status", "platform"]) == 0
    assert seen["action"] == "status"
    assert seen["selection"].scope == "platform"


@pytest.mark.parametrize("action", ("status", "pull", "plan", "push", "publish"))
def test_workspace_commands_default_to_all_scopes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_workspace",
        lambda settings, verb, selection: seen.update(action=verb, selection=selection),
    )
    assert cli.main(["--state-dir", str(tmp_path), action]) == 0
    assert seen["action"] == action
    assert seen["selection"].scope == "all"


def test_removed_duplicate_mutation_commands_are_not_registered() -> None:
    help_text = cli.parser().format_help()
    assert "sync" not in help_text
    assert "config" not in cli.parser()._subparsers._group_actions[0].choices["tenant"].format_help()
    assert "system-prompt" in help_text
