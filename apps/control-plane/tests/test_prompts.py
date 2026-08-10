from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.platform_prompt_revision_response import (
    PlatformPromptRevisionResponse,
)
from admin_client.generated.models.prompt_text_revision_response import (
    PromptTextRevisionResponse,
)
from admin_client.generated.types import Response
from control_plane.commands import prompts
from control_plane.settings import Settings

NOW = datetime(2026, 8, 9, tzinfo=UTC)


def settings(path: Path) -> Settings:
    return Settings("https://backend.example", "secret", path)


def revision(
    number: int,
    status: str,
    text: str,
    *,
    version: int = 1,
) -> PromptTextRevisionResponse:
    return PromptTextRevisionResponse(
        created_at=NOW,
        id=UUID(int=number),
        published_at=NOW if status == "published" else None,
        revision_number=number,
        status=status,
        text=text,
        version=version,
    )


def platform_revision(
    number: int, status: str, text: str, *, version: int = 1
) -> PlatformPromptRevisionResponse:
    return PlatformPromptRevisionResponse(
        created_at=NOW,
        id=UUID(int=number),
        key=prompts.SYSTEM_PROMPT_KEY,
        prompt_id=UUID(int=100),
        published_at=NOW if status == "published" else None,
        revision_number=number,
        status=status,
        text=text,
        version=version,
    )


def response(
    parsed: object,
    status: HTTPStatus = HTTPStatus.OK,
    content: bytes = b"",
) -> Response[object]:
    return Response(
        status_code=status,
        content=content,
        headers=httpx.Headers(),
        parsed=parsed,
    )


def mock_system_revisions(
    monkeypatch: pytest.MonkeyPatch,
    revisions: list[PromptTextRevisionResponse],
) -> None:
    monkeypatch.setattr(
        prompts.list_system_prompt_revisions_admin_v1_platform_prompts_system_key_revisions_get,
        "sync_detailed",
        lambda key, *, client: response(revisions),
    )


def mock_profile(
    monkeypatch: pytest.MonkeyPatch,
    revisions: list[PromptTextRevisionResponse],
    *,
    keys: list[str] | None = None,
) -> None:
    monkeypatch.setattr(
        prompts.list_profiles_admin_v1_platform_prompts_profiles_get,
        "sync_detailed",
        lambda *, client: response(keys or ["hotel_assistant"]),
    )
    monkeypatch.setattr(
        prompts.list_profile_prompt_revisions_admin_v1_platform_prompts_profiles_key_revisions_get,
        "sync_detailed",
        lambda key, *, client: response(revisions),
    )


def test_canonical_path_resolution_and_state_dir_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENTCTL_API_URL", "https://backend.example")
    monkeypatch.setenv("AGENTCTL_TOKEN", "secret")
    monkeypatch.delenv("AGENTCTL_STATE_DIR", raising=False)
    assert Settings.load().state_dir == Path("control-plane")

    environment = tmp_path / "environment"
    monkeypatch.setenv("AGENTCTL_STATE_DIR", str(environment))
    assert Settings.load().state_dir == environment

    cli = tmp_path / "cli"
    loaded = Settings.load(state_dir=str(cli))
    assert loaded.state_dir == cli
    assert prompts.system_prompt_path(cli) == cli / "platform/system_prompt.md"
    assert prompts.profile_prompt_path(cli, "hotel_assistant") == (
        cli / "platform/profiles/hotel_assistant.md"
    )


def test_profile_key_cannot_escape_state_directory(tmp_path: Path) -> None:
    with pytest.raises(prompts.PromptCommandError, match="profile key"):
        prompts.profile_prompt_path(tmp_path, "../outside")


def test_system_show_and_revisions_use_generated_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_system_revisions(
        monkeypatch,
        [revision(1, "published", "old"), revision(2, "draft", "new", version=4)],
    )
    prompts.run_system_prompt(settings(tmp_path), "show")
    output = capsys.readouterr().out
    assert "published revision: 1" in output
    assert "draft version: 4" in output

    prompts.run_system_prompt(settings(tmp_path), "revisions")
    output = capsys.readouterr().out
    assert "REVISION\tSTATUS" in output
    assert "2\tdraft" in output


