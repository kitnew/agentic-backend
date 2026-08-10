from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.tenant_prompt_revision_response import (
    TenantPromptRevisionResponse,
)
from admin_client.generated.models.tenant_response import TenantResponse
from admin_client.generated.models.tenant_status import TenantStatus
from admin_client.generated.types import Response
from control_plane.commands import prompts
from control_plane.settings import Settings

NOW = datetime(2026, 8, 9, tzinfo=UTC)
TENANT_ID = UUID("00000000-0000-0000-0000-000000000010")
SLUG = "penzion-grand"


def settings(path: Path) -> Settings:
    return Settings("https://backend.example", "secret", path)


def tenant() -> TenantResponse:
    return TenantResponse(
        active_config_revision_id=None,
        active_prompt_set_revision_id=None,
        business_type="hotel",
        created_at=NOW,
        display_name="Penzion Grand",
        id=TENANT_ID,
        slug=SLUG,
        status=TenantStatus.ACTIVE,
        updated_at=NOW,
    )


def revision(
    number: int,
    status: str,
    text: str,
    *,
    version: int = 1,
) -> TenantPromptRevisionResponse:
    return TenantPromptRevisionResponse(
        created_at=NOW,
        id=UUID(int=number),
        prompt_id=UUID(int=100),
        published_at=NOW if status == "published" else None,
        revision_number=number,
        status=status,
        tenant_id=TENANT_ID,
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


def mock_remote(
    monkeypatch: pytest.MonkeyPatch,
    revisions: list[TenantPromptRevisionResponse],
) -> None:
    monkeypatch.setattr(
        prompts.get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
        "sync_detailed",
        lambda slug, *, client: response(tenant()),
    )
    monkeypatch.setattr(
        prompts.list_tenant_prompt_revisions_admin_v1_tenants_tenant_id_tenant_prompt_revisions_get,
        "sync_detailed",
        lambda tenant_id, *, client: response(revisions),
    )


def test_tenant_prompt_path_and_slug_safety(tmp_path: Path) -> None:
    assert prompts.tenant_prompt_path(tmp_path, SLUG) == (
        tmp_path / "tenants" / SLUG / "tenant_prompt.md"
    )
    for slug in ("../escape", "/absolute", "tenant/name", "UPPER", "a--b"):
        with pytest.raises(prompts.PromptCommandError, match="tenant slug"):
            prompts.tenant_prompt_path(tmp_path, slug)


def test_unknown_tenant_is_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        prompts.get_tenant_by_slug_admin_v1_tenants_by_slug_slug_get,
        "sync_detailed",
        lambda slug, *, client: response(
            None, HTTPStatus.NOT_FOUND, b'{"detail":"tenant not found"}'
        ),
    )
    with pytest.raises(prompts.PromptCommandError, match=f"unknown tenant: {SLUG}"):
        prompts.run_tenant_prompt(settings(tmp_path), "show", SLUG)


def test_show_and_revisions_use_remote_state_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local = prompts.tenant_prompt_path(tmp_path, SLUG)
    local.parent.mkdir(parents=True)
    local.write_bytes(b"\xff")
    mock_remote(
        monkeypatch,
        [revision(4, "published", "old"), revision(5, "draft", "new", version=2)],
    )

    prompts.run_tenant_prompt(settings(tmp_path), "show", SLUG)
    output = capsys.readouterr().out
    assert f"Tenant Prompt: {SLUG}" in output
    assert "published revision: 4" in output
    assert "draft version: 2" in output

    prompts.run_tenant_prompt(settings(tmp_path), "revisions", SLUG)
    assert "5\tdraft" in capsys.readouterr().out


