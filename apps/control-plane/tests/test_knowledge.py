from contextlib import nullcontext
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.knowledge_base_plan_response import (
    KnowledgeBasePlanResponse,
)
from admin_client.generated.models.knowledge_base_plan_response_status import (
    KnowledgeBasePlanResponseStatus,
)
from admin_client.generated.models.knowledge_base_publish_response import (
    KnowledgeBasePublishResponse,
)
from admin_client.generated.models.knowledge_base_push_response import (
    KnowledgeBasePushResponse,
)
from admin_client.generated.models.knowledge_base_revision_response import (
    KnowledgeBaseRevisionResponse,
)
from admin_client.generated.models.knowledge_base_snapshot_response import (
    KnowledgeBaseSnapshotResponse,
)
from admin_client.generated.models.knowledge_base_state_response import (
    KnowledgeBaseStateResponse,
)
from admin_client.generated.models.knowledge_document_plan_response import (
    KnowledgeDocumentPlanResponse,
)
from admin_client.generated.models.knowledge_document_plan_response_action import (
    KnowledgeDocumentPlanResponseAction,
)
from admin_client.generated.models.knowledge_document_plan_response_status import (
    KnowledgeDocumentPlanResponseStatus,
)
from admin_client.generated.models.knowledge_document_revision_response import (
    KnowledgeDocumentRevisionResponse,
)
from admin_client.generated.types import Response
from control_plane.commands import knowledge
from control_plane.settings import Settings

NOW = datetime(2026, 8, 10, tzinfo=UTC)
TENANT_ID = UUID(int=100)


def settings(path: Path) -> Settings:
    return Settings("https://backend.example", "secret", path)


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


def revision(number: int, status: str = "published") -> KnowledgeBaseRevisionResponse:
    return KnowledgeBaseRevisionResponse(
        created_at=NOW,
        document_count=2,
        id=UUID(int=number),
        knowledge_base_id=UUID(int=90),
        published_at=NOW if status == "published" else None,
        revision_number=number,
        status=status,
        tenant_id=TENANT_ID,
        version=number,
    )


def snapshot() -> KnowledgeBaseSnapshotResponse:
    return KnowledgeBaseSnapshotResponse(
        documents=[
            KnowledgeDocumentRevisionResponse(
                content="General\n",
                content_hash="hash-knowledge",
                document_revision_number=3,
                key="knowledge",
                media_type="text/markdown",
                position=0,
            ),
            KnowledgeDocumentRevisionResponse(
                content="Rooms",
                content_hash="hash-rooms",
                document_revision_number=2,
                key="rooms",
                media_type="text/markdown",
                position=1,
            ),
        ],
        revision=revision(4),
    )


def plan() -> KnowledgeBasePlanResponse:
    return KnowledgeBasePlanResponse(
        base_version=7,
        create_count=1,
        documents=[
            KnowledgeDocumentPlanResponse(
                action=KnowledgeDocumentPlanResponseAction.REUSE,
                current_revision_number=3,
                key="knowledge",
                status=KnowledgeDocumentPlanResponseStatus.UNCHANGED,
            ),
            KnowledgeDocumentPlanResponse(
                action=KnowledgeDocumentPlanResponseAction.CREATE,
                current_revision_number=None,
                key="rooms",
                status=KnowledgeDocumentPlanResponseStatus.LOCAL_ONLY,
            ),
        ],
        remove_count=0,
        reuse_count=1,
        status=KnowledgeBasePlanResponseStatus.MODIFIED,
        tenant_id=TENANT_ID,
        update_draft=True,
    )


def test_flat_markdown_validation_rejects_unsupported_entries(tmp_path: Path) -> None:
    directory = tmp_path / "knowledge"
    directory.mkdir()
    (directory / "knowledge.md").write_text("facts", encoding="utf-8")
    assert knowledge.read_knowledge_documents(directory, required=True)[1] == {
        "knowledge": "facts"
    }

    (directory / "notes.txt").write_text("unsupported", encoding="utf-8")
    with pytest.raises(knowledge.PromptCommandError, match=r"only \*\.md"):
        knowledge.read_knowledge_documents(directory, required=True)
    (directory / "notes.txt").unlink()

    (directory / "nested").mkdir()
    with pytest.raises(knowledge.PromptCommandError, match="nested"):
        knowledge.read_knowledge_documents(directory, required=True)
    (directory / "nested").rmdir()

    (directory / "Rooms.md").write_text("bad key", encoding="utf-8")
    with pytest.raises(knowledge.PromptCommandError, match="filenames must match"):
        knowledge.read_knowledge_documents(directory, required=True)