def test_pull_creates_file_and_unchanged_pull_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_system_revisions(monkeypatch, [revision(3, "published", "Canonical\n")])
    path = prompts.system_prompt_path(tmp_path)
    prompts.run_system_prompt(settings(tmp_path), "pull")
    assert path.read_bytes() == b"Canonical\n"
    assert "published revision 3" in capsys.readouterr().out

    path.write_bytes(b"Canonical")
    prompts.run_system_prompt(settings(tmp_path), "pull")
    assert path.read_bytes() == b"Canonical"
    assert "Already current" in capsys.readouterr().out


def test_pull_refuses_modified_file_and_force_overwrites(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_system_revisions(monkeypatch, [revision(1, "published", "remote")])
    path = prompts.system_prompt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("local", encoding="utf-8")

    with pytest.raises(prompts.PromptCommandError, match="--force"):
        prompts.run_system_prompt(settings(tmp_path), "pull")
    assert path.read_text(encoding="utf-8") == "local"

    prompts.run_system_prompt(settings(tmp_path), "pull", force=True)
    assert path.read_text(encoding="utf-8") == "remote"


@pytest.mark.parametrize(
    ("local", "remote", "expected"),
    [
        ("same\n", [revision(1, "published", "same")], "no changes"),
        ("changed", [revision(1, "published", "old")], "create draft revision"),
        (
            "changed",
            [revision(1, "published", "old"), revision(2, "draft", "other")],
            "update existing draft revision 2",
        ),
    ],
)
def test_system_plan_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    local: str,
    remote: list[PromptTextRevisionResponse],
    expected: str,
) -> None:
    path = prompts.system_prompt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(local, encoding="utf-8")
    mock_system_revisions(monkeypatch, remote)
    prompts.run_system_prompt(settings(tmp_path), "plan")
    assert expected in capsys.readouterr().out


