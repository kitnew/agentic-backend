import re
from http import HTTPStatus
from pathlib import Path
from typing import Any

from admin_client.generated.api.admintenants import (
    get_published_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_published_get,
    list_knowledge_base_revisions_admin_v1_tenants_tenant_id_knowledge_base_revisions_get,
    plan_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_plan_post,
    publish_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_publish_post,
    push_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_push_post,
    show_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_get,
)
from admin_client.generated.models.knowledge_base_plan_response import (
    KnowledgeBasePlanResponse,
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
from admin_client.generated.models.knowledge_document_input import (
    KnowledgeDocumentInput,
)
from admin_client.generated.models.knowledge_documents_request import (
    KnowledgeDocumentsRequest,
)
from admin_client.generated.types import Response

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
    _tenant,
    content_matches,
)
from control_plane.settings import Settings

DOCUMENT_KEY = re.compile(r"^[a-z][a-z0-9_-]*$")


def knowledge_directory(state_dir: Path, slug: str) -> Path:
    return state_dir / "tenants" / slug / "knowledge"


def read_knowledge_documents(
    directory: Path, *, required: bool
) -> tuple[bool, dict[str, str]]:
    if directory.is_symlink():
        raise PromptCommandError(
            f"canonical knowledge path must be a real directory: {directory}", 2
        )
    if not directory.exists():
        if required:
            raise PromptCommandError(
                f"missing canonical knowledge directory: {directory}", 2
            )
        return False, {}
    if not directory.is_dir():
        raise PromptCommandError(
            f"canonical knowledge path must be a real directory: {directory}", 2
        )
    documents: dict[str, str] = {}
    try:
        entries = sorted(directory.iterdir(), key=lambda path: path.name)
        for path in entries:
            if path.is_symlink():
                raise PromptCommandError(
                    f"knowledge symlinks are not supported: {path}", 2
                )
            if path.is_dir():
                raise PromptCommandError(
                    f"nested knowledge directories are not supported: {path}", 2
                )
            if path.suffix != ".md":
                raise PromptCommandError(
                    f"unsupported knowledge file (only *.md is allowed): {path}", 2
                )
            key = path.stem
            if not DOCUMENT_KEY.fullmatch(key):
                raise PromptCommandError(
                    "knowledge filenames must match ^[a-z][a-z0-9_-]*\\.md$: "
                    f"{path.name}",
                    2,
                )
            folded = key.casefold()
            if any(existing.casefold() == folded for existing in documents):
                raise PromptCommandError(
                    f"case-colliding knowledge filename: {path.name}", 2
                )
            documents[key] = path.read_bytes().decode("utf-8")
    except PromptCommandError:
        raise
    except (OSError, UnicodeDecodeError) as error:
        raise PromptCommandError(
            f"cannot read canonical knowledge directory {directory}: {error}", 2
        ) from error
    return True, documents


def _request(documents: dict[str, str]) -> KnowledgeDocumentsRequest:
    return KnowledgeDocumentsRequest(
        documents=[
            KnowledgeDocumentInput(key=key, content=content)
            for key, content in sorted(documents.items())
        ]
    )


def _expect(response: Response[Any], expected: type[Any]) -> Any:
    _response_error(response)
    if not isinstance(response.parsed, expected):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _show(slug: str, state: KnowledgeBaseStateResponse) -> None:
    print(f"Knowledge Base: {slug}\n")
    published = state.latest_published_revision
    draft = state.draft_revision
    print(
        "Latest published revision: "
        + (str(published.revision_number) if published else "none")
    )
    print("Draft revision: " + (str(draft.revision_number) if draft else "none"))
    print("\nPublished documents:")
    if not state.published_documents:
        print("  none")
    for document in state.published_documents:
        print(
            f"  {document.key}.md  document revision "
            f"{document.document_revision_number}"
        )


def _revisions(revisions: list[KnowledgeBaseRevisionResponse]) -> None:
    if not revisions:
        print("No Knowledge Base revisions.")
        return
    print("REVISION  STATUS      DOCUMENTS  PUBLISHED")
    for revision in revisions:
        published = revision.published_at.isoformat() if revision.published_at else "-"
        print(
            f"{revision.revision_number:<8}  {revision.status:<10}  "
            f"{revision.document_count:<9}  {published}"
        )