def test_symlink_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "knowledge"
    directory.mkdir()
    target = tmp_path / "target.md"
    target.write_text("facts", encoding="utf-8")
    (directory / "knowledge.md").symlink_to(target)
    with pytest.raises(knowledge.PromptCommandError, match="symlinks"):
        knowledge.read_knowledge_documents(directory, required=True)


def test_pull_synchronizes_exact_managed_document_set(tmp_path: Path) -> None:
    directory = tmp_path / "knowledge"
    knowledge._pull(directory, snapshot(), force=False)
    assert {
        path.name: path.read_text(encoding="utf-8") for path in directory.iterdir()
    } == {"knowledge.md": "General\n", "rooms.md": "Rooms"}

    (directory / "knowledge.md").write_text("General", encoding="utf-8")
    knowledge._pull(directory, snapshot(), force=False)

    (directory / "knowledge.md").write_text("changed", encoding="utf-8")
    (directory / "local.md").write_text("local", encoding="utf-8")
    with pytest.raises(knowledge.PromptCommandError, match="--force"):
        knowledge._pull(directory, snapshot(), force=False)
    knowledge._pull(directory, snapshot(), force=True)
    assert sorted(path.name for path in directory.iterdir()) == [
        "knowledge.md",
        "rooms.md",
    ]
    assert (directory / "knowledge.md").read_text(encoding="utf-8") == "General\n"


def test_plan_and_push_use_generated_high_level_operations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = knowledge.knowledge_directory(tmp_path, "debug-hotel")
    directory.mkdir(parents=True)
    (directory / "rooms.md").write_text("Rooms", encoding="utf-8")
    (directory / "knowledge.md").write_text("General", encoding="utf-8")
    seen: dict[str, object] = {}

    monkeypatch.setattr(knowledge, "_client", lambda settings: nullcontext(object()))
    monkeypatch.setattr(
        knowledge, "_tenant", lambda client, slug: SimpleNamespace(id=TENANT_ID)
    )
    monkeypatch.setattr(
        knowledge.plan_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_plan_post,
        "sync_detailed",
        lambda tenant_id, *, client, body: response(plan()),
    )

    def generated_push(
        tenant_id: UUID, *, client: object, body: object, if_match: str
    ) -> Response[object]:
        seen.update(tenant_id=tenant_id, body=body, if_match=if_match)
        return response(KnowledgeBasePushResponse(changed=True, draft=snapshot()))

    monkeypatch.setattr(
        knowledge.push_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_push_post,
        "sync_detailed",
        generated_push,
    )
    knowledge.run_tenant_knowledge(settings(tmp_path), "plan", "debug-hotel")
    assert "reuse 1 document revision" in capsys.readouterr().out
    knowledge.run_tenant_knowledge(settings(tmp_path), "push", "debug-hotel")
    assert seen["tenant_id"] == TENANT_ID
    assert seen["if_match"] == '"7"'
    assert [item.key for item in seen["body"].documents] == ["knowledge", "rooms"]


@pytest.mark.parametrize("action", ["show", "revisions", "publish"])
def test_backend_only_commands_do_not_read_filesystem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    action: str,
) -> None:
    monkeypatch.setattr(knowledge, "_client", lambda settings: nullcontext(object()))
    monkeypatch.setattr(
        knowledge, "_tenant", lambda client, slug: SimpleNamespace(id=TENANT_ID)
    )
    monkeypatch.setattr(
        knowledge,
        "read_knowledge_documents",
        lambda *args, **kwargs: pytest.fail("must not read filesystem"),
    )
    state = KnowledgeBaseStateResponse(
        draft_revision=None,
        latest_published_revision=revision(4),
        published_documents=[],
        tenant_id=TENANT_ID,
    )
    operations = {
        "show": (
            knowledge.show_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_get,
            state,
        ),
        "revisions": (
            knowledge.list_knowledge_base_revisions_admin_v1_tenants_tenant_id_knowledge_base_revisions_get,
            [revision(4)],
        ),
        "publish": (
            knowledge.publish_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_publish_post,
            KnowledgeBasePublishResponse(published=snapshot()),
        ),
    }
    operation, parsed = operations[action]
    monkeypatch.setattr(
        operation,
        "sync_detailed",
        lambda tenant_id, *, client: response(parsed),
    )
    knowledge.run_tenant_knowledge(settings(tmp_path), action, "debug-hotel")
