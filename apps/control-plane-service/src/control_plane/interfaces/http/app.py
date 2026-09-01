from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from control_plane import SERVICE_NAME
from control_plane.application.components import ComponentService
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentScope,
    PlatformScope,
    ProfileScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    ComponentError,
    InvalidComponentValue,
    ScopeNotAllowed,
    UnknownComponentKind,
    UnsupportedSchemaVersion,
)
from control_plane.runtime.lifecycle import ServiceLifecycle


class SaveDraftRequest(BaseModel):
    value: dict[str, Any]
    schema_version: int = Field(ge=1)
    expected_draft_version: int | None
    expected_active_revision_id: UUID | None
    actor: str = Field(min_length=1)


class PublishRequest(BaseModel):
    expected_draft_version: int
    actor: str = Field(min_length=1)


class RollbackRequest(BaseModel):
    revision_number: int = Field(ge=1)
    actor: str = Field(min_length=1)


def create_http_app(
    lifecycle: ServiceLifecycle, components: ComponentService | None = None
) -> FastAPI:
    app = FastAPI(title="Agentic Backend Control Plane", lifespan=lifecycle.lifespan)
    app.state.lifecycle = lifecycle
    app.state.components = components

    @app.exception_handler(ComponentError)
    async def component_error(_request: Request, exc: ComponentError) -> JSONResponse:
        if isinstance(
            exc, (InvalidComponentValue, ScopeNotAllowed, UnsupportedSchemaVersion)
        ):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        elif isinstance(exc, UnknownComponentKind) or exc.code.endswith("not_found"):
            code = status.HTTP_404_NOT_FOUND
        else:
            code = status.HTTP_409_CONFLICT
        return JSONResponse(
            status_code=code,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        runtime: ServiceLifecycle = request.app.state.lifecycle
        readiness = await runtime.readiness()
        if readiness.ready:
            return {"status": "ok", "service": SERVICE_NAME}
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unavailable",
                "service": SERVICE_NAME,
                "checks": {
                    "postgres": readiness.postgres,
                    "control_plane_schema": readiness.control_plane_schema,
                    "nats": readiness.nats,
                    "outbox_relay": readiness.outbox_relay,
                },
            },
        )

    if components is not None:
        for prefix in (
            "/v1/scopes/platform",
            "/v1/scopes/tenant/{tenant_id}",
            "/v1/scopes/profile/{profile_key}",
        ):
            app.include_router(_component_router(), prefix=prefix)
    return app


def _address(request: Request, kind: str) -> ComponentAddress:
    scope: ComponentScope
    if tenant_id := request.path_params.get("tenant_id"):
        scope = TenantScope(tenant_id)
    elif profile_key := request.path_params.get("profile_key"):
        scope = ProfileScope(profile_key)
    else:
        scope = PlatformScope()
    return ComponentAddress(ComponentKind(kind), scope)


def _service(request: Request) -> ComponentService:
    return request.app.state.components


def _component_router() -> APIRouter:
    router = APIRouter()

    @router.get("/components/{kind}")
    async def get_component(request: Request, kind: str) -> Any:
        return jsonable_encoder(
            await _service(request).get_component(_address(request, kind))
        )

    @router.get("/components/{kind}/draft")
    async def get_draft(request: Request, kind: str) -> Any:
        return jsonable_encoder(
            await _service(request).get_draft(_address(request, kind))
        )

    @router.put("/components/{kind}/draft")
    async def save_draft(request: Request, kind: str, body: SaveDraftRequest) -> Any:
        return jsonable_encoder(
            await _service(request).save_draft(
                _address(request, kind),
                body.value,
                body.schema_version,
                body.expected_draft_version,
                body.expected_active_revision_id,
                body.actor,
            )
        )

    @router.delete("/components/{kind}/draft", status_code=status.HTTP_204_NO_CONTENT)
    async def discard_draft(
        request: Request, kind: str, expected_draft_version: int = Query(ge=1)
    ) -> None:
        await _service(request).discard_draft(
            _address(request, kind), expected_draft_version
        )

    @router.post("/components/{kind}/publish")
    async def publish(request: Request, kind: str, body: PublishRequest) -> Any:
        return jsonable_encoder(
            await _service(request).publish_draft(
                _address(request, kind), body.expected_draft_version, body.actor
            )
        )

    @router.get("/components/{kind}/active")
    async def active(request: Request, kind: str) -> Any:
        return jsonable_encoder(
            await _service(request).get_active(_address(request, kind))
        )

    @router.get("/components/{kind}/revisions")
    async def revisions(
        request: Request, kind: str, limit: int = Query(100, ge=1, le=500)
    ) -> Any:
        return jsonable_encoder(
            await _service(request).list_revisions(_address(request, kind), limit)
        )

    @router.get("/components/{kind}/revisions/{revision_number}")
    async def revision(request: Request, kind: str, revision_number: int) -> Any:
        return jsonable_encoder(
            await _service(request).get_revision(
                _address(request, kind), revision_number
            )
        )

    @router.post("/components/{kind}/rollback")
    async def rollback(request: Request, kind: str, body: RollbackRequest) -> Any:
        return jsonable_encoder(
            await _service(request).rollback(
                _address(request, kind), body.revision_number, body.actor
            )
        )

    return router