def _pull(
    directory: Path, snapshot: KnowledgeBaseSnapshotResponse, *, force: bool
) -> None:
    existed, local = read_knowledge_documents(directory, required=False)
    remote = {document.key: document.content for document in snapshot.documents}
    same = local.keys() == remote.keys() and all(
        content_matches(local[key], remote[key]) for key in local
    )
    if existed and same:
        print(f"Already current: {directory}")
        return
    if existed and not force:
        raise PromptCommandError(
            "Local knowledge directory differs from the remote published snapshot. "
            "Use --force to synchronize it.",
            2,
        )
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for key in local.keys() - remote.keys():
            (directory / f"{key}.md").unlink()
        for key, content in sorted(remote.items()):
            (directory / f"{key}.md").write_bytes(content.encode("utf-8"))
    except OSError as error:
        raise PromptCommandError(
            f"cannot synchronize canonical knowledge directory {directory}: {error}", 2
        ) from error
    print(
        f"Wrote published Knowledge Base revision "
        f"{snapshot.revision.revision_number} to {directory}"
    )


def _render_plan(slug: str, plan: KnowledgeBasePlanResponse) -> None:
    print(f"Knowledge Base: {slug}\n")
    print(f"Status: {plan.status.value}\n")
    print("Documents:\n")
    for document in plan.documents:
        print(f"{document.key}.md")
        print(f"  {document.status.value}")
        if document.action.value == "reuse":
            print(f"  document revision {document.current_revision_number}")
        elif document.action.value == "create" and document.current_revision_number:
            print(
                f"  document revision {document.current_revision_number} → new revision"
            )
        elif document.action.value == "create":
            print("  → add document")
        else:
            print("  → remove from next snapshot")
        print()
    print("Plan:")
    print(f"  reuse {plan.reuse_count} document revision(s)")
    print(f"  create {plan.create_count} document revision(s)")
    print(f"  remove {plan.remove_count} document(s) from snapshot")
    print("  update KnowledgeBase draft" if plan.update_draft else "  no changes")
    print("  no publication")


def run_tenant_knowledge(
    settings: Settings, action: str, slug: str, *, force: bool = False
) -> None:
    directory = knowledge_directory(settings.state_dir, slug)
    with _client(settings) as client:
        tenant = _tenant(client, slug)
        if action == "show":
            state_response = show_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_get.sync_detailed(
                tenant.id, client=client
            )
            _show(slug, _expect(state_response, KnowledgeBaseStateResponse))
        elif action == "revisions":
            history_response = list_knowledge_base_revisions_admin_v1_tenants_tenant_id_knowledge_base_revisions_get.sync_detailed(
                tenant.id, client=client
            )
            _response_error(history_response)
            if not isinstance(history_response.parsed, list) or not all(
                isinstance(item, KnowledgeBaseRevisionResponse)
                for item in history_response.parsed
            ):
                raise PromptCommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            _revisions(history_response.parsed)
        elif action == "pull":
            published_response = get_published_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_published_get.sync_detailed(
                tenant.id, client=client
            )
            _pull(
                directory,
                _expect(published_response, KnowledgeBaseSnapshotResponse),
                force=force,
            )
        elif action in {"plan", "push"}:
            _, documents = read_knowledge_documents(directory, required=True)
            body = _request(documents)
            plan_response = plan_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_plan_post.sync_detailed(
                tenant.id, client=client, body=body
            )
            plan = _expect(plan_response, KnowledgeBasePlanResponse)
            if action == "plan":
                _render_plan(slug, plan)
                return
            pushed = push_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_push_post.sync_detailed(
                tenant.id,
                client=client,
                body=body,
                if_match=f'"{plan.base_version}"',
            )
            if pushed.status_code in {
                HTTPStatus.CONFLICT,
                HTTPStatus.PRECONDITION_FAILED,
            }:
                raise PromptCommandError(
                    "remote KnowledgeBase draft changed; run plan and retry", 5
                )
            result = _expect(pushed, KnowledgeBasePushResponse)
            if not result.changed:
                print("No changes; remote Knowledge Base state is current.")
            elif result.draft is not None:
                print(
                    f"Updated Knowledge Base draft revision "
                    f"{result.draft.revision.revision_number} with "
                    f"{len(result.draft.documents)} document(s)."
                )
                print("No publication.")
        elif action == "publish":
            publish_response = publish_knowledge_base_admin_v1_tenants_tenant_id_knowledge_base_publish_post.sync_detailed(
                tenant.id, client=client
            )
            result = _expect(publish_response, KnowledgeBasePublishResponse)
            print(
                f"Published Knowledge Base revision "
                f"{result.published.revision.revision_number} for '{slug}'.\n"
            )
            print(
                "The new knowledge revision is not active until referenced by an "
                "applied PromptSet."
            )
        else:
            raise PromptCommandError(f"unsupported Knowledge Base action: {action}", 2)
