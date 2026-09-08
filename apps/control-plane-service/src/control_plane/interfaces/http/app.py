from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool

from control_plane import SERVICE_NAME
from control_plane.application.command_support import IdempotencyKeyReused
from control_plane.application.components import ComponentService
from control_plane.application.credentials import CredentialService
from control_plane.application.execution_materialization import (
    ExecutionMaterializationService,
    RuntimeSecretSlot,
)
from control_plane.application.live_components import (
    LiveComponentPreconditionFailed,
    LiveComponentService,
)
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.application.providers import ProviderService
from control_plane.application.runtime_materialization import (
    ExecutionSnapshotService,
)
from control_plane.application.runtime_resolver import RuntimeResolver
from control_plane.application.system_configuration import (
    SystemConfiguration,
    SystemConfigurationApplyResult,
    SystemConfigurationDesired,
    SystemConfigurationError,
    SystemConfigurationNotFound,
    SystemConfigurationPlan,
    SystemConfigurationPreconditionFailed,
    SystemConfigurationService,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentKind,
    ComponentScope,
    PlatformScope,
    ProfileScope,
    SystemScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    ComponentError,
    InvalidComponentValue,
    ScopeNotAllowed,
    UnknownComponentKind,
    UnsupportedSchemaVersion,
)
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceError,
    ManagedResourceNotFound,
    ManagedResourcePreconditionFailed,
)
from control_plane.domain.managed_resources import (
    CredentialRef,
    CredentialScope,
    DeploymentKind,
    HandoffDestination,
    HandoffDestinationRef,
    IntegrationConnection,
    IntegrationConnectionRef,
    LLMCapabilities,
    ModelDeployment,
    ModelDeploymentRef,
    PhoneNumberAssignment,
    PhoneNumberAssignmentRef,
    PlatformCredentialScope,
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
    TenantCredentialScope,
    TTSCapabilities,
)
from control_plane.domain.runtime_resolution import RuntimeResolutionError
from control_plane.interfaces.http.service_auth import (
    ManagementPrincipal,
    ServicePrincipal,
    require_management_permission,
    require_management_token,
    require_service_scope,
)
from control_plane.runtime.lifecycle import ServiceLifecycle


class SaveDraftRequest(BaseModel):
    value: dict[str, Any]
    schema_version: int = Field(ge=1)
    expected_draft_version: int | None
    expected_active_revision_id: UUID | None


class LiveComponentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: dict[str, Any]


class SystemScopeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["system"]


class SystemLiveComponentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    scope: SystemScopeResponse
    value: dict[str, Any]
    updated_at: datetime
    updated_by: str


class PublishRequest(BaseModel):
    expected_draft_version: int


class RollbackRequest(BaseModel):
    revision_number: int = Field(ge=1)


class PlatformCredentialScopeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["platform"]


class TenantCredentialScopeWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tenant"]
    tenant_id: str = Field(min_length=1, max_length=255)


CredentialScopeWrite = Annotated[
    PlatformCredentialScopeWrite | TenantCredentialScopeWrite,
    Field(discriminator="type"),
]


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: CredentialScopeWrite
    name: str = Field(min_length=1, max_length=255)
    secret: SecretStr = Field(min_length=1)


class CredentialRotate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret: SecretStr = Field(min_length=1)


class CredentialResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    scope: CredentialScopeWrite
    name: str
    status: Literal["active", "revoked"]
    active_secret_version: int = Field(ge=1)


class ProviderConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=255)
    provider_kind: str = Field(min_length=1, max_length=64)
    credential_ref: UUID
    connection_config: dict[str, object]


class ProviderConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_ref: UUID
    connection_config: dict[str, object]


class ProviderConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    key: str
    provider_kind: str
    credential_ref: UUID
    connection_config: dict[str, object]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class GeneratedActorRequest(BaseModel):
    expected_generation: int = Field(ge=1)


class IntegrationConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=255)
    key: str = Field(min_length=1, max_length=255)
    integration_kind: str = "http"
    config: dict[str, object]
    credential_ref: UUID | None = None
    enabled: bool = False


class IntegrationConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict[str, object]
    credential_ref: UUID | None = None
    expected_generation: int = Field(ge=1)


class HandoffDestinationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=255)
    key: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(min_length=1, max_length=64)
    enabled: bool = False


class HandoffDestinationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(min_length=1, max_length=64)
    expected_generation: int = Field(ge=1)


class PhoneNumberAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=255)
    phone_number: str = Field(min_length=1, max_length=64)
    enabled: bool = False


_runtime_secret_auth = Depends(require_service_scope("runtime-secret:materialize"))
_integration_material_auth = Depends(require_service_scope("integration-material:read"))
_snapshot_materialize_auth = Depends(
    require_service_scope("execution-snapshot:materialize")
)
_snapshot_read_auth = Depends(require_service_scope("execution-snapshot:read"))
_handoff_material_auth = Depends(require_service_scope("handoff-material:read"))
_telephony_read_auth = Depends(require_service_scope("telephony:read"))
_credential_read_auth = Depends(require_management_permission("resources:read"))
_credential_write_auth = Depends(require_management_permission("credentials:write"))


