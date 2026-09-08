from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings

ConfigurationScope = Literal["system", "platform", "tenant"]


def _read(path: Path) -> dict:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CommandError(f"missing desired configuration file: {path}", 2) from None
    except yaml.YAMLError as error:
        raise CommandError(f"invalid desired configuration YAML: {error}", 2) from error
    if not isinstance(value, dict):
        raise CommandError("desired configuration YAML root must be a mapping", 2)
    return value


def _print(value: object) -> None:
    print(yaml.safe_dump(value, sort_keys=False), end="")


def run_configuration(
    settings: Settings,
    scope: ConfigurationScope,
    action: str,
    *,
    tenant_id: str | None = None,
    file: Path | None = None,
) -> None:
    with ControlPlaneClient(settings) as client:
        if action == "get":
            state = client.get_configuration_optional(scope, tenant_id)
            if state is None:
                raise CommandError(f"{scope} configuration is not initialized", 3)
            _print(state.value)
            return

        if action == "plan":
            if file is None:
                raise CommandError("desired configuration file is required", 2)
            _print(client.plan_configuration(scope, _read(file), tenant_id))
            return

        if action == "apply":
            if file is None:
                raise CommandError("desired configuration file is required", 2)
            state = client.get_configuration_optional(scope, tenant_id)
            _print(
                client.apply_configuration(
                    scope,
                    _read(file),
                    None if state is None else state.write_etag,
                    tenant_id,
                    if_none_match=state is None,
                )
            )
            return

        if action == "publish":
            state = client.get_configuration_optional(scope, tenant_id)
            if state is None:
                raise CommandError(f"{scope} configuration is not initialized", 3)
            _print(client.publish_configuration(scope, state.write_etag, tenant_id))
            return

        raise CommandError(f"unsupported configuration action: {action}", 2)
