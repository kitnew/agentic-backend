from contextlib import nullcontext
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from admin_client.generated.models.prompt_set_apply_response import (
    PromptSetApplyResponse,
)
from admin_client.generated.models.prompt_set_component_plan_response import (
    PromptSetComponentPlanResponse,
)
from admin_client.generated.models.prompt_set_component_response import (
    PromptSetComponentResponse,
)
from admin_client.generated.models.prompt_set_composition_response import (
    PromptSetCompositionResponse,
)
from admin_client.generated.models.prompt_set_detail_response import (
    PromptSetDetailResponse,
)
from admin_client.generated.models.prompt_set_plan_components_response import (
    PromptSetPlanComponentsResponse,
)
from admin_client.generated.models.prompt_set_plan_response import (
    PromptSetPlanResponse,
)
from admin_client.generated.models.prompt_set_plan_response_status import (
    PromptSetPlanResponseStatus,
)
from admin_client.generated.models.prompt_set_revision_response import (
    PromptSetRevisionResponse,
)
from admin_client.generated.types import Response
from control_plane.commands import prompt_sets
from control_plane.settings import Settings


def component(number: int, key: str | None = None) -> PromptSetComponentResponse:
    return PromptSetComponentResponse(
        revision_id=UUID(int=number), revision_number=number, key=key
    )


def detail() -> PromptSetDetailResponse:
    return PromptSetDetailResponse(
        revision=PromptSetRevisionResponse(
            created_at=datetime(2026, 8, 10, tzinfo=UTC),
            id=UUID(int=10),
            knowledge_base_revision_id=UUID(int=4),
            profile_prompt_revision_id=UUID(int=2),
            published_at=datetime(2026, 8, 10, tzinfo=UTC),
            revision_number=8,
            status="published",
            system_prompt_revision_id=UUID(int=1),
            tenant_id=UUID(int=100),
            tenant_prompt_revision_id=UUID(int=3),
            version=1,
        ),
        components=PromptSetCompositionResponse(
            system=component(4, "default"),
            profile=component(2, "hotel_assistant"),
            tenant_prompt=component(5),
            knowledge_base=component(3),
        ),
    )


def response(parsed: object) -> Response[object]:
    return Response(
        status_code=HTTPStatus.OK,
        content=b"",
        headers=httpx.Headers(),
        parsed=parsed,
    )


@pytest.mark.parametrize("action", ["show", "revisions", "plan", "apply"])
def test_prompt_set_commands_use_generated_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    action: str,
) -> None:
    seen: list[UUID] = []
    current = detail()
    unchanged = PromptSetComponentPlanResponse(
        active=current.components.system,
        changed=False,
        desired=current.components.system,
    )
    plan = PromptSetPlanResponse(
        active_revision_number=8,
        components=PromptSetPlanComponentsResponse(
            system=unchanged,
            profile=PromptSetComponentPlanResponse(
                active=current.components.profile,
                changed=False,
                desired=current.components.profile,
            ),
            tenant_prompt=PromptSetComponentPlanResponse(
                active=current.components.tenant_prompt,
                changed=False,
                desired=current.components.tenant_prompt,
            ),
            knowledge_base=PromptSetComponentPlanResponse(
                active=current.components.knowledge_base,
                changed=False,
                desired=current.components.knowledge_base,
            ),
        ),
        status=PromptSetPlanResponseStatus.UNCHANGED,
        tenant_id=UUID(int=100),
    )
    operations = {
        "show": (
            prompt_sets.show_prompt_set_admin_v1_tenants_tenant_id_prompt_set_get,
            current,
        ),
        "revisions": (
            prompt_sets.prompt_set_history_admin_v1_tenants_tenant_id_prompt_set_history_get,
            [current],
        ),
        "plan": (
            prompt_sets.plan_prompt_set_admin_v1_tenants_tenant_id_prompt_set_plan_get,
            plan,
        ),
        "apply": (
            prompt_sets.apply_prompt_set_admin_v1_tenants_tenant_id_prompt_set_apply_post,
            PromptSetApplyResponse(changed=False, prompt_set=current),
        ),
    }
    operation, parsed = operations[action]

    def generated(tenant_id: UUID, *, client: object) -> Response[object]:
        seen.append(tenant_id)
        return response(parsed)

    monkeypatch.setattr(operation, "sync_detailed", generated)
    monkeypatch.setattr(prompt_sets, "_client", lambda settings: nullcontext(object()))
    monkeypatch.setattr(
        prompt_sets,
        "_tenant",
        lambda client, slug: SimpleNamespace(id=UUID(int=100)),
    )

    prompt_sets.run_tenant_prompt_set(
        Settings("https://backend.example", "secret", Path("control-plane")),
        action,
        "debug-hotel",
    )
    assert seen == [UUID(int=100)]
    assert capsys.readouterr().out