class HandoffMaterialRequest(BaseModel):
    destination: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class LLMCapabilitiesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["llm"]
    supports_temperature: StrictBool
    supports_reasoning_effort: StrictBool


class RealtimeCapabilitiesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["realtime"]
    supports_server_vad: StrictBool
    supports_semantic_vad: StrictBool


class STTCapabilitiesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["stt"]
    supports_cascade: StrictBool
    supports_realtime_input_transcription: StrictBool


class TTSCapabilitiesWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tts"]


CapabilitiesWrite = Annotated[
    LLMCapabilitiesWrite
    | RealtimeCapabilitiesWrite
    | STTCapabilitiesWrite
    | TTSCapabilitiesWrite,
    Field(discriminator="kind"),
]


class ModelDeploymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=255)
    connection_ref: UUID
    deployment_kind: DeploymentKind
    deployment_config: dict[str, object]
    capabilities: CapabilitiesWrite


class ModelDeploymentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_ref: UUID
    deployment_config: dict[str, object]
    capabilities: CapabilitiesWrite


class ModelDeploymentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    key: str
    connection_ref: UUID
    deployment_kind: DeploymentKind
    deployment_config: dict[str, object]
    capabilities: CapabilitiesWrite
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ProviderValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    usable: bool
    code: str | None = None
    message: str | None = None


