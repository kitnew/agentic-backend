import subprocess
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from admin_client.generated.models.tenant_response import TenantResponse
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
        state_dir=Path("definitions"),
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
            state_dir=Path("definitions"),
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


def test_tenant_create_uses_existing_admin_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, object] = {}
    tenant = TenantResponse.from_dict(
        {
            "active_config_revision_id": None,
            "active_prompt_set_revision_id": None,
            "business_type": "hotel",
            "created_at": "2026-08-13T12:00:00+00:00",
            "display_name": "Debug Hotel",
            "id": "00000000-0000-0000-0000-000000000001",
            "slug": "debug-hotel",
            "status": "active",
            "updated_at": "2026-08-13T12:00:00+00:00",
        }
    )

    def generated_call(*, client: object, body: object) -> object:
        seen["body"] = body
        return SimpleNamespace(
            status_code=HTTPStatus.CREATED,
            parsed=tenant,
            content=b"",
        )

    monkeypatch.setattr(
        tenants.create_tenant_admin_v1_tenants_post,
        "sync_detailed",
        generated_call,
    )
    tenants.run_tenant_create(
        Settings("https://backend.example", "secret", Path("definitions")),
        "debug-hotel",
        "Debug Hotel",
        "hotel",
        "active",
    )

    assert seen["body"].to_dict() == {
        "business_type": "hotel",
        "display_name": "Debug Hotel",
        "slug": "debug-hotel",
        "status": "active",
    }
    assert "Created tenant:" in capsys.readouterr().out


def test_tenant_create_dispatches_from_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}

    def run(
        settings: Settings,
        slug: str,
        display_name: str,
        business_type: str,
        status: str,
    ) -> None:
        seen.update(
            settings=settings,
            slug=slug,
            display_name=display_name,
            business_type=business_type,
            status=status,
        )

    monkeypatch.setattr(cli, "run_tenant_create", run)
    assert (
        cli.main(
            [
                "tenant",
                "create",
                "debug-hotel",
                "--display-name",
                "Debug Hotel",
                "--business-type",
                "hotel",
            ]
        )
        == 0
    )
    assert seen["slug"] == "debug-hotel"
    assert seen["status"] == "active"


def test_tenant_create_reports_slug_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tenants.create_tenant_admin_v1_tenants_post,
        "sync_detailed",
        lambda **_: SimpleNamespace(
            status_code=HTTPStatus.CONFLICT,
            parsed=None,
            content=b'{"detail":"tenant slug already exists"}',
        ),
    )
    with pytest.raises(PromptCommandError, match="tenant slug already exists"):
        tenants.run_tenant_create(
            Settings("https://backend.example", "secret", Path("definitions")),
            "debug-hotel",
            "Debug Hotel",
            "hotel",
            "active",
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


def test_tenant_knowledge_command_hierarchy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}

    def run(settings: Settings, action: str, slug: str, *, force: bool = False) -> None:
        seen.update(settings=settings, action=action, slug=slug, force=force)

    monkeypatch.setattr(cli, "run_tenant_knowledge", run)
    assert (
        cli.main(
            [
                "--state-dir",
                str(tmp_path),
                "tenant",
                "knowledge",
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


def test_integration_command_hierarchy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_integration",
        lambda settings, action, slug, key=None, **options: seen.update(
            action=action, slug=slug, key=key, **options
        ),
    )

    assert (
        cli.main(
            [
                "integration",
                "create",
                "penzion-grand",
                "recording_webhook",
                "--provider",
                "managed_webhook",
                "--config-json",
                '{"allowed_hosts":["example.test"]}',
            ]
        )
        == 0
    )
    assert seen == {
        "action": "create",
        "slug": "penzion-grand",
        "key": "recording_webhook",
        "provider": "managed_webhook",
        "config_json": '{"allowed_hosts":["example.test"]}',
    }


@pytest.mark.parametrize(("action", "number"), [("show", None), ("set-number", "+421552301410")])
def test_telephony_command_hierarchy(
    monkeypatch: pytest.MonkeyPatch, action: str, number: str | None
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        cli,
        "run_tenant_telephony",
        lambda settings, selected, slug, **kwargs: seen.update(
            action=selected, slug=slug, number=kwargs.get("number")
        ),
    )
    arguments = ["tenant", "telephony", action, "penzion-grand"]
    if number is not None:
        arguments.append(number)
    assert cli.main(arguments) == 0
    assert seen == {"action": action, "slug": "penzion-grand", "number": number}


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
        lambda settings, selected, slug: seen.update(action=selected, slug=slug),
    )

    assert cli.main(["tenant", "prompt-set", action, "penzion-grand"]) == 0
    assert seen == {"action": action, "slug": "penzion-grand"}


def test_runtime_command_hierarchies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    seen: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(
        cli,
        "run_platform_runtime",
        lambda settings, action, force=False: seen.append(("platform", action, None)),
    )
    monkeypatch.setattr(
        cli,
        "run_tenant_runtime",
        lambda settings, action, slug, force=False: seen.append(
            ("tenant", action, slug)
        ),
    )
    monkeypatch.setattr(
        cli,
        "run_tenant_voice_runtime",
        lambda settings, action, slug: seen.append(("voice", action, slug)),
    )

    assert cli.main(["runtime", "plan"]) == 0
    assert cli.main(["tenant", "runtime", "push", "penzion-grand"]) == 0
    assert cli.main(["tenant", "voice-runtime", "apply", "penzion-grand"]) == 0
    assert seen == [
        ("platform", "plan", None),
        ("tenant", "push", "penzion-grand"),
        ("voice", "apply", "penzion-grand"),
    ]


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
