from app.contracts.voice import VoiceTurnConfig, VoiceTurnOverrides


def resolve_voice_turn_config(
    tenant_config: VoiceTurnConfig | None = None,
    session_overrides: VoiceTurnOverrides | None = None,
) -> VoiceTurnConfig:
    values = (tenant_config or VoiceTurnConfig()).model_dump()
    if session_overrides:
        for group, overrides in session_overrides.model_dump(exclude_none=True).items():
            values[group].update(overrides)
    return VoiceTurnConfig.model_validate(values)


__all__ = ["VoiceTurnConfig", "VoiceTurnOverrides", "resolve_voice_turn_config"]