def create_http_app(
    lifecycle: ServiceLifecycle,
    components: ComponentService | None = None,
    managed_resources: ManagedResourceService | None = None,
    runtime_resolver: RuntimeResolver | None = None,
    runtime_materialization: ExecutionSnapshotService | None = None,
    execution_materialization: ExecutionMaterializationService | None = None,
    credentials: CredentialService | None = None,
    providers: ProviderService | None = None,
    system_configuration: SystemConfigurationService | None = None,
    live_components: LiveComponentService | None = None,
) -> FastAPI:
    app = FastAPI(title="Agentic Backend Control Plane", lifespan=lifecycle.lifespan)
    app.state.settings = None
    app.state.lifecycle = lifecycle
    app.state.components = components
    app.state.managed_resources = managed_resources
    app.state.runtime_resolver = runtime_resolver
    app.state.runtime_materialization = runtime_materialization
    app.state.execution_materialization = execution_materialization
    app.state.credentials = credentials
    app.state.providers = providers
    app.state.system_configuration = system_configuration
    app.state.live_components = live_components

    @app.middleware("http")
    async def management_boundary(request: Request, call_next):
        target = request.url.path.startswith("/management/v1/")
        request.state.request_id = str(uuid4())
        if target or (
            request.url.path.startswith("/v1/")
            and not request.url.path.startswith("/v1/runtime/resolve")
        ):
            try:
                request.state.management_principal = require_management_token(request)
            except HTTPException as error:
                if target:
                    return _management_error(
                        request,
                        error.status_code,
                        "unauthenticated",
                        str(error.detail),
                        headers=error.headers,
                    )
                return JSONResponse(
                    {"detail": error.detail},
                    status_code=error.status_code,
                    headers=error.headers,
                )
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if request.url.path.startswith("/management/v1/"):
            code = (
                "permission_denied"
                if exc.status_code == status.HTTP_403_FORBIDDEN
                else "precondition_required"
                if exc.status_code == status.HTTP_428_PRECONDITION_REQUIRED
                else "invalid_request"
            )
            return _management_error(
                request, exc.status_code, code, str(exc.detail), headers=exc.headers
            )
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if request.url.path.startswith("/management/v1/"):
            issues = [
                {
                    "location": ".".join(str(item) for item in error["loc"]),
                    "message": error["msg"],
                }
                for error in exc.errors()
            ]
            return _management_error(
                request,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "invalid_request",
                "request validation failed",
                issues=issues,
            )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(IdempotencyKeyReused)
    async def idempotency_error(
        request: Request, exc: IdempotencyKeyReused
    ) -> JSONResponse:
        return _management_error(request, status.HTTP_409_CONFLICT, exc.code, str(exc))

    @app.exception_handler(ComponentError)
    async def component_error(request: Request, exc: ComponentError) -> JSONResponse:
        if isinstance(
            exc, (InvalidComponentValue, ScopeNotAllowed, UnsupportedSchemaVersion)
        ):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        elif isinstance(exc, LiveComponentPreconditionFailed):
            code = status.HTTP_412_PRECONDITION_FAILED
        elif isinstance(exc, UnknownComponentKind) or exc.code.endswith("not_found"):
            code = status.HTTP_404_NOT_FOUND
        else:
            code = status.HTTP_409_CONFLICT
        if request.url.path.startswith("/management/v1/"):
            return _management_error(request, code, exc.code, str(exc))
        return JSONResponse(
            status_code=code,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(ManagedResourceError)
    async def managed_resource_error(
        request: Request, exc: ManagedResourceError
    ) -> JSONResponse:
        if isinstance(exc, InvalidManagedResource):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        elif isinstance(exc, ManagedResourceNotFound):
            code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, ManagedResourcePreconditionFailed):
            code = status.HTTP_412_PRECONDITION_FAILED
        else:
            code = status.HTTP_409_CONFLICT
        if request.url.path.startswith("/management/v1/"):
            return _management_error(request, code, exc.code, str(exc))
        return JSONResponse(
            status_code=code,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(RuntimeResolutionError)
    async def runtime_resolution_error(
        _request: Request, exc: RuntimeResolutionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=jsonable_encoder(
                {
                    "detail": {
                        "code": "runtime_resolution_failed",
                        "reason": exc.reason,
                        "details": exc.details,
                        "attempts": exc.attempts,
                    }
                }
            ),
        )

    @app.exception_handler(SystemConfigurationError)
    async def system_configuration_error(
        request: Request, exc: SystemConfigurationError
    ) -> JSONResponse:
        code = (
            status.HTTP_404_NOT_FOUND
            if isinstance(exc, SystemConfigurationNotFound)
            else status.HTTP_412_PRECONDITION_FAILED
            if isinstance(exc, SystemConfigurationPreconditionFailed)
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        return _management_error(request, code, exc.code, str(exc))

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
    if managed_resources is not None:
        app.include_router(_managed_resource_router(), prefix="/v1/managed-resources")
    if credentials is not None:
        app.include_router(_credential_router(), prefix="/management/v1")
    if providers is not None:
        app.include_router(_provider_router(), prefix="/management/v1/providers")
    if system_configuration is not None:
        app.include_router(_system_configuration_router(), prefix="/management/v1")
    if live_components is not None:
        app.include_router(_system_live_component_router(), prefix="/management/v1")
    if runtime_resolver is not None:

        @app.get("/v1/runtime/resolve/tenant/{tenant_id}")
        async def resolve_runtime(request: Request, tenant_id: str) -> Any:
            resolver: RuntimeResolver = request.app.state.runtime_resolver
            return jsonable_encoder(await resolver.resolve_runtime(tenant_id))

    if runtime_materialization is not None:

        @app.post(
            "/v1/execution-snapshots/materialize/tenant/{tenant_id}",
            status_code=status.HTTP_201_CREATED,
        )
        async def materialize_execution_snapshot(
            request: Request, tenant_id: str
        ) -> Any:
            service: ExecutionSnapshotService = (
                request.app.state.runtime_materialization
            )
            return jsonable_encoder(await service.materialize(tenant_id))

        @app.get("/v1/execution-snapshots/{snapshot_id}")
        async def get_execution_snapshot(request: Request, snapshot_id: UUID) -> Any:
            service: ExecutionSnapshotService = (
                request.app.state.runtime_materialization
            )
            snapshot = await service.get_snapshot(snapshot_id)
            if snapshot is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return jsonable_encoder(snapshot)

        @app.post(
            "/internal/v1/execution-snapshots/materialize/tenant/{tenant_id}",
            status_code=status.HTTP_201_CREATED,
        )
        async def materialize_internal(
            request: Request,
            tenant_id: str,
            _principal: ServicePrincipal = _snapshot_materialize_auth,
        ) -> Any:
            return jsonable_encoder(
                await request.app.state.runtime_materialization.materialize(tenant_id)
            )

        @app.get("/internal/v1/execution-snapshots/{snapshot_id}")
        async def read_internal(
            request: Request,
            snapshot_id: UUID,
            _principal: ServicePrincipal = _snapshot_read_auth,
        ) -> Any:
            snapshot = await request.app.state.runtime_materialization.get_snapshot(
                snapshot_id
            )
            if snapshot is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return jsonable_encoder(snapshot)

    if execution_materialization is not None:

        @app.post("/internal/v1/execution-snapshots/{snapshot_id}/secrets/{slot}")
        async def materialize_runtime_secret(
            request: Request,
            snapshot_id: UUID,
            slot: RuntimeSecretSlot,
            _principal: ServicePrincipal = _runtime_secret_auth,
        ) -> JSONResponse:
            service: ExecutionMaterializationService = (
                request.app.state.execution_materialization
            )
            material = await service.runtime_secret(snapshot_id, slot)
            return JSONResponse(
                jsonable_encoder(_runtime_secret_response(material)),
                headers=_secret_headers(),
            )

    if managed_resources is not None:

        @app.get("/internal/v1/telephony/phone-number-assignments/resolve")
        async def resolve_phone_assignment(
            request: Request,
            phone_number: str = Query(...),
            _principal: ServicePrincipal = _telephony_read_auth,
        ) -> Any:
            try:
                from control_plane.domain.managed_resources import normalize_e164

                phone_number = normalize_e164(phone_number)
            except ValueError as error:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
            assignments = await request.app.state.managed_resources.list_phone_number_assignments()
            assignment = next(
                (
                    item
                    for item in assignments
                    if item.enabled and item.phone_number == phone_number
                ),
                None,
            )
            if assignment is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            return {
                "assignment_id": assignment.ref.value,
                "tenant_id": assignment.tenant_id,
                "phone_number": assignment.phone_number,
                "generation": assignment.generation,
            }

        @app.get("/internal/v1/telephony/phone-number-assignments")
        async def list_enabled_phone_assignments(
            request: Request,
            _principal: ServicePrincipal = _telephony_read_auth,
        ) -> list[dict[str, Any]]:
            assignments = await request.app.state.managed_resources.list_phone_number_assignments()
            return [
                {
                    "assignment_id": item.ref.value,
                    "tenant_id": item.tenant_id,
                    "phone_number": item.phone_number,
                    "generation": item.generation,
                }
                for item in assignments
                if item.enabled
            ]

        @app.post(
            "/internal/v1/tenants/{tenant_id}/integration-connections/{connection_id}/execution-material"
        )
        async def materialize_integration_execution(
            request: Request,
            tenant_id: str,
            connection_id: UUID,
            _principal: ServicePrincipal = _integration_material_auth,
        ) -> JSONResponse:
            service: ExecutionMaterializationService = (
                request.app.state.execution_materialization
            )
            material = await service.integration_material(tenant_id, connection_id)
            return JSONResponse(
                jsonable_encoder(_integration_material_response(material)),
                headers=_secret_headers(),
            )

        @app.post("/internal/v1/execution-snapshots/{snapshot_id}/handoff-material")
        async def handoff_material(
            request: Request,
            snapshot_id: UUID,
            body: HandoffMaterialRequest,
            _principal: ServicePrincipal = _handoff_material_auth,
        ) -> JSONResponse:
            snapshot = await request.app.state.runtime_materialization.get_snapshot(
                snapshot_id
            )
            if snapshot is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            destinations = snapshot.execution.get("handoff", [])
            selected = next(
                (
                    item
                    for item in destinations
                    if isinstance(item, dict) and item.get("key") == body.destination
                ),
                None,
            )
            if not isinstance(selected, dict) or not selected.get("ref"):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            if request.app.state.managed_resources is None:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
            destination = (
                await request.app.state.managed_resources.get_handoff_destination(
                    HandoffDestinationRef(UUID(str(selected["ref"])))
                )
            )
            if destination.tenant_id != snapshot.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            if not destination.enabled:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT)
            return JSONResponse(
                {
                    "snapshot_id": snapshot_id,
                    "destination": body.destination,
                    "generation": destination.generation,
                    "phone_number": destination.phone_number,
                },
                headers=_secret_headers(),
            )

    return app


def _system_configuration_router() -> APIRouter:
    router = APIRouter()
    read_auth = Depends(require_management_permission("configuration:read"))
    write_auth = Depends(require_management_permission("configuration:write"))

    @router.get("/system/configuration", response_model=SystemConfiguration)
    async def get_system_configuration(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> JSONResponse:
        service = request.app.state.system_configuration
        value = await service.get()
        return JSONResponse(
            jsonable_encoder(value),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.post("/system/configuration/plan", response_model=SystemConfigurationPlan)
    async def plan_system_configuration(
        request: Request,
        body: SystemConfigurationDesired,
        _principal: ManagementPrincipal = write_auth,
    ) -> Any:
        return jsonable_encoder(await request.app.state.system_configuration.plan(body))

    @router.put("/system/configuration", response_model=SystemConfigurationApplyResult)
    async def apply_system_configuration(
        request: Request,
        body: SystemConfigurationDesired,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = request.app.state.system_configuration
        result = await service.apply(
            body, expected_token, principal.subject, idempotency_key
        )
        return JSONResponse(
            jsonable_encoder(result),
            headers={"ETag": f'"{service.concurrency_token(result.configuration)}"'},
        )

    return router


def _system_live_component_router() -> APIRouter:
    router = APIRouter()
    read_auth = Depends(require_management_permission("configuration:read"))
    write_auth = Depends(require_management_permission("configuration:write"))

    @router.get("/system/components/{kind}", response_model=SystemLiveComponentResponse)
    async def get_live_component(
        request: Request,
        kind: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = request.app.state.live_components
        state = await service.get(ComponentAddress(ComponentKind(kind), SystemScope()))
        return JSONResponse(
            jsonable_encoder(
                {
                    "kind": str(state.address.kind),
                    "scope": {"type": "system"},
                    "value": state.value,
                    "updated_at": state.updated_at,
                    "updated_by": state.updated_by,
                }
            ),
            headers={"ETag": f'"{service.concurrency_token(state)}"'},
        )

    @router.put("/system/components/{kind}", response_model=SystemLiveComponentResponse)
    async def set_live_component(
        request: Request,
        kind: str,
        body: LiveComponentWrite,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = request.app.state.live_components
        state = await service.set(
            ComponentAddress(ComponentKind(kind), SystemScope()),
            body.value,
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(
                {
                    "kind": str(state.address.kind),
                    "scope": {"type": "system"},
                    "value": state.value,
                    "updated_at": state.updated_at,
                    "updated_by": state.updated_by,
                }
            ),
            headers={"ETag": f'"{service.concurrency_token(state)}"'},
        )

    return router


def _secret_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }


def _management_error(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    issues: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    content: dict[str, object] = {
        "code": code,
        "message": message,
        "request_id": request.state.request_id,
    }
    if issues:
        content["issues"] = issues
    return JSONResponse(content, status_code=status_code, headers=headers)


def _runtime_secret_response(value: object) -> dict[str, object]:
    from control_plane.application.execution_materialization import (
        RuntimeSecretMaterial,
    )

    assert isinstance(value, RuntimeSecretMaterial)
    return {
        "snapshot_id": value.snapshot_id,
        "slot": value.slot,
        "secret": value.secret,
        "credential_ref": value.credential_ref,
        "credential_generation": value.credential_generation,
        "credential_version_id": value.credential_version_id,
        "credential_version_number": value.credential_version_number,
        "provider_connection_ref": value.provider_connection_ref,
        "provider_connection_generation": value.provider_connection_generation,
        "model_deployment_ref": value.model_deployment_ref,
        "model_deployment_generation": value.model_deployment_generation,
    }


def _integration_material_response(value: object) -> dict[str, object]:
    from control_plane.application.execution_materialization import (
        IntegrationExecutionMaterial,
    )

    assert isinstance(value, IntegrationExecutionMaterial)
    return {
        "tenant_id": value.tenant_id,
        "integration_connection_id": value.integration_connection_id,
        "integration_connection_generation": value.integration_connection_generation,
        "integration_kind": value.integration_kind,
        "config": value.config,
        "secret": value.secret,
        "credential_ref": value.credential_ref,
        "credential_generation": value.credential_generation,
        "credential_version_id": value.credential_version_id,
        "credential_version_number": value.credential_version_number,
    }


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


def _management_actor(request: Request) -> str:
    principal = request.state.management_principal
    assert isinstance(principal, ManagementPrincipal)
    return principal.subject


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
                body.expected_draft_version,
                body.expected_active_revision_id,
                _management_actor(request),
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
                _address(request, kind),
                body.expected_draft_version,
                _management_actor(request),
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
                _address(request, kind),
                body.revision_number,
                _management_actor(request),
            )
        )

    return router


def _managed(request: Request) -> ManagedResourceService:
    return request.app.state.managed_resources


def _provider(request: Request) -> ProviderService:
    return request.app.state.providers


def _credential(request: Request) -> CredentialService:
    return request.app.state.credentials


def _credential_response(value: object) -> dict[str, object]:
    from control_plane.domain.managed_resources import Credential

    assert isinstance(value, Credential)
    scope = (
        {"type": "tenant", "tenant_id": value.scope.tenant_id}
        if isinstance(value.scope, TenantCredentialScope)
        else {"type": "platform"}
    )
    return {
        "id": value.ref.value,
        "scope": scope,
        "name": value.name,
        "status": value.status,
        "active_secret_version": value.active_secret_version_number,
    }


def _etag(service: CredentialService, value: object) -> str:
    from control_plane.domain.managed_resources import Credential

    assert isinstance(value, Credential)
    return f'"{service.concurrency_token(value)}"'


def _command_headers(request: Request, *, precondition: bool) -> tuple[str, str]:
    idempotency_key = request.headers.get("idempotency-key", "").strip()
    if not idempotency_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Idempotency-Key is required")
    if_match = request.headers.get("if-match", "").strip()
    if precondition and not if_match:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED, "If-Match is required"
        )
    return idempotency_key, if_match.removeprefix("W/").strip('"')


def _connection_response(value: ProviderConnection) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "key": value.key,
        "provider_kind": value.provider_kind,
        "credential_ref": value.credential_ref.value,
        "connection_config": value.connection_config,
        "enabled": value.enabled,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _integration_connection_response(value: IntegrationConnection) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "tenant_id": value.tenant_id,
        "key": value.key,
        "integration_kind": value.integration_kind,
        "config": value.config,
        "credential_ref": value.credential_ref.value if value.credential_ref else None,
        "enabled": value.enabled,
        "generation": value.generation,
        "created_at": value.created_at,
        "created_by": value.created_by,
        "updated_at": value.updated_at,
        "updated_by": value.updated_by,
    }


def _handoff_destination_response(value: HandoffDestination) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "tenant_id": value.tenant_id,
        "key": value.key,
        "description": value.description,
        "phone_number": value.phone_number,
        "enabled": value.enabled,
        "generation": value.generation,
        "created_at": value.created_at,
        "created_by": value.created_by,
        "updated_at": value.updated_at,
        "updated_by": value.updated_by,
    }


def _phone_number_assignment_response(
    value: PhoneNumberAssignment,
) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "tenant_id": value.tenant_id,
        "phone_number": value.phone_number,
        "enabled": value.enabled,
        "generation": value.generation,
        "created_at": value.created_at,
        "created_by": value.created_by,
        "updated_at": value.updated_at,
        "updated_by": value.updated_by,
    }


