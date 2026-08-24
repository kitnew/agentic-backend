from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from control_plane.workspace.model import (
    DraftResourceKind,
    LiveResourceKind,
    PlatformResourceKind,
    ResourceId,
    ResourceKind,
    resource_path,
)


class ResourceCapability(StrEnum):
    REMOTE_READABLE = "remote_readable"
    PLANNABLE = "plannable"
    LIVE_MUTABLE = "live_mutable"
    SECRET_BEARING = "secret_bearing"
    LOCAL_PROJECTABLE = "local_projectable"
    DRAFT_WRITABLE = "draft_writable"
    PUBLISHABLE = "publishable"
    PUBLISHABLE_PARTICIPANT = "publishable_participant"


class ResourcePresence(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class ResourceDescriptor:
    kind: ResourceKind | PlatformResourceKind | LiveResourceKind | DraftResourceKind
    filename: str | None
    scope: str = "tenant"
    qualifier: str | None = None
    presence: ResourcePresence = ResourcePresence.REQUIRED
    capabilities: frozenset[ResourceCapability] = frozenset(
        {
            ResourceCapability.REMOTE_READABLE,
            ResourceCapability.PLANNABLE,
            ResourceCapability.LOCAL_PROJECTABLE,
            ResourceCapability.DRAFT_WRITABLE,
            ResourceCapability.PUBLISHABLE,
        }
    )

    def resource_id(self, tenant: str) -> ResourceId:
        return ResourceId(
            self.scope,
            tenant if self.scope == "tenant" else "platform",
            self.kind,
            self.qualifier,
        )

    def path(self, root: Path, tenant: str) -> Path:
        return resource_path(root, self.resource_id(tenant))


DESCRIPTORS = tuple(
    ResourceDescriptor(kind, filename)
    for kind, filename in (
        (ResourceKind.AGENT, "tenant.yaml"),
        (ResourceKind.RUNTIME, "runtime.yaml"),
        (ResourceKind.PROMPT, "tenant_prompt.md"),
        (ResourceKind.KNOWLEDGE, "knowledge/"),
        (ResourceKind.CAPABILITIES, "capabilities.yaml"),
        (ResourceKind.POST_CALL, "post_call.yaml"),
    )
)

PLATFORM_DESCRIPTORS = (
    ResourceDescriptor(ResourceKind.RUNTIME, "platform/runtime.yaml", "platform"),
    ResourceDescriptor(
        PlatformResourceKind.SYSTEM_PROMPT, "platform/system_prompt.md", "platform"
    ),
)


def platform_profile_descriptor(name: str) -> ResourceDescriptor:
    if (
        not name
        or Path(name).name != name
        or "/" in name
        or "\\" in name
        or name in {".", ".."}
    ):
        raise ValueError("unsafe platform profile qualifier")
    return ResourceDescriptor(
        PlatformResourceKind.PROFILE_PROMPT,
        f"platform/profiles/{name}.md",
        "platform",
        name,
        ResourcePresence.OPTIONAL,
    )


def integration_descriptor(key: str) -> ResourceDescriptor:
    if (
        not key
        or Path(key).name != key
        or "/" in key
        or "\\" in key
        or key in {".", ".."}
    ):
        raise ValueError("unsafe integration key")
    return ResourceDescriptor(
        LiveResourceKind.INTEGRATION,
        None,
        capabilities=frozenset(
            {
                ResourceCapability.REMOTE_READABLE,
                ResourceCapability.PLANNABLE,
                ResourceCapability.LIVE_MUTABLE,
                ResourceCapability.SECRET_BEARING,
            }
        ),
        qualifier=key,
    )


def integration_resource(tenant: str, key: str) -> ResourceId:
    return integration_descriptor(key).resource_id(tenant)


def telephony_descriptor() -> ResourceDescriptor:
    return ResourceDescriptor(
        DraftResourceKind.TELEPHONY,
        None,
        capabilities=frozenset(
            {
                ResourceCapability.REMOTE_READABLE,
                ResourceCapability.PLANNABLE,
                ResourceCapability.DRAFT_WRITABLE,
                ResourceCapability.PUBLISHABLE_PARTICIPANT,
            }
        ),
        presence=ResourcePresence.OPTIONAL,
    )


def telephony_resource(tenant: str) -> ResourceId:
    return telephony_descriptor().resource_id(tenant)


def resource_capabilities(resource_id: ResourceId) -> frozenset[ResourceCapability]:
    if resource_id.kind is LiveResourceKind.INTEGRATION:
        return integration_descriptor(resource_id.qualifier or "").capabilities
    if resource_id.kind is DraftResourceKind.TELEPHONY:
        return telephony_descriptor().capabilities
    return frozenset(
        {
            ResourceCapability.REMOTE_READABLE,
            ResourceCapability.PLANNABLE,
            ResourceCapability.LOCAL_PROJECTABLE,
            ResourceCapability.DRAFT_WRITABLE,
            ResourceCapability.PUBLISHABLE,
        }
    )


def resource_presence(resource_id: ResourceId) -> ResourcePresence:
    if resource_id.kind is LiveResourceKind.INTEGRATION:
        return ResourcePresence.OPTIONAL
    if resource_id.kind is DraftResourceKind.TELEPHONY:
        return ResourcePresence.OPTIONAL
    if resource_id.kind is PlatformResourceKind.PROFILE_PROMPT:
        return ResourcePresence.OPTIONAL
    return ResourcePresence.REQUIRED


def platform_resources(
    root: Path, remote: Iterable[ResourceId] = ()
) -> tuple[ResourceId, ...]:
    result = [descriptor.resource_id("platform") for descriptor in PLATFORM_DESCRIPTORS]
    names = {
        path.stem
        for path in (root / "platform" / "profiles").glob("*.md")
        if path.is_file()
    }
    names.update(
        item.qualifier
        for item in remote
        if item.scope == "platform"
        and item.kind is PlatformResourceKind.PROFILE_PROMPT
        and item.qualifier
    )
    result.extend(
        platform_profile_descriptor(name).resource_id("platform")
        for name in sorted(names)
    )
    return tuple(result)


def descriptors() -> tuple[ResourceDescriptor, ...]:
    return DESCRIPTORS


def publishable_component_names() -> tuple[str, ...]:
    candidates = (*DESCRIPTORS, telephony_descriptor())
    return tuple(
        descriptor.kind.value
        for descriptor in candidates
        if ResourceCapability.PUBLISHABLE in descriptor.capabilities
        or ResourceCapability.PUBLISHABLE_PARTICIPANT in descriptor.capabilities
    )
