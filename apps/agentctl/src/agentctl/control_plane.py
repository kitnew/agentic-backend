from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from json import dumps
from typing import Any, Self
from uuid import UUID, uuid4

import httpx
from admin_client.control_plane.client import AuthenticatedClient

from agentctl.commands.errors import CommandError
from agentctl.settings import Settings


@dataclass(frozen=True, slots=True)
class ComponentState:
    working: dict[str, Any] | None
    active: dict[str, Any] | None
    write_etag: str | None


@dataclass(frozen=True, slots=True)
class ConfigurationState:
    value: dict[str, Any]
    write_etag: str


class ControlPlaneClient:
    """Typed management boundary for agentctl; commands do not build CP URLs."""

    def __init__(self, settings: Settings) -> None:
        if not settings.control_plane_url or not settings.control_plane_token:
            raise CommandError(
                "AGENTCTL_CONTROL_PLANE_URL and AGENTCTL_CONTROL_PLANE_TOKEN are required",
                2,
            )
        self._generated = AuthenticatedClient(
            base_url=settings.control_plane_url,
            token=settings.control_plane_token,
            timeout=httpx.Timeout(10.0),
        )
        self._client = self._generated.get_httpx_client()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _response(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            raise CommandError(
                _format_error(response),
                3,
                status_code=response.status_code,
            )
        return response

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self._response(method, path, **kwargs)
        if not response.content:
            return None
        return response.json()

    @staticmethod
    def _scope(kind: str, tenant_id: UUID | str | None, profile_key: str | None) -> str:
        if tenant_id is not None:
            return f"/management/v1/tenants/{tenant_id}"
        if profile_key is not None:
            return f"/management/v1/platform/profiles/{profile_key}"
        if kind in {
            "STTDefaults",
            "LLMDefaults",
            "TTSDefaults",
            "RealtimeDefaults",
            "Policies",
        }:
            return "/management/v1/system"
        return "/management/v1/platform"

    @staticmethod
    def _mutation_headers(
        etag: str | None = None,
        *,
        if_none_match: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, str]:
        return {
            "Idempotency-Key": idempotency_key or str(uuid4()),
            **(
                {"If-None-Match": "*"}
                if if_none_match
                else {"If-Match": etag}
                if etag
                else {}
            ),
        }

    def get_component(
        self,
        kind: str,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> ComponentState:
        scope = self._scope(kind, tenant_id, profile_key)
        try:
            response = self._response("GET", f"{scope}/components/{kind}")
        except CommandError as error:
            if error.status_code != 404 or "component_not_found" not in str(error):
                raise
            return ComponentState(None, None, None)
        snapshot = response.json()
        draft = snapshot.get("draft")
        active = snapshot.get("active")
        working = draft or active
        return ComponentState(
            None if working is None else working["value"],
            None if active is None else active["value"],
            response.headers.get("etag"),
        )

    def save_component(
        self,
        kind: str,
        value: dict[str, Any],
        *,
        etag: str | None = None,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(kind, tenant_id, profile_key)
        if scope == "/management/v1/system":
            return self._request(
                "PUT",
                f"{scope}/components/{kind}",
                json={"value": value},
                headers=self._mutation_headers(etag),
            )
        return self._request(
            "PUT",
            f"{scope}/components/{kind}/draft",
            json={"value": value},
            headers={"If-Match": etag} if etag else {},
        )

    def discard_component(
        self,
        kind: str,
        etag: str,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> None:
        scope = self._scope(kind, tenant_id, profile_key)
        self._request(
            "DELETE",
            f"{scope}/components/{kind}/draft",
            headers={"If-Match": etag},
        )

    def publish_component(
        self,
        kind: str,
        etag: str,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(kind, tenant_id, profile_key)
        return self._request(
            "POST",
            f"{scope}/components/{kind}/publish",
            headers=self._mutation_headers(etag),
        )

    def revisions(
        self,
        kind: str,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
        limit: int = 100,
    ) -> Any:
        scope = self._scope(kind, tenant_id, profile_key)
        return self._request(
            "GET", f"{scope}/components/{kind}/revisions?limit={limit}"
        )

    def revision(
        self,
        kind: str,
        revision_number: int,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(kind, tenant_id, profile_key)
        return self._request(
            "GET", f"{scope}/components/{kind}/revisions/{revision_number}"
        )

    def rollback(
        self,
        kind: str,
        revision_number: int,
        *,
        tenant_id: UUID | str | None = None,
        profile_key: str | None = None,
    ) -> Any:
        scope = self._scope(kind, tenant_id, profile_key)
        etag = self.get_component(
            kind, tenant_id=tenant_id, profile_key=profile_key
        ).write_etag
        return self._request(
            "POST",
            f"{scope}/components/{kind}/rollback",
            json={"revision_number": revision_number},
            headers=self._mutation_headers(etag),
        )

    def management(self, method: str, path: str, **kwargs: Any) -> Any:
        return self._request(method, f"/management/v1/{path.lstrip('/')}", **kwargs)

    def management_mutation(
        self,
        method: str,
        path: str,
        *,
        etag: str | None = None,
        if_none_match: bool = False,
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> Any:
        return self.management(
            method,
            path,
            headers=self._mutation_headers(
                etag,
                if_none_match=if_none_match,
                idempotency_key=idempotency_key,
            ),
            **kwargs,
        )

    def management_etag(self, path: str) -> str:
        response = self._response("GET", f"/management/v1/{path.lstrip('/')}")
        etag = response.headers.get("etag")
        if not etag:
            raise CommandError("Control Plane response did not include ETag", 3)
        return etag

    @staticmethod
    def _configuration_path(scope: str, tenant_id: str | None = None) -> str:
        if scope == "tenant":
            if not tenant_id:
                raise CommandError("tenant id is required", 2)
            return f"tenants/{tenant_id}/configuration"
        if scope not in {"system", "platform"}:
            raise CommandError(f"unsupported configuration scope: {scope}", 2)
        return f"{scope}/configuration"

    def get_configuration_optional(
        self, scope: str, tenant_id: str | None = None
    ) -> ConfigurationState | None:
        path = self._configuration_path(scope, tenant_id)
        try:
            response = self._response("GET", f"/management/v1/{path}")
        except CommandError as error:
            if error.status_code == 404:
                return None
            raise
        etag = response.headers.get("etag")
        if not etag:
            raise CommandError("Control Plane response did not include ETag", 3)
        return ConfigurationState(response.json(), etag)

    def get_configuration(
        self, scope: str, tenant_id: str | None = None
    ) -> ConfigurationState:
        state = self.get_configuration_optional(scope, tenant_id)
        if state is None:
            raise CommandError(f"{scope} configuration is not initialized", 3)
        return state

    def plan_configuration(
        self, scope: str, value: dict[str, Any], tenant_id: str | None = None
    ) -> Any:
        path = self._configuration_path(scope, tenant_id)
        return self.management("POST", f"{path}/plan", json=value)

    def apply_configuration(
        self,
        scope: str,
        value: dict[str, Any],
        etag: str | None = None,
        tenant_id: str | None = None,
        *,
        if_none_match: bool = False,
        idempotency_key: str | None = None,
    ) -> Any:
        path = self._configuration_path(scope, tenant_id)
        return self.management_mutation(
            "PUT",
            path,
            etag=etag,
            if_none_match=if_none_match,
            idempotency_key=idempotency_key,
            json=value,
        )

    def publish_configuration(
        self, scope: str, etag: str, tenant_id: str | None = None
    ) -> Any:
        path = f"{self._configuration_path(scope, tenant_id)}/publish"
        return self.management_mutation("POST", path, etag=etag)


def _format_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    try:
        phrase = HTTPStatus(response.status_code).phrase
    except ValueError:
        phrase = "HTTP error"
    if not isinstance(payload, dict) or not isinstance(payload.get("code"), str):
        return (
            f"Control Plane API request failed ({response.status_code} {phrase}): "
            f"{response.text[:500]}"
        )
    lines = [
        (
            f"Control Plane API request failed ({response.status_code} {phrase}): "
            f"{payload['code']}: {payload.get('message', 'request failed')}"
        )
    ]
    for issue in payload.get("issues") or []:
        if isinstance(issue, dict):
            lines.append(
                f"  {issue.get('path', '<root>')}: {issue.get('code', 'invalid')}: "
                f"{issue.get('message', 'invalid value')}"
            )
    if payload.get("details") is not None:
        lines.append(f"  details: {dumps(payload['details'], sort_keys=True)}")
    if payload.get("request_id"):
        lines.append(f"  request_id: {payload['request_id']}")
    return "\n".join(lines)
