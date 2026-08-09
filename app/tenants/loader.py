from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.capabilities.providers.make_webhook import valid_webhook_config
from app.tenants.schemas import TenantContext


class TenantConfigNotFoundError(Exception):
    pass


class TenantConfigInvalidError(Exception):
    pass


class TenantConfigLoader:
    known_capabilities = {
        "calculator.calculate",
        "knowledge.search",
        "notification.send_staff_message",
        "reservation.check_availability",
        "reservation.cancel_request",
        "reservation.change_request",
        "reservation.create_request",
        "reservation.check_existing_reservation",
    }
    known_voice_providers = {"elevenlabs"}

    def __init__(self, configs_dir: Path | None = None, content_dir: Path | None = None):
        self.configs_dir = configs_dir or Path(__file__).parent / "configs"
        self.content_dir = (content_dir or self.configs_dir.parent / "content").resolve()
        self._cache: dict[str, TenantContext] = {}

    def load(self, tenant_id: str) -> TenantContext:
        if tenant_id in self._cache:
            return self._cache[tenant_id]
        if Path(tenant_id).name != tenant_id:
            raise TenantConfigNotFoundError(f"Invalid tenant id: {tenant_id}")

        config_path = self.configs_dir / f"{tenant_id}.yaml"
        if not config_path.exists():
            raise TenantConfigNotFoundError(f"Tenant config not found: {tenant_id}")

        try:
            with config_path.open("r", encoding="utf-8") as config_file:
                raw_config = yaml.safe_load(config_file) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise TenantConfigInvalidError(f"Cannot read tenant config {config_path}: {exc}") from exc

        if not isinstance(raw_config, dict):
            raise TenantConfigInvalidError(
                f"Tenant config {config_path} must contain a YAML object"
            )
        raw_config = self._normalize(raw_config, config_path)

        try:
            tenant_context = TenantContext.model_validate(raw_config)
        except ValidationError as exc:
            raise TenantConfigInvalidError(f"Tenant config {config_path} is invalid: {exc}") from exc

        if tenant_context.tenant_id != tenant_id:
            raise TenantConfigInvalidError(
                f"Tenant config id mismatch: expected {tenant_id}, got {tenant_context.tenant_id}"
            )

        tenant_context = self._load_prompt_content(tenant_context, config_path)
        self._cache[tenant_id] = tenant_context
        return tenant_context

    def _normalize(self, raw_config: dict[str, Any], config_path: Path) -> dict[str, Any]:
        normalized = dict(raw_config)
        schema_version = normalized.get("schema_version", 1)
        if schema_version not in (1, 2):
            raise TenantConfigInvalidError(
                f"Tenant config {config_path} has unsupported schema_version: {schema_version}"
            )
        normalized["schema_version"] = 2
        normalized.setdefault(
            "supported_locales",
            [normalized.get("locale") or normalized.get("default_language")],
        )
        return normalized

    def _load_prompt_content(
        self, tenant_context: TenantContext, config_path: Path
    ) -> TenantContext:
        prompt = tenant_context.prompt
        references = [
            *([prompt.instructions_file] if prompt.instructions_file else []),
            *prompt.knowledge_base_files,
        ]
        if len(references) != len(set(references)):
            raise TenantConfigInvalidError(
                f"Tenant config {config_path} contains duplicate prompt content references"
            )

        loaded = {reference: self._read_content(reference, config_path) for reference in references}
        prompt = prompt.model_copy(
            update={
                "instructions": loaded.get(prompt.instructions_file, ""),
                "knowledge_base": "\n\n".join(
                    loaded[path] for path in prompt.knowledge_base_files
                ),
            }
        )
        return tenant_context.model_copy(update={"prompt": prompt})

    def _read_content(self, reference: str, config_path: Path) -> str:
        relative_path = Path(reference)
        if relative_path.is_absolute():
            raise TenantConfigInvalidError(
                f"Tenant config {config_path} references absolute content path: {reference}"
            )
        content_path = (self.content_dir / relative_path).resolve()
        if not content_path.is_relative_to(self.content_dir):
            raise TenantConfigInvalidError(
                f"Tenant config {config_path} content path escapes {self.content_dir}: {reference}"
            )
        if not content_path.is_file():
            raise TenantConfigInvalidError(
                f"Tenant config {config_path} referenced content file does not exist: {reference}"
            )
        try:
            return content_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise TenantConfigInvalidError(
                f"Tenant config {config_path} cannot read content file {reference}: {exc}"
            ) from exc

    def validate_all(self, provider_names: set[str]) -> list[TenantContext]:
        tenant_contexts = []
        for config_path in sorted(self.configs_dir.glob("*.yaml")):
            tenant_context = self.load(config_path.stem)
            self._validate_capabilities(tenant_context, provider_names)
            self._validate_voice(tenant_context)
            tenant_contexts.append(tenant_context)

        assignments: dict[str, str] = {}
        for tenant in tenant_contexts:
            for did in tenant.voice.inbound_dids:
                if owner := assignments.get(did):
                    raise TenantConfigInvalidError(
                        f"Inbound DID {did} is assigned to both {owner} and {tenant.tenant_id}"
                    )
                assignments[did] = tenant.tenant_id
        return tenant_contexts

    def find_by_inbound_did(self, did: str) -> TenantContext | None:
        match = None
        for config_path in sorted(self.configs_dir.glob("*.yaml")):
            tenant = self.load(config_path.stem)
            if did not in tenant.voice.inbound_dids:
                continue
            if match:
                raise TenantConfigInvalidError(
                    f"Inbound DID {did} is assigned to both {match.tenant_id} and {tenant.tenant_id}"
                )
            match = tenant
        return match

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

            if capability_config.enabled and capability_config.provider == "make_webhook":
                if not valid_webhook_config(capability_config.config):
                    raise TenantConfigInvalidError(
                        f"make_webhook capability {capability_name} in tenant config "
                        f"{tenant_context.tenant_id} requires an http(s) webhook_url "
                        "and positive timeout_seconds"
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
