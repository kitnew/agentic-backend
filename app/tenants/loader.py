from pathlib import Path

import yaml
from pydantic import ValidationError

from app.tenants.schemas import TenantContext


class TenantConfigNotFoundError(Exception):
    pass


class TenantConfigInvalidError(Exception):
    pass


class TenantConfigLoader:
    known_capabilities = {
        "knowledge.search",
        "notification.send_staff_message",
        "reservation.check_availability",
        "reservation.create_request",
    }
    known_voice_providers = {"elevenlabs"}

    def __init__(self, configs_dir: Path | None = None):
        self.configs_dir = configs_dir or Path(__file__).parent / "configs"

    def load(self, tenant_id: str) -> TenantContext:
        config_path = self.configs_dir / f"{tenant_id}.yaml"
        if not config_path.exists():
            raise TenantConfigNotFoundError(f"Tenant config not found: {tenant_id}")

        with config_path.open("r", encoding="utf-8") as config_file:
            raw_config = yaml.safe_load(config_file) or {}

        try:
            tenant_context = TenantContext.model_validate(raw_config)
        except ValidationError as exc:
            raise TenantConfigInvalidError(f"Tenant config is invalid: {tenant_id}") from exc

        if tenant_context.tenant_id != tenant_id:
            raise TenantConfigInvalidError(
                f"Tenant config id mismatch: expected {tenant_id}, got {tenant_context.tenant_id}"
            )

        return tenant_context

    def validate_all(self, provider_names: set[str]) -> list[TenantContext]:
        tenant_contexts = []
        for config_path in sorted(self.configs_dir.glob("*.yaml")):
            tenant_context = self.load(config_path.stem)
            self._validate_capabilities(tenant_context, provider_names)
            self._validate_voice(tenant_context)
            tenant_contexts.append(tenant_context)

        return tenant_contexts

    def _validate_capabilities(
        self,
        tenant_context: TenantContext,
        provider_names: set[str],
    ) -> None:
        for capability_name, capability_config in tenant_context.capabilities.items():
            if capability_name not in self.known_capabilities:
                raise TenantConfigInvalidError(
                    f"Unknown capability in tenant config {tenant_context.tenant_id}: {capability_name}"
                )

            if capability_config.provider not in provider_names:
                raise TenantConfigInvalidError(
                    f"Unknown provider for {capability_name} in tenant config "
                    f"{tenant_context.tenant_id}: {capability_config.provider}"
                )

            if (
                capability_config.enabled
                and capability_config.provider == "google_sheets"
                and (
                    not capability_config.config.get("spreadsheet_id")
                    or not capability_config.config.get("sheet_name")
                )
            ):
                raise TenantConfigInvalidError(
                    f"google_sheets capability {capability_name} in tenant config "
                    f"{tenant_context.tenant_id} requires spreadsheet_id and sheet_name"
                )

    def _validate_voice(self, tenant_context: TenantContext) -> None:
        if not tenant_context.voice.enabled:
            return

        if tenant_context.voice.stt.provider not in self.known_voice_providers:
            raise TenantConfigInvalidError(
                f"Unknown STT provider in tenant config {tenant_context.tenant_id}: "
                f"{tenant_context.voice.stt.provider}"
            )

        if tenant_context.voice.tts.provider not in self.known_voice_providers:
            raise TenantConfigInvalidError(
                f"Unknown TTS provider in tenant config {tenant_context.tenant_id}: "
                f"{tenant_context.voice.tts.provider}"
            )