def _deployment_response(value: ModelDeployment) -> dict[str, object]:
    capabilities = value.capabilities
    capability_payload: dict[str, object] = {"kind": capabilities.kind}
    if isinstance(capabilities, LLMCapabilities):
        capability_payload.update(
            supports_temperature=capabilities.supports_temperature,
            supports_reasoning_effort=capabilities.supports_reasoning_effort,
        )
    elif isinstance(capabilities, RealtimeCapabilities):
        capability_payload.update(
            supports_server_vad=capabilities.supports_server_vad,
            supports_semantic_vad=capabilities.supports_semantic_vad,
        )
    elif isinstance(capabilities, STTCapabilities):
        capability_payload.update(
            supports_cascade=capabilities.supports_cascade,
            supports_realtime_input_transcription=(
                capabilities.supports_realtime_input_transcription
            ),
        )
    return {
        "id": value.ref.value,
        "key": value.key,
        "connection_ref": value.connection_ref.value,
        "deployment_kind": value.deployment_kind,
        "deployment_config": value.deployment_config,
        "capabilities": capability_payload,
        "enabled": value.enabled,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _provider_etag(
    service: ProviderService, value: ProviderConnection | ModelDeployment
) -> str:
    return f'"{service.concurrency_token(value)}"'


def _capabilities(value: CapabilitiesWrite):
    payload = value.model_dump(exclude={"kind"})
    if isinstance(value, LLMCapabilitiesWrite):
        return LLMCapabilities(**payload)
    if isinstance(value, RealtimeCapabilitiesWrite):
        return RealtimeCapabilities(**payload)
    if isinstance(value, STTCapabilitiesWrite):
        return STTCapabilities(**payload)
    return TTSCapabilities()


def _credential_router() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/credentials",
        status_code=status.HTTP_201_CREATED,
        response_model=CredentialResponse,
    )
    async def create_credential(
        request: Request,
        body: CredentialCreate,
        principal: ManagementPrincipal = _credential_write_auth,
    ) -> JSONResponse:
        idempotency_key, _ = _command_headers(request, precondition=False)
        scope = (
            TenantCredentialScope(body.scope.tenant_id)
            if isinstance(body.scope, TenantCredentialScopeWrite)
            else PlatformCredentialScope()
        )
        service = _credential(request)
        value = await service.create(
            scope,
            body.name,
            body.secret.get_secret_value(),
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_credential_response(value)),
            status_code=status.HTTP_201_CREATED,
            headers={"ETag": _etag(service, value)},
        )

    @router.get("/credentials", response_model=list[CredentialResponse])
    async def list_credentials(
        request: Request,
        scope_type: Literal["platform", "tenant"] | None = None,
        tenant_id: str | None = None,
        _principal: ManagementPrincipal = _credential_read_auth,
    ) -> Any:
        scope: CredentialScope | None
        if scope_type is None and tenant_id is None:
            scope = None
        elif scope_type == "platform" and tenant_id is None:
            scope = PlatformCredentialScope()
        elif scope_type == "tenant" and tenant_id:
            scope = TenantCredentialScope(tenant_id)
        else:
            raise InvalidManagedResource("credential scope filter is invalid")
        return jsonable_encoder(
            [
                _credential_response(value)
                for value in await _credential(request).list(scope)
            ]
        )

    @router.get("/credentials/{resource_id}", response_model=CredentialResponse)
    async def get_credential(
        request: Request,
        resource_id: UUID,
        _principal: ManagementPrincipal = _credential_read_auth,
    ) -> JSONResponse:
        service = _credential(request)
        value = await service.get(CredentialRef(resource_id))
        return JSONResponse(
            jsonable_encoder(_credential_response(value)),
            headers={"ETag": _etag(service, value)},
        )

    @router.post("/credentials/{resource_id}/rotate", response_model=CredentialResponse)
    async def rotate_credential(
        request: Request,
        resource_id: UUID,
        body: CredentialRotate,
        principal: ManagementPrincipal = _credential_write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _credential(request)
        value = await service.rotate(
            CredentialRef(resource_id),
            body.secret.get_secret_value(),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_credential_response(value)),
            headers={"ETag": _etag(service, value)},
        )

    @router.post("/credentials/{resource_id}/revoke", response_model=CredentialResponse)
    async def revoke_credential(
        request: Request,
        resource_id: UUID,
        principal: ManagementPrincipal = _credential_write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _credential(request)
        value = await service.revoke(
            CredentialRef(resource_id),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_credential_response(value)),
            headers={"ETag": _etag(service, value)},
        )

    return router


