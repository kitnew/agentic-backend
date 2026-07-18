from dataclasses import dataclass

from app.tenants.schemas import TenantContext


@dataclass(frozen=True)
class VoiceRuntimeContext:
    tenant_id: str
    language: str | None
    timezone: str


def build_voice_runtime_context(tenant_context: TenantContext) -> VoiceRuntimeContext:
    return VoiceRuntimeContext(
        tenant_id=tenant_context.tenant_id,
        language=(
            tenant_context.voice.stt.language
            or tenant_context.voice.tts.language
            or tenant_context.agent.language
            or tenant_context.default_language
        ),
        timezone=tenant_context.timezone,
    )
