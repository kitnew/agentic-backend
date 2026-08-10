import subprocess
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from control_plane import main as cli
from control_plane.commands import tenants
from control_plane.commands.prompts import PromptCommandError
from control_plane.settings import Settings, SettingsError


@pytest.mark.parametrize("argument", ["--help", "--version"])
def test_agentctl_metadata_commands(argument: str) -> None:
    result = subprocess.run(
        ["agentctl", argument],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "agentctl" in result.stdout


def test_settings_validate_required_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENTCTL_API_URL", raising=False)
    monkeypatch.delenv("AGENTCTL_TOKEN", raising=False)
    with pytest.raises(SettingsError, match="AGENTCTL_API_URL"):
        Settings.load()

    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    with pytest.raises(SettingsError, match=r"HTTP\(S\) origin"):
        Settings.load("file:///tmp/backend")


def test_api_url_override_and_token_are_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://ignored.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    settings = Settings.load("https://backend.example/")
    assert settings == Settings(
        api_url="https://backend.example",
        token="secret",
        state_dir=Path("control-plane"),
    )


def test_cli_state_dir_overrides_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    monkeypatch.setenv("AGENTCTL_STATE_DIR", str(tmp_path / "environment"))
    seen: dict[str, Any] = {}

    def run(settings: Settings, action: str, *, force: bool = False) -> None:
        seen.update(settings=settings, action=action, force=force)

    monkeypatch.setattr(cli, "run_system_prompt", run)
    explicit = tmp_path / "explicit"
    assert (
        cli.main(
            [
                "--state-dir",
                str(explicit),
                "system-prompt",
                "plan",
            ]
        )
        == 0
    )
    assert seen["settings"].state_dir == explicit


def test_prompt_concurrency_error_is_clean_at_cli_boundary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    monkeypatch.setattr(
        cli,
        "run_system_prompt",
        lambda settings, action, force=False: (_ for _ in ()).throw(
            PromptCommandError("remote draft changed; run plan and retry")
        ),
    )
    assert cli.main(["system-prompt", "push"]) == 5
    error = capsys.readouterr().err
    assert "run plan and retry" in error
    assert "Traceback" not in error


def test_tenant_command_uses_generated_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def generated_call(*, client: object) -> object:
        seen["client"] = client
        return SimpleNamespace(status_code=HTTPStatus.OK, parsed=[], content=b"")

    monkeypatch.setattr(
        tenants.list_tenants_admin_v1_tenants_get,
        "sync_detailed",
        generated_call,
    )
    response = tenants.fetch_tenants(
        Settings(
            api_url="https://backend.example",
            token="secret",
            state_dir=Path("control-plane"),
        )
    )
    assert response.status_code is HTTPStatus.OK
    assert seen["client"].get_httpx_client().headers["Authorization"] == "Bearer secret"


def test_tenant_list_renders_human_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    tenant = SimpleNamespace(
        slug="penzion-grand",
        id="00000000-0000-0000-0000-000000000001",
        status=SimpleNamespace(value="active"),
    )
    monkeypatch.setattr(
        cli,
        "fetch_tenants",
        lambda settings: SimpleNamespace(
            status_code=HTTPStatus.OK,
            parsed=[tenant],
            content=b"",
        ),
    )

    assert cli.main(["tenant", "list"]) == 0
    assert capsys.readouterr().out == (
        "penzion-grand\t00000000-0000-0000-0000-000000000001\tactive\n"
    )


def test_tenant_prompt_command_hierarchy_and_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}

    def run(
        settings: Settings,
        action: str,
        slug: str,
        *,
        force: bool = False,
    ) -> None:
        seen.update(settings=settings, action=action, slug=slug, force=force)

    monkeypatch.setattr(cli, "run_tenant_prompt", run)
    assert (
        cli.main(
            [
                "--state-dir",
                str(tmp_path),
                "tenant",
                "prompt",
                "pull",
                "penzion-grand",
                "--force",
            ]
        )
        == 0
    )
    assert seen == {
        "settings": Settings("https://backend.example", "secret", tmp_path),
        "action": "pull",
        "slug": "penzion-grand",
        "force": True,
    }


def test_tenant_config_command_hierarchy_and_state_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}

    def run(
        settings: Settings,
        action: str,
        slug: str,
        *,
        force: bool = False,
    ) -> None:
        seen.update(settings=settings, action=action, slug=slug, force=force)

    monkeypatch.setattr(cli, "run_tenant_config", run)
    assert (
        cli.main(
            [
                "--state-dir",
                str(tmp_path),
                "tenant",
                "config",
                "pull",
                "penzion-grand",
                "--force",
            ]
        )
        == 0
    )
    assert seen == {
        "settings": Settings("https://backend.example", "secret", tmp_path),
        "action": "pull",
        "slug": "penzion-grand",
        "force": True,
    }


@pytest.mark.parametrize("action", ["show", "revisions", "plan", "apply"])
def test_tenant_prompt_set_command_hierarchy(
    monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_tenant_prompt_set",
        lambda settings, selected, slug: seen.update(
            action=selected, slug=slug
        ),
    )

    assert cli.main(["tenant", "prompt-set", action, "penzion-grand"]) == 0
    assert seen == {"action": action, "slug": "penzion-grand"}


@pytest.mark.parametrize(
    ("failure", "code", "message"),
    [
        (httpx.ConnectError("unavailable"), 3, "connection failed"),
        (RuntimeError("broken"), 1, "unexpected client failure"),
    ],
)
def test_client_failures_are_clean(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
    code: int,
    message: str,
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")

    def fail(_: Settings) -> object:
        raise failure

    monkeypatch.setattr(cli, "fetch_tenants", fail)
    assert cli.main(["tenant", "list"]) == code
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("status", "code", "message"),
    [
        (HTTPStatus.UNAUTHORIZED, 4, "authentication/authorization failed"),
        (HTTPStatus.FORBIDDEN, 4, "authentication/authorization failed"),
        (HTTPStatus.UNPROCESSABLE_ENTITY, 5, "invalid request"),
    ],
)
def test_api_failures_are_clean(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: HTTPStatus,
    code: int,
    message: str,
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    content = b'{"detail":"invalid request"}'
    monkeypatch.setattr(
        cli,
        "fetch_tenants",
        lambda settings: SimpleNamespace(
            status_code=status,
            parsed=None,
            content=content,
        ),
    )

    assert cli.main(["tenant", "list"]) == code
    assert message in capsys.readouterr().err


def test_missing_configuration_is_clean(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("AGENTCTL_API_URL", raising=False)
    monkeypatch.delenv("AGENTCTL_TOKEN", raising=False)
    assert cli.main(["tenant", "list"]) == 2
    error = capsys.readouterr().err
    assert "configuration error" in error
    assert "Traceback" not in error
