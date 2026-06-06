from pathlib import Path

import yaml
from pydantic import ValidationError

from app.tenants.schemas import TenantContext


class TenantConfigNotFoundError(Exception):
    pass


class TenantConfigInvalidError(Exception):
    pass


class TenantConfigLoader:
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
