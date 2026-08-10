from typing import Any

from admin_client.generated.api.admintenant_runtime import (
    apply_voice_runtime_admin_v1_tenants_tenant_id_voice_runtime_apply_post,
    list_voice_runtime_revisions_admin_v1_tenants_tenant_id_voice_runtime_revisions_get,
    plan_voice_runtime_admin_v1_tenants_tenant_id_voice_runtime_plan_get,
    show_voice_runtime_admin_v1_tenants_tenant_id_voice_runtime_get,
)
from admin_client.generated.models.voice_runtime_apply_response import (
    VoiceRuntimeApplyResponse,
)
from admin_client.generated.models.voice_runtime_plan_response import (
    VoiceRuntimePlanResponse,
)
from admin_client.generated.models.voice_runtime_revision_response import (
    VoiceRuntimeRevisionResponse,
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


def _show(slug: str, revision: VoiceRuntimeRevisionResponse) -> None:
    runtime = revision.effective_settings
    print(f"Voice Runtime: {slug}\n")
    print(f"Active revision: {revision.revision_number}")
    print(f"Platform source: {revision.platform_runtime_revision_id}")
    print(
        "Tenant source: "
        + (
            "none"
            if revision.tenant_runtime_revision_id is None
            else str(revision.tenant_runtime_revision_id)
        )
    )
    print(f"\nLocale\n  {runtime.locale}")
    print(f"\nLLM\n  {runtime.llm.provider} / {runtime.llm.model}")
    print(f"  temperature: {runtime.llm.temperature}")
    print(f"\nSTT\n  {runtime.stt.provider} / {runtime.stt.model}")
    print(
        f"\nTTS\n  {runtime.tts.provider} / {runtime.tts.model}\n"
        f"  voice: {runtime.tts.voice_id}"
    )
    print(
        "\nLocal VAD\n"
        f"  speech: {runtime.local_vad.min_speech_seconds}s\n"
        f"  silence: {runtime.local_vad.min_silence_seconds}s\n"
        f"  threshold: {runtime.local_vad.activation_threshold}"
    )
    print(
        "\nTurn\n"
        f"  detection: {runtime.turn.detection}\n"
        f"  endpointing: {runtime.turn.min_endpointing_delay_seconds}s"
        f"..{runtime.turn.max_endpointing_delay_seconds}s"
    )


def _plan(plan: VoiceRuntimePlanResponse) -> None:
    print(f"Status: {plan.status.value}\n")
    print(
        "Active Voice Runtime: "
        + (
            "none"
            if plan.active_revision is None
            else f"revision {plan.active_revision.revision_number}"
        )
    )
    if plan.changes:
        print("\nChanges:")
        for change in plan.changes:
            print(f"  {change.path}: {change.before!r} → {change.after!r}")
    print("\nPlan:")
    print(
        "  no changes"
        if plan.status.value == "unchanged"
        else "  create and activate a new VoiceRuntime revision for new calls"
    )


def run_tenant_voice_runtime(settings: Settings, action: str, slug: str) -> None:
    with _client(settings) as client:
        tenant = _tenant(client, slug)
        if action == "show":
            response = show_voice_runtime_admin_v1_tenants_tenant_id_voice_runtime_get.sync_detailed(
                tenant.id, client=client
            )
            _show(slug, _expect(response, VoiceRuntimeRevisionResponse))
        elif action == "revisions":
            revisions_response = list_voice_runtime_revisions_admin_v1_tenants_tenant_id_voice_runtime_revisions_get.sync_detailed(
                tenant.id, client=client
            )
            _response_error(revisions_response)
            if not isinstance(revisions_response.parsed, list) or not all(
                isinstance(item, VoiceRuntimeRevisionResponse)
                for item in revisions_response.parsed
            ):
                raise PromptCommandError(
                    "unexpected client failure: invalid Backend response", 1
                )
            if not revisions_response.parsed:
                print("No VoiceRuntime revisions.")
            else:
                print("REVISION  STATUS      PLATFORM SOURCE  TENANT SOURCE")
                for revision in revisions_response.parsed:
                    print(
                        f"{revision.revision_number:<8}  "
                        f"{revision.status.value:<10}  "
                        f"{revision.platform_runtime_revision_id!s:<36}  "
                        f"{revision.tenant_runtime_revision_id or '-'}"
                    )
        elif action == "plan":
            plan_response = plan_voice_runtime_admin_v1_tenants_tenant_id_voice_runtime_plan_get.sync_detailed(
                tenant.id, client=client
            )
            _plan(_expect(plan_response, VoiceRuntimePlanResponse))
        elif action == "apply":
            apply_response = apply_voice_runtime_admin_v1_tenants_tenant_id_voice_runtime_apply_post.sync_detailed(
                tenant.id, client=client
            )
            applied = _expect(apply_response, VoiceRuntimeApplyResponse)
            print(
                f"VoiceRuntime revision {applied.voice_runtime.revision_number}: "
                + ("created and activated" if applied.changed else "unchanged")
            )
        else:
            raise PromptCommandError(f"unsupported VoiceRuntime action: {action}", 2)
