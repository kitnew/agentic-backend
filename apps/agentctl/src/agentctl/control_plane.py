from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self
from uuid import UUID

import httpx

from agentctl.commands.errors import CommandError
from agentctl.settings import Settings


@dataclass(frozen=True, slots=True)
class ComponentState:
    working: dict[str, Any] | None
    active: dict[str, Any] | None
    draft_version: int | None
    active_revision_id: UUID | None = None


class ControlPlaneClient:
    """Typed management boundary for agentctl; commands do not build CP URLs."""

    def __init__(self, settings: Settings) -> None:
        if not settings.control_plane_url or not settings.control_plane_token:
            raise CommandError(
                "AGENTCTL_CONTROL_PLANE_URL and AGENTCTL_CONTROL_PLANE_TOKEN are required",
                2,
            )
        self._client = httpx.Client(
            base_url=settings.control_plane_url,
            headers={"Authorization": f"Bearer {settings.control_plane_token}"},
            timeout=httpx.Timeout(10.0),
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise CommandError(
                f"Control Plane API request failed ({response.status_code}): "
                f"{response.text[:500]}",
                3,
            )
        if not response.content:
            return None
        return response.json()

    @staticmethod
    def _scope(tenant_id: UUID | str | None, profile_key: str | None) -> str:
        if tenant_id is not None:
            return f"/v1/scopes/tenant/{tenant_id}"
        if profile_key is not None:
            return f"/v1/scopes/profile/{profile_key}"
        return "/v1/scopes/platform"

    def get_component(
        self, kind: str, *, tenant_id: UUID | str | None = None, profile_key: str | None = None
    ) -> ComponentState:
        scope = self._scope(tenant_id, profile_key)
        try:
            snapshot = self._request("GET", f"{scope}/components/{kind}")
        except CommandError as error:
            if "(404)" not in str(error) or "component_not_found" not in str(error):
                raise
            return ComponentState(None, None, None)
        draft = snapshot.get("draft")
        active = snapshot.get("active")
        working = draft or active
        return ComponentState(
            None if working is None else working["value"],
            None if active is None else active["value"],
            None if draft is None else draft["version"],
            None if active is None else UUID(str(active["revision_id"])),
        )

    def save_component(
        self,
        kind: str,
        value: dict[str, Any],
        *,
        schema_version: int = 1,
        draft_version: int | None = None,
        active_revision_id: UUID | None = None,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(tenant_id, profile_key)
        return self._request(
            "PUT",
            f"{scope}/components/{kind}/draft",
            json={
                "value": value,
                "schema_version": schema_version,
                "expected_draft_version": draft_version,
                "expected_active_revision_id": (
                    None if active_revision_id is None else str(active_revision_id)
                ),
            },
        )

    def discard_component(
        self,
        kind: str,
        draft_version: int,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> None:
        scope = self._scope(tenant_id, profile_key)
        self._request(
            "DELETE",
            f"{scope}/components/{kind}/draft?expected_draft_version={draft_version}",
        )

    def publish_component(
        self,
        kind: str,
        draft_version: int,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(tenant_id, profile_key)
        return self._request(
            "POST",
            f"{scope}/components/{kind}/publish",
            json={"expected_draft_version": draft_version},
        )

    def revisions(
        self,
        kind: str,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
        limit: int = 100,
    ) -> Any:
        scope = self._scope(tenant_id, profile_key)
        return self._request("GET", f"{scope}/components/{kind}/revisions?limit={limit}")

    def revision(
        self,
        kind: str,
        revision_number: int,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(tenant_id, profile_key)
        return self._request("GET", f"{scope}/components/{kind}/revisions/{revision_number}")

    def rollback(
        self,
        kind: str,
        revision_number: int,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(tenant_id, profile_key)
        return self._request(
            "POST",
            f"{scope}/components/{kind}/rollback",
            json={"revision_number": revision_number},
        )

    def managed(self, method: str, resource: str, **kwargs: Any) -> Any:
        return self._request(method, f"/v1/managed-resources/{resource}", **kwargs)
