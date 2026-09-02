from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from agentctl.commands.common import _client, _tenant
from agentctl.commands.errors import CommandError
from agentctl.control_plane import ControlPlaneClient
from agentctl.settings import Settings

COMPONENTS = ("agent", "runtime", "prompt", "knowledge", "capabilities", "post_call")
KINDS = {
    "agent": "agent.tenant",
    "runtime": "runtime.architecture.policy",
    "prompt": "prompt.tenant",
    "knowledge": "knowledge.tenant",
    "capabilities": "capabilities.tenant",
    "post_call": "post_call.tenant",
}


def tenant_config_path(state_dir: Path, slug: str) -> Path:
    return state_dir / "tenants" / slug / "tenant.yaml"


def parse_tenant_yaml(text: str) -> dict[str, dict[str, Any]]:
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise CommandError(f"invalid tenant.yaml: {error}", 2) from error
    if not isinstance(document, dict):
        raise CommandError("tenant.yaml root must be a mapping", 2)
    unknown = set(document) - set(COMPONENTS)
    if unknown:
        raise CommandError(f"unknown tenant components: {', '.join(sorted(unknown))}", 2)
    if not all(isinstance(value, dict) for value in document.values()):
        raise CommandError("tenant components must be mappings", 2)
    return document


def run_tenant_components(settings: Settings, action: str, slug: str, *, force: bool = False) -> None:
    path = tenant_config_path(settings.state_dir, slug)
    with _client(settings) as backend:
        tenant = _tenant(backend, slug)
    with ControlPlaneClient(settings) as client:
        if action in {"show", "pull"}:
            document = {}
            for name, kind in KINDS.items():
                state = client.get_component(kind, tenant_id=tenant.id)
                if state.working is not None:
                    document[name] = state.working
            if action == "show":
                print(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), end="")
                return
            if path.exists() and not force:
                raise CommandError(f"refusing to overwrite existing file: {path}", 2)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
            return
        sections = parse_tenant_yaml(path.read_text(encoding="utf-8"))
        for name, value in sections.items():
            state = client.get_component(KINDS[name], tenant_id=tenant.id)
            if action == "push":
                client.save_component(KINDS[name], value, tenant_id=tenant.id, draft_version=state.draft_version)
                print(f"{name}: saved draft")
            elif action == "publish":
                if state.draft_version is not None:
                    client.publish_component(KINDS[name], state.draft_version, tenant_id=tenant.id)
                    print(f"{name}: published")
        if action not in {"push", "publish"}:
            raise CommandError(f"unsupported tenant config action: {action}", 2)
