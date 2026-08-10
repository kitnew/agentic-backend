from typing import Any

from admin_client.generated.api.admintenants import (
    apply_prompt_set_admin_v1_tenants_tenant_id_prompt_set_apply_post,
    plan_prompt_set_admin_v1_tenants_tenant_id_prompt_set_plan_get,
    prompt_set_history_admin_v1_tenants_tenant_id_prompt_set_history_get,
    show_prompt_set_admin_v1_tenants_tenant_id_prompt_set_get,
)
from admin_client.generated.models.prompt_set_apply_response import (
    PromptSetApplyResponse,
)
from admin_client.generated.models.prompt_set_component_plan_response import (
    PromptSetComponentPlanResponse,
)
from admin_client.generated.models.prompt_set_component_response import (
    PromptSetComponentResponse,
)
from admin_client.generated.models.prompt_set_detail_response import (
    PromptSetDetailResponse,
)
from admin_client.generated.models.prompt_set_plan_response import (
    PromptSetPlanResponse,
)
from admin_client.generated.types import Response

from control_plane.commands.prompts import (
    PromptCommandError,
    _client,
    _response_error,
    _tenant,
)
from control_plane.settings import Settings


def _expect(response: Response[Any], expected: type[Any]) -> Any:
    _response_error(response)
    if not isinstance(response.parsed, expected):
        raise PromptCommandError(
            "unexpected client failure: invalid Backend response", 1
        )
    return response.parsed


def _component(value: PromptSetComponentResponse) -> str:
    if isinstance(value.key, str):
        return f"{value.key}@{value.revision_number}"
    return f"revision {value.revision_number}"


def _show(slug: str, detail: PromptSetDetailResponse) -> None:
    components = detail.components
    print(f"Prompt Set: {slug}\n")
    print(f"Active revision: {detail.revision.revision_number}\n")
    print(f"System:\n  {_component(components.system)}\n")
    print(f"Profile:\n  {_component(components.profile)}\n")
    print(f"Tenant Prompt:\n  {_component(components.tenant_prompt)}\n")
    print(f"Knowledge Base:\n  {_component(components.knowledge_base)}")


def _revisions(history: list[PromptSetDetailResponse]) -> None:
    if not history:
        print("No PromptSet revisions.")
        return
    print("REVISION  STATUS      SYSTEM       PROFILE               TENANT  KB")
    for detail in history:
        revision = detail.revision
        components = detail.components
        print(
            f"{revision.revision_number:<8}  {revision.status:<10}  "
            f"{_component(components.system):<12}  "
            f"{_component(components.profile):<20}  "
            f"{components.tenant_prompt.revision_number:<6}  "
            f"{components.knowledge_base.revision_number}"
        )


def _plan_component(label: str, component: PromptSetComponentPlanResponse) -> None:
    before = "missing" if component.active is None else _component(component.active)
    after = _component(component.desired)
    print(f"{label}\n  {before}\n  → {after}")
    if component.changed and isinstance(component.reason, str):
        print(f"  reason: {component.reason}")
    elif not component.changed:
        print("  unchanged")


def _plan(plan: PromptSetPlanResponse) -> None:
    print(f"Status: {plan.status.value}\n")
    if plan.active_revision_number is not None:
        print(f"Active revision: {plan.active_revision_number}\n")
    components = plan.components
    _plan_component("System Prompt", components.system)
    print()
    _plan_component("Profile Prompt", components.profile)
    print()
    _plan_component("Tenant Prompt", components.tenant_prompt)
    print()
    _plan_component("Knowledge Base", components.knowledge_base)
    print("\nPlan:")
    print(
        "  no changes"
        if plan.status.value == "unchanged"
        else "  create and publish new PromptSet\n  activate it for new calls"
    )


def run_tenant_prompt_set(settings: Settings, action: str, slug: str) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, slug)
        if action == "show":
            show_response = show_prompt_set_admin_v1_tenants_tenant_id_prompt_set_get.sync_detailed(
                tenant.id, client=client
            )
            _show(slug, _expect(show_response, PromptSetDetailResponse))
        elif action == "revisions":
            history_response = prompt_set_history_admin_v1_tenants_tenant_id_prompt_set_history_get.sync_detailed(
                tenant.id, client=client
            )
            _response_error(history_response)
            if not isinstance(history_response.parsed, list) or not all(
                isinstance(item, PromptSetDetailResponse)
                for item in history_response.parsed
            ):
                raise PromptCommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            _revisions(history_response.parsed)
        elif action == "plan":
            plan_response = plan_prompt_set_admin_v1_tenants_tenant_id_prompt_set_plan_get.sync_detailed(
                tenant.id, client=client
            )
            _plan(_expect(plan_response, PromptSetPlanResponse))
        elif action == "apply":
            apply_response = apply_prompt_set_admin_v1_tenants_tenant_id_prompt_set_apply_post.sync_detailed(
                tenant.id, client=client
            )
            result = _expect(apply_response, PromptSetApplyResponse)
            if not result.changed:
                print("No changes; active PromptSet already matches desired state.")
            else:
                print(
                    f"Activated PromptSet revision "
                    f"{result.prompt_set.revision.revision_number} for new calls."
                )
            _show(slug, result.prompt_set)
        else:
            raise PromptCommandError(f"unsupported PromptSet action: {action}", 2)