def test_pull_create_noop_refuse_and_force(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_remote(monkeypatch, [revision(4, "published", "remote\n")])
    path = prompts.tenant_prompt_path(tmp_path, SLUG)

    prompts.run_tenant_prompt(settings(tmp_path), "pull", SLUG)
    assert path.read_bytes() == b"remote\n"
    assert "published revision 4" in capsys.readouterr().out

    path.write_bytes(b"remote")
    prompts.run_tenant_prompt(settings(tmp_path), "pull", SLUG)
    assert "Already current" in capsys.readouterr().out

    path.write_text("local", encoding="utf-8")
    with pytest.raises(prompts.PromptCommandError, match="--force"):
        prompts.run_tenant_prompt(settings(tmp_path), "pull", SLUG)
    assert path.read_text(encoding="utf-8") == "local"

    prompts.run_tenant_prompt(settings(tmp_path), "pull", SLUG, force=True)
    assert path.read_bytes() == b"remote\n"


def test_plan_is_read_only_and_uses_remote_draft(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = prompts.tenant_prompt_path(tmp_path, SLUG)
    path.parent.mkdir(parents=True)
    path.write_text("local", encoding="utf-8")
    mock_remote(monkeypatch, [])
    prompts.run_tenant_prompt(settings(tmp_path), "plan", SLUG)
    output = capsys.readouterr().out
    assert "Status: local-only" in output
    assert "create draft revision" in output
    assert "status: missing-remote" not in output

    mock_remote(
        monkeypatch,
        [revision(1, "published", "local"), revision(2, "draft", "remote draft")],
    )
    prompts.run_tenant_prompt(settings(tmp_path), "plan", SLUG)
    output = capsys.readouterr().out
    assert "Status: draft-conflict" in output
    assert "update existing draft revision 2" in output


def test_plan_missing_local_and_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_remote(monkeypatch, [revision(1, "published", "same")])
    prompts.run_tenant_prompt(settings(tmp_path), "plan", SLUG)
    assert "Status: missing-local" in capsys.readouterr().out

    path = prompts.tenant_prompt_path(tmp_path, SLUG)
    path.parent.mkdir(parents=True)
    path.write_text("same\n", encoding="utf-8")
    prompts.run_tenant_prompt(settings(tmp_path), "plan", SLUG)
    assert "no changes" in capsys.readouterr().out


def test_first_push_creates_draft_and_never_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = prompts.tenant_prompt_path(tmp_path, SLUG)
    path.parent.mkdir(parents=True)
    path.write_text("new", encoding="utf-8")
    mock_remote(monkeypatch, [])
    seen: dict[str, Any] = {}

    def create(tenant_id: UUID, *, client: object, body: object) -> Response[object]:
        seen.update(tenant_id=tenant_id, body=body)
        return response(revision(1, "draft", "new"), HTTPStatus.CREATED)

    monkeypatch.setattr(
        prompts.create_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_post,
        "sync_detailed",
        create,
    )
    monkeypatch.setattr(
        prompts.publish_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_publish_post,
        "sync_detailed",
        lambda *args, **kwargs: pytest.fail("push must not publish"),
    )
    prompts.run_tenant_prompt(settings(tmp_path), "push", SLUG)
    assert seen["tenant_id"] == TENANT_ID
    assert seen["body"].text == "new"


def test_changed_push_updates_draft_with_etag_and_unchanged_is_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = prompts.tenant_prompt_path(tmp_path, SLUG)
    path.parent.mkdir(parents=True)
    path.write_text("new", encoding="utf-8")
    mock_remote(monkeypatch, [revision(2, "draft", "old", version=7)])
    seen: dict[str, Any] = {}

    def update(
        tenant_id: UUID,
        revision_id: UUID,
        *,
        client: object,
        body: object,
        if_match: str,
    ) -> Response[object]:
        seen.update(
            tenant_id=tenant_id,
            revision_id=revision_id,
            body=body,
            if_match=if_match,
        )
        return response(revision(2, "draft", "new", version=8))

    monkeypatch.setattr(
        prompts.update_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_patch,
        "sync_detailed",
        update,
    )
    prompts.run_tenant_prompt(settings(tmp_path), "push", SLUG)
    assert seen["if_match"] == '"7"'
    assert seen["body"].text == "new"

    mock_remote(monkeypatch, [revision(2, "draft", "new\n", version=8)])
    monkeypatch.setattr(
        prompts.update_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_patch,
        "sync_detailed",
        lambda *args, **kwargs: pytest.fail("unchanged push must not mutate"),
    )
    prompts.run_tenant_prompt(settings(tmp_path), "push", SLUG)


@pytest.mark.parametrize(
    "status", [HTTPStatus.PRECONDITION_FAILED, HTTPStatus.CONFLICT]
)
def test_push_concurrency_conflict_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: HTTPStatus,
) -> None:
    path = prompts.tenant_prompt_path(tmp_path, SLUG)
    path.parent.mkdir(parents=True)
    path.write_text("new", encoding="utf-8")
    mock_remote(monkeypatch, [revision(2, "draft", "old", version=7)])
    monkeypatch.setattr(
        prompts.update_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_patch,
        "sync_detailed",
        lambda *args, **kwargs: response(None, status, b'{"detail":"conflict"}'),
    )
    with pytest.raises(prompts.PromptCommandError, match="run plan and retry"):
        prompts.run_tenant_prompt(settings(tmp_path), "push", SLUG)


def test_publish_uses_remote_draft_without_file_or_prompt_set_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_remote(monkeypatch, [revision(5, "draft", "remote")])
    seen: dict[str, UUID] = {}

    def publish(
        tenant_id: UUID, revision_id: UUID, *, client: object
    ) -> Response[object]:
        seen.update(tenant_id=tenant_id, revision_id=revision_id)
        return response(revision(5, "published", "remote"))

    monkeypatch.setattr(
        prompts.publish_tenant_prompt_draft_admin_v1_tenants_tenant_id_tenant_prompt_drafts_revision_id_publish_post,
        "sync_detailed",
        publish,
    )
    prompts.run_tenant_prompt(settings(tmp_path), "publish", SLUG)
    output = capsys.readouterr().out
    assert "Published Tenant Prompt" in output
    assert "not active in runtime" in output
    assert seen == {"tenant_id": TENANT_ID, "revision_id": UUID(int=5)}
    assert not prompts.tenant_prompt_path(tmp_path, SLUG).exists()