def test_plan_reports_missing_local_and_missing_remote(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_system_revisions(monkeypatch, [revision(1, "published", "remote")])
    prompts.run_system_prompt(settings(tmp_path), "plan")
    assert "missing-local" in capsys.readouterr().out

    path = prompts.system_prompt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("local", encoding="utf-8")
    mock_system_revisions(monkeypatch, [])
    prompts.run_system_prompt(settings(tmp_path), "plan")
    assert "Status: local-only" in capsys.readouterr().out


def test_push_creates_draft_without_publishing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = prompts.system_prompt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("new", encoding="utf-8")
    mock_system_revisions(monkeypatch, [])
    seen: dict[str, Any] = {}

    def create(*, client: object, body: object) -> Response[object]:
        seen["body"] = body
        return response(platform_revision(1, "draft", "new"), HTTPStatus.CREATED)

    monkeypatch.setattr(
        prompts.create_system_prompt_draft_admin_v1_platform_prompts_system_drafts_post,
        "sync_detailed",
        create,
    )
    prompts.run_system_prompt(settings(tmp_path), "push")
    assert seen["body"].text == "new"


def test_push_updates_draft_with_current_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = prompts.system_prompt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("new", encoding="utf-8")
    mock_system_revisions(monkeypatch, [revision(2, "draft", "old", version=7)])
    seen: dict[str, Any] = {}

    def update(
        revision_id: UUID,
        *,
        client: object,
        body: object,
        if_match: str,
    ) -> Response[object]:
        seen.update(revision_id=revision_id, body=body, if_match=if_match)
        return response(revision(2, "draft", "new", version=8))

    monkeypatch.setattr(
        prompts.update_system_prompt_draft_admin_v1_platform_prompts_system_drafts_revision_id_patch,
        "sync_detailed",
        update,
    )
    prompts.run_system_prompt(settings(tmp_path), "push")
    assert seen["if_match"] == '"7"'
    assert seen["body"].text == "new"


def test_push_unchanged_skips_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = prompts.system_prompt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("same", encoding="utf-8")
    mock_system_revisions(monkeypatch, [revision(2, "draft", "same\n")])
    prompts.run_system_prompt(settings(tmp_path), "push")


def test_push_concurrency_conflict_is_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = prompts.system_prompt_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("new", encoding="utf-8")
    mock_system_revisions(monkeypatch, [revision(2, "draft", "old", version=7)])
    monkeypatch.setattr(
        prompts.update_system_prompt_draft_admin_v1_platform_prompts_system_drafts_revision_id_patch,
        "sync_detailed",
        lambda revision_id, *, client, body, if_match: response(
            None,
            HTTPStatus.PRECONDITION_FAILED,
            b'{"detail":"draft version does not match If-Match"}',
        ),
    )
    with pytest.raises(prompts.PromptCommandError, match="run plan and retry"):
        prompts.run_system_prompt(settings(tmp_path), "push")


def test_publish_uses_remote_draft_without_reading_local_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    draft = revision(2, "draft", "remote")
    mock_system_revisions(monkeypatch, [draft])
    monkeypatch.setattr(
        prompts.publish_system_prompt_draft_admin_v1_platform_prompts_system_drafts_revision_id_publish_post,
        "sync_detailed",
        lambda revision_id, *, client: response(revision(2, "published", "remote")),
    )
    prompts.run_system_prompt(settings(tmp_path), "publish")
    assert "Published System Prompt" in capsys.readouterr().out
    assert not prompts.system_prompt_path(tmp_path).exists()


def test_profile_list_show_revisions_and_unknown_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    remote = [revision(1, "published", "hotel")]
    mock_profile(monkeypatch, remote)
    prompts.run_profile(settings(tmp_path), "list")
    assert capsys.readouterr().out == "hotel_assistant\n"

    prompts.run_profile(settings(tmp_path), "show", "hotel_assistant")
    assert "Profile Prompt: hotel_assistant" in capsys.readouterr().out
    prompts.run_profile(settings(tmp_path), "revisions", "hotel_assistant")
    assert "1\tpublished" in capsys.readouterr().out

    mock_profile(monkeypatch, [], keys=["another_profile"])
    with pytest.raises(prompts.PromptCommandError, match="unknown profile"):
        prompts.run_profile(settings(tmp_path), "show", "hotel_assistant")


def test_profile_pull_plan_push_and_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    published = revision(1, "published", "hotel")
    mock_profile(monkeypatch, [published])
    prompts.run_profile(settings(tmp_path), "pull", "hotel_assistant")
    path = prompts.profile_prompt_path(tmp_path, "hotel_assistant")
    assert path.read_text(encoding="utf-8") == "hotel"

    path.write_text("updated", encoding="utf-8")
    prompts.run_profile(settings(tmp_path), "plan", "hotel_assistant")
    assert "create draft revision" in capsys.readouterr().out

    monkeypatch.setattr(
        prompts.create_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_post,
        "sync_detailed",
        lambda *, client, body: response(
            platform_revision(2, "draft", body.text), HTTPStatus.CREATED
        ),
    )
    prompts.run_profile(settings(tmp_path), "push", "hotel_assistant")

    draft = revision(2, "draft", "updated")
    mock_profile(monkeypatch, [published, draft])
    monkeypatch.setattr(
        prompts.publish_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_revision_id_publish_post,
        "sync_detailed",
        lambda revision_id, *, client: response(revision(2, "published", "updated")),
    )
    prompts.run_profile(settings(tmp_path), "publish", "hotel_assistant")
    assert "Published Profile Prompt" in capsys.readouterr().out


def test_profile_create_is_explicit_and_creates_only_a_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_profile(monkeypatch, [], keys=["legacy_default"])
    path = prompts.profile_prompt_path(tmp_path, "hotel_assistant")
    path.parent.mkdir(parents=True)
    path.write_text("hotel profile", encoding="utf-8")
    seen: dict[str, Any] = {}

    def create(*, client: object, body: object) -> Response[object]:
        seen["body"] = body
        return response(
            platform_revision(1, "draft", "hotel profile"), HTTPStatus.CREATED
        )

    monkeypatch.setattr(
        prompts.create_profile_prompt_draft_admin_v1_platform_prompts_profiles_drafts_post,
        "sync_detailed",
        create,
    )
    prompts.run_profile(settings(tmp_path), "create", "hotel_assistant")
    assert seen["body"].text == "hotel profile"
    assert "draft revision 1" in capsys.readouterr().out