def _provider_router() -> APIRouter:
    router = APIRouter()
    read_auth = Depends(require_management_permission("resources:read"))
    write_auth = Depends(require_management_permission("resources:write"))

    @router.post(
        "/connections",
        status_code=status.HTTP_201_CREATED,
        response_model=ProviderConnectionResponse,
    )
    async def create_connection(
        request: Request,
        body: ProviderConnectionCreate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, _ = _command_headers(request, precondition=False)
        service = _provider(request)
        value = await service.create_connection(
            body.key,
            body.provider_kind,
            CredentialRef(body.credential_ref),
            body.connection_config,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_connection_response(value)),
            status_code=status.HTTP_201_CREATED,
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.get("/connections", response_model=list[ProviderConnectionResponse])
    async def list_connections(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(
            [
                _connection_response(value)
                for value in await _provider(request).list_connections()
            ]
        )

    @router.get("/connections/{resource_id}", response_model=ProviderConnectionResponse)
    async def get_connection(
        request: Request,
        resource_id: UUID,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = _provider(request)
        value = await service.get_connection(ProviderConnectionRef(resource_id))
        return JSONResponse(
            jsonable_encoder(_connection_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.put("/connections/{resource_id}", response_model=ProviderConnectionResponse)
    async def update_connection(
        request: Request,
        resource_id: UUID,
        body: ProviderConnectionUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        value = await service.update_connection(
            ProviderConnectionRef(resource_id),
            CredentialRef(body.credential_ref),
            body.connection_config,
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_connection_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.post(
        "/connections/{resource_id}/enable", response_model=ProviderConnectionResponse
    )
    async def enable_connection(
        request: Request,
        resource_id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await connection_lifecycle(request, resource_id, principal, True)

    @router.post(
        "/connections/{resource_id}/disable", response_model=ProviderConnectionResponse
    )
    async def disable_connection(
        request: Request,
        resource_id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await connection_lifecycle(request, resource_id, principal, False)

    async def connection_lifecycle(
        request: Request,
        resource_id: UUID,
        principal: ManagementPrincipal,
        enabled: bool,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        command = service.enable_connection if enabled else service.disable_connection
        value = await command(
            ProviderConnectionRef(resource_id),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_connection_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.post(
        "/connections/{resource_id}/validate",
        response_model=ProviderValidationResponse,
    )
    async def validate_connection(
        request: Request,
        resource_id: UUID,
        _principal: ManagementPrincipal = write_auth,
    ) -> Any:
        return jsonable_encoder(
            await _provider(request).validate_connection(
                ProviderConnectionRef(resource_id)
            )
        )

    @router.post(
        "/deployments",
        status_code=status.HTTP_201_CREATED,
        response_model=ModelDeploymentResponse,
    )
    async def create_deployment(
        request: Request,
        body: ModelDeploymentCreate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, _ = _command_headers(request, precondition=False)
        service = _provider(request)
        value = await service.create_deployment(
            body.key,
            ProviderConnectionRef(body.connection_ref),
            body.deployment_kind,
            body.deployment_config,
            _capabilities(body.capabilities),
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_deployment_response(value)),
            status_code=status.HTTP_201_CREATED,
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.get("/deployments", response_model=list[ModelDeploymentResponse])
    async def list_deployments(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(
            [
                _deployment_response(value)
                for value in await _provider(request).list_deployments()
            ]
        )

    @router.get("/deployments/{resource_id}", response_model=ModelDeploymentResponse)
    async def get_deployment(
        request: Request,
        resource_id: UUID,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = _provider(request)
        value = await service.get_deployment(ModelDeploymentRef(resource_id))
        return JSONResponse(
            jsonable_encoder(_deployment_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.put("/deployments/{resource_id}", response_model=ModelDeploymentResponse)
    async def update_deployment(
        request: Request,
        resource_id: UUID,
        body: ModelDeploymentUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        value = await service.update_deployment(
            ModelDeploymentRef(resource_id),
            ProviderConnectionRef(body.connection_ref),
            body.deployment_config,
            _capabilities(body.capabilities),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_deployment_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.post(
        "/deployments/{resource_id}/enable", response_model=ModelDeploymentResponse
    )
    async def enable_deployment(
        request: Request,
        resource_id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await deployment_lifecycle(request, resource_id, principal, True)

    @router.post(
        "/deployments/{resource_id}/disable", response_model=ModelDeploymentResponse
    )
    async def disable_deployment(
        request: Request,
        resource_id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await deployment_lifecycle(request, resource_id, principal, False)

    async def deployment_lifecycle(
        request: Request,
        resource_id: UUID,
        principal: ManagementPrincipal,
        enabled: bool,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        command = service.enable_deployment if enabled else service.disable_deployment
        value = await command(
            ModelDeploymentRef(resource_id),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_deployment_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.post(
        "/deployments/{resource_id}/validate",
        response_model=ProviderValidationResponse,
    )
    async def validate_deployment(
        request: Request,
        resource_id: UUID,
        _principal: ManagementPrincipal = write_auth,
    ) -> Any:
        return jsonable_encoder(
            await _provider(request).validate_deployment(
                ModelDeploymentRef(resource_id)
            )
        )

    return router


def _managed_resource_router() -> APIRouter:
    router = APIRouter()

    @router.post("/integration-connections", status_code=status.HTTP_201_CREATED)
    async def create_integration_connection(
        request: Request, body: IntegrationConnectionCreate
    ) -> Any:
        if body.integration_kind != "http":
            raise InvalidManagedResource("only integration_kind=http is supported")
        value = await _managed(request).create_integration_connection(
            body.tenant_id,
            body.key,
            body.config,
            CredentialRef(body.credential_ref) if body.credential_ref else None,
            body.enabled,
            _management_actor(request),
        )
        return jsonable_encoder(_integration_connection_response(value))

    @router.put("/integration-connections/{resource_id}")
    async def update_integration_connection(
        request: Request, resource_id: UUID, body: IntegrationConnectionUpdate
    ) -> Any:
        value = await _managed(request).update_integration_connection(
            IntegrationConnectionRef(resource_id),
            body.config,
            CredentialRef(body.credential_ref) if body.credential_ref else None,
            body.expected_generation,
            _management_actor(request),
        )
        return jsonable_encoder(_integration_connection_response(value))

    @router.post("/integration-connections/{resource_id}/{operation}")
    async def set_integration_connection_enabled(
        request: Request, resource_id: UUID, operation: str, body: GeneratedActorRequest
    ) -> Any:
        if operation not in {"enable", "disable"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        value = await _managed(request).set_integration_connection_enabled(
            IntegrationConnectionRef(resource_id),
            operation == "enable",
            body.expected_generation,
            _management_actor(request),
        )
        return jsonable_encoder(_integration_connection_response(value))

    @router.get("/integration-connections/{resource_id}")
    async def get_integration_connection(request: Request, resource_id: UUID) -> Any:
        return jsonable_encoder(
            _integration_connection_response(
                await _managed(request).get_integration_connection(
                    IntegrationConnectionRef(resource_id)
                )
            )
        )

    @router.get("/integration-connections")
    async def list_integration_connections(
        request: Request, tenant_id: str | None = None
    ) -> Any:
        return jsonable_encoder(
            [
                _integration_connection_response(value)
                for value in await _managed(request).list_integration_connections(
                    tenant_id
                )
            ]
        )

    @router.post("/integration-connections/{resource_id}/validate")
    async def validate_integration_connection(
        request: Request, resource_id: UUID
    ) -> Any:
        connection = await _managed(request).get_integration_connection(
            IntegrationConnectionRef(resource_id)
        )
        if not connection.enabled:
            return {"valid": False, "usable": False, "reason": "disabled"}
        config = connection.config
        headers = dict(config.get("headers", {}))
        authentication = config.get("authentication", {})
        if authentication.get("type") != "none":
            materializer = request.app.state.execution_materialization
            if materializer is None:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE)
            material = await materializer.integration_material(
                connection.tenant_id, resource_id
            )
            header_name = authentication.get("header_name")
            if isinstance(header_name, str):
                headers[header_name] = material.secret
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(5.0), follow_redirects=False
            ) as client:
                response = await client.get(config["endpoint"], headers=headers)
        except (httpx.HTTPError, KeyError) as error:
            return {"valid": False, "usable": False, "reason": type(error).__name__}
        return {
            "valid": True,
            "usable": response.is_success,
            "status_code": response.status_code,
        }

    @router.post("/handoff-destinations", status_code=status.HTTP_201_CREATED)
    async def create_handoff_destination(
        request: Request, body: HandoffDestinationCreate
    ) -> Any:
        value = await _managed(request).create_handoff_destination(
            body.tenant_id,
            body.key,
            body.description,
            body.phone_number,
            body.enabled,
            _management_actor(request),
        )
        return jsonable_encoder(_handoff_destination_response(value))

    @router.put("/handoff-destinations/{resource_id}")
    async def update_handoff_destination(
        request: Request, resource_id: UUID, body: HandoffDestinationUpdate
    ) -> Any:
        value = await _managed(request).update_handoff_destination(
            HandoffDestinationRef(resource_id),
            body.description,
            body.phone_number,
            body.expected_generation,
            _management_actor(request),
        )
        return jsonable_encoder(_handoff_destination_response(value))

    @router.post("/handoff-destinations/{resource_id}/{operation}")
    async def set_handoff_destination_enabled(
        request: Request, resource_id: UUID, operation: str, body: GeneratedActorRequest
    ) -> Any:
        if operation not in {"enable", "disable"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        value = await _managed(request).set_handoff_destination_enabled(
            HandoffDestinationRef(resource_id),
            operation == "enable",
            body.expected_generation,
            _management_actor(request),
        )
        return jsonable_encoder(_handoff_destination_response(value))

    @router.get("/handoff-destinations/{resource_id}")
    async def get_handoff_destination(request: Request, resource_id: UUID) -> Any:
        return jsonable_encoder(
            _handoff_destination_response(
                await _managed(request).get_handoff_destination(
                    HandoffDestinationRef(resource_id)
                )
            )
        )

    @router.get("/handoff-destinations")
    async def list_handoff_destinations(
        request: Request, tenant_id: str | None = None
    ) -> Any:
        return jsonable_encoder(
            [
                _handoff_destination_response(value)
                for value in await _managed(request).list_handoff_destinations(
                    tenant_id
                )
            ]
        )

    @router.post("/phone-number-assignments", status_code=status.HTTP_201_CREATED)
    async def create_phone_number_assignment(
        request: Request, body: PhoneNumberAssignmentCreate
    ) -> Any:
        value = await _managed(request).create_phone_number_assignment(
            body.tenant_id, body.phone_number, body.enabled, _management_actor(request)
        )
        return jsonable_encoder(_phone_number_assignment_response(value))

    @router.post("/phone-number-assignments/{resource_id}/{operation}")
    async def set_phone_number_assignment_enabled(
        request: Request, resource_id: UUID, operation: str, body: GeneratedActorRequest
    ) -> Any:
        if operation not in {"enable", "disable"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        value = await _managed(request).set_phone_number_assignment_enabled(
            PhoneNumberAssignmentRef(resource_id),
            operation == "enable",
            body.expected_generation,
            _management_actor(request),
        )
        return jsonable_encoder(_phone_number_assignment_response(value))

    @router.get("/phone-number-assignments/{resource_id}")
    async def get_phone_number_assignment(request: Request, resource_id: UUID) -> Any:
        return jsonable_encoder(
            _phone_number_assignment_response(
                await _managed(request).get_phone_number_assignment(
                    PhoneNumberAssignmentRef(resource_id)
                )
            )
        )

    @router.get("/phone-number-assignments")
    async def list_phone_number_assignments(
        request: Request, tenant_id: str | None = None
    ) -> Any:
        return jsonable_encoder(
            [
                _phone_number_assignment_response(value)
                for value in await _managed(request).list_phone_number_assignments(
                    tenant_id
                )
            ]
        )

    return router
