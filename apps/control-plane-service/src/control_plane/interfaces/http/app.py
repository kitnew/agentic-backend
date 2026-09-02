from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from control_plane import SERVICE_NAME
from control_plane.application.components import ComponentService
from control_plane.application.execution_materialization import (
    ExecutionMaterializationService,
    RuntimeSecretSlot,
)
from control_plane.application.managed_resources import ManagedResourceService
from control_plane.application.runtime_materialization import (
    ExecutionSnapshotService,
)
from control_plane.application.runtime_resolver import RuntimeResolver
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
from control_plane.domain.managed_resource_errors import (
    InvalidManagedResource,
    ManagedResourceError,
    ManagedResourceNotFound,
)
from control_plane.domain.managed_resources import (
    Credential,
    CredentialRef,
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
    ProviderConnection,
    ProviderConnectionRef,
    RealtimeCapabilities,
    STTCapabilities,
)
from control_plane.domain.runtime_resolution import RuntimeResolutionError
from control_plane.interfaces.http.service_auth import (
    ServicePrincipal,
    require_service_scope,
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


class CredentialWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    secret: SecretStr = Field(min_length=1)
    actor: str = Field(min_length=1, max_length=255)


class CredentialRotate(BaseModel):
    secret: SecretStr = Field(min_length=1)
    actor: str = Field(min_length=1, max_length=255)


class ActorRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=255)


class ProviderConnectionCreate(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    provider_kind: str = Field(min_length=1, max_length=64)
    credential_ref: UUID
    connection_config: dict[str, object]
    enabled: bool = False
    actor: str = Field(min_length=1, max_length=255)


class ProviderConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_ref: UUID
    connection_config: dict[str, object]
    expected_generation: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=255)


class GeneratedActorRequest(ActorRequest):
    expected_generation: int = Field(ge=1)


class IntegrationConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: str = Field(min_length=1, max_length=255)
    key: str = Field(min_length=1, max_length=255)
    integration_kind: str = "http"
    config: dict[str, object]
    credential_ref: UUID | None = None
    enabled: bool = False
    actor: str = Field(min_length=1, max_length=255)


class IntegrationConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict[str, object]
    credential_ref: UUID | None = None
    expected_generation: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=255)


class HandoffDestinationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=255)
    key: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(min_length=1, max_length=64)
    enabled: bool = False
    actor: str = Field(min_length=1, max_length=255)


class HandoffDestinationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(min_length=1, max_length=64)
    expected_generation: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=255)


class PhoneNumberAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=255)
    phone_number: str = Field(min_length=1, max_length=64)
    enabled: bool = False
    actor: str = Field(min_length=1, max_length=255)


_runtime_secret_auth = Depends(require_service_scope("runtime-secret:materialize"))
_integration_material_auth = Depends(require_service_scope("integration-material:read"))
_snapshot_materialize_auth = Depends(require_service_scope("execution-snapshot:materialize"))
_snapshot_read_auth = Depends(require_service_scope("execution-snapshot:read"))
_handoff_material_auth = Depends(require_service_scope("handoff-material:read"))


class HandoffMaterialRequest(BaseModel):
    destination: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")


class LLMCapabilitiesWrite(BaseModel):
    supports_temperature: bool
    supports_reasoning_effort: bool


class RealtimeCapabilitiesWrite(BaseModel):
    supports_server_vad: bool
    supports_semantic_vad: bool


class STTCapabilitiesWrite(BaseModel):
    supports_cascade: bool
    supports_realtime_input_transcription: bool


class ModelDeploymentCreate(BaseModel):
    key: str = Field(min_length=1, max_length=255)
    connection_ref: UUID
    deployment_kind: DeploymentKind
    deployment_config: dict[str, object]
    llm_capabilities: LLMCapabilitiesWrite | None = None
    realtime_capabilities: RealtimeCapabilitiesWrite | None = None
    stt_capabilities: STTCapabilitiesWrite | None = None
    enabled: bool = False
    actor: str = Field(min_length=1, max_length=255)


class ModelDeploymentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_ref: UUID
    deployment_config: dict[str, object]
    llm_capabilities: LLMCapabilitiesWrite | None = None
    realtime_capabilities: RealtimeCapabilitiesWrite | None = None
    stt_capabilities: STTCapabilitiesWrite | None = None
    expected_generation: int = Field(ge=1)
    actor: str = Field(min_length=1, max_length=255)


def create_http_app(
    lifecycle: ServiceLifecycle,
    components: ComponentService | None = None,
    managed_resources: ManagedResourceService | None = None,
    runtime_resolver: RuntimeResolver | None = None,
    runtime_materialization: ExecutionSnapshotService | None = None,
    execution_materialization: ExecutionMaterializationService | None = None,
) -> FastAPI:
    app = FastAPI(title="Agentic Backend Control Plane", lifespan=lifecycle.lifespan)
    app.state.lifecycle = lifecycle
    app.state.components = components
    app.state.managed_resources = managed_resources
    app.state.runtime_resolver = runtime_resolver
    app.state.runtime_materialization = runtime_materialization
    app.state.execution_materialization = execution_materialization

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

    @app.exception_handler(ManagedResourceError)
    async def managed_resource_error(
        _request: Request, exc: ManagedResourceError
    ) -> JSONResponse:
        if isinstance(exc, InvalidManagedResource):
            code = status.HTTP_422_UNPROCESSABLE_CONTENT
        elif isinstance(exc, ManagedResourceNotFound):
            code = status.HTTP_404_NOT_FOUND
        else:
            code = status.HTTP_409_CONFLICT
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
    if managed_resources is not None:
        app.include_router(_managed_resource_router(), prefix="/v1/managed-resources")
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
            snapshot = await request.app.state.runtime_materialization.get_snapshot(snapshot_id)
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

        @app.post(
            "/internal/v1/execution-snapshots/{snapshot_id}/handoff-material"
        )
        async def handoff_material(
            request: Request,
            snapshot_id: UUID,
            body: HandoffMaterialRequest,
            _principal: ServicePrincipal = _handoff_material_auth,
        ) -> JSONResponse:
            snapshot = await request.app.state.runtime_materialization.get_snapshot(snapshot_id)
            if snapshot is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            destinations = snapshot.execution.get("handoff", [])
            selected = next(
                (item for item in destinations
                 if isinstance(item, dict) and item.get("key") == body.destination),
                None,
            )
            if not isinstance(selected, dict) or not selected.get("ref"):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            if request.app.state.managed_resources is None:
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
            destination = await request.app.state.managed_resources.get_handoff_destination(
                HandoffDestinationRef(UUID(str(selected["ref"])))
            )
            if destination.tenant_id != snapshot.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            if not destination.enabled:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT)
            return JSONResponse(
                {"snapshot_id": snapshot_id, "destination": body.destination,
                 "generation": destination.generation, "phone_number": destination.phone_number},
                headers=_secret_headers(),
            )

    return app


def _secret_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }


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


def _managed(request: Request) -> ManagedResourceService:
    return request.app.state.managed_resources


def _credential_response(value: Credential) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "name": value.name,
        "active_version_id": value.active_version_id,
        "active_secret_version_number": value.active_secret_version_number,
        "status": value.status,
        "generation": value.generation,
        "created_at": value.created_at,
        "created_by": value.created_by,
        "revoked_at": value.revoked_at,
        "revoked_by": value.revoked_by,
    }


def _connection_response(value: ProviderConnection) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "key": value.key,
        "provider_kind": value.provider_kind,
        "credential_ref": value.credential_ref.value,
        "connection_config": value.connection_config,
        "enabled": value.enabled,
        "generation": value.generation,
        "created_at": value.created_at,
        "created_by": value.created_by,
        "updated_at": value.updated_at,
        "updated_by": value.updated_by,
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
    return {
        "id": value.ref.value,
        "key": value.key,
        "connection_ref": value.connection_ref.value,
        "deployment_kind": value.deployment_kind,
        "deployment_config": value.deployment_config,
        "llm_capabilities": (
            {
                "supports_temperature": value.llm_capabilities.supports_temperature,
                "supports_reasoning_effort": value.llm_capabilities.supports_reasoning_effort,
            }
            if value.llm_capabilities
            else None
        ),
        "realtime_capabilities": (
            {
                "supports_server_vad": value.realtime_capabilities.supports_server_vad,
                "supports_semantic_vad": value.realtime_capabilities.supports_semantic_vad,
            }
            if value.realtime_capabilities
            else None
        ),
        "stt_capabilities": (
            {
                "supports_cascade": value.stt_capabilities.supports_cascade,
                "supports_realtime_input_transcription": value.stt_capabilities.supports_realtime_input_transcription,
            }
            if value.stt_capabilities
            else None
        ),
        "enabled": value.enabled,
        "generation": value.generation,
        "created_at": value.created_at,
        "created_by": value.created_by,
        "updated_at": value.updated_at,
        "updated_by": value.updated_by,
    }


def _managed_resource_router() -> APIRouter:
    router = APIRouter()

    @router.post("/credentials", status_code=status.HTTP_201_CREATED)
    async def create_credential(request: Request, body: CredentialWrite) -> Any:
        value = await _managed(request).create_credential(
            body.name, body.secret.get_secret_value(), body.actor
        )
        return jsonable_encoder(_credential_response(value))

    @router.post("/credentials/{resource_id}/rotate")
    async def rotate_credential(
        request: Request, resource_id: UUID, body: CredentialRotate
    ) -> Any:
        value = await _managed(request).rotate_credential(
            CredentialRef(resource_id), body.secret.get_secret_value(), body.actor
        )
        return jsonable_encoder(_credential_response(value))

    @router.post("/credentials/{resource_id}/revoke")
    async def revoke_credential(
        request: Request, resource_id: UUID, body: ActorRequest
    ) -> Any:
        value = await _managed(request).revoke_credential(
            CredentialRef(resource_id), body.actor
        )
        return jsonable_encoder(_credential_response(value))

    @router.get("/credentials/{resource_id}")
    async def get_credential(request: Request, resource_id: UUID) -> Any:
        value = await _managed(request).get_credential(CredentialRef(resource_id))
        return jsonable_encoder(_credential_response(value))

    @router.get("/credentials")
    async def list_credentials(request: Request) -> Any:
        return jsonable_encoder(
            [
                _credential_response(value)
                for value in await _managed(request).list_credentials()
            ]
        )

    @router.post("/provider-connections", status_code=status.HTTP_201_CREATED)
    async def create_connection(
        request: Request, body: ProviderConnectionCreate
    ) -> Any:
        value = await _managed(request).create_connection(
            body.key,
            body.provider_kind,
            CredentialRef(body.credential_ref),
            body.connection_config,
            body.enabled,
            body.actor,
        )
        return jsonable_encoder(_connection_response(value))

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
            body.actor,
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
            body.actor,
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
            body.actor,
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
            body.actor,
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
            body.actor,
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
            body.actor,
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
            body.tenant_id, body.phone_number, body.enabled, body.actor
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
            body.actor,
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

    @router.put("/provider-connections/{resource_id}")
    async def update_connection(
        request: Request, resource_id: UUID, body: ProviderConnectionUpdate
    ) -> Any:
        value = await _managed(request).update_connection(
            ProviderConnectionRef(resource_id),
            CredentialRef(body.credential_ref),
            body.connection_config,
            body.expected_generation,
            body.actor,
        )
        return jsonable_encoder(_connection_response(value))

    @router.post("/provider-connections/{resource_id}/{operation}")
    async def set_connection_enabled(
        request: Request,
        resource_id: UUID,
        operation: str,
        body: GeneratedActorRequest,
    ) -> Any:
        if operation not in {"enable", "disable"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        value = await _managed(request).set_connection_enabled(
            ProviderConnectionRef(resource_id),
            operation == "enable",
            body.expected_generation,
            body.actor,
        )
        return jsonable_encoder(_connection_response(value))

    @router.get("/provider-connections/{resource_id}")
    async def get_connection(request: Request, resource_id: UUID) -> Any:
        value = await _managed(request).get_connection(
            ProviderConnectionRef(resource_id)
        )
        return jsonable_encoder(_connection_response(value))

    @router.get("/provider-connections")
    async def list_connections(request: Request) -> Any:
        return jsonable_encoder(
            [
                _connection_response(value)
                for value in await _managed(request).list_connections()
            ]
        )

    @router.post("/model-deployments", status_code=status.HTTP_201_CREATED)
    async def create_deployment(request: Request, body: ModelDeploymentCreate) -> Any:
        value = await _managed(request).create_deployment(
            body.key,
            ProviderConnectionRef(body.connection_ref),
            body.deployment_kind,
            body.deployment_config,
            body.enabled,
            body.actor,
            LLMCapabilities(**body.llm_capabilities.model_dump())
            if body.llm_capabilities
            else None,
            RealtimeCapabilities(**body.realtime_capabilities.model_dump())
            if body.realtime_capabilities
            else None,
            STTCapabilities(**body.stt_capabilities.model_dump())
            if body.stt_capabilities
            else None,
        )
        return jsonable_encoder(_deployment_response(value))

    @router.put("/model-deployments/{resource_id}")
    async def update_deployment(
        request: Request, resource_id: UUID, body: ModelDeploymentUpdate
    ) -> Any:
        value = await _managed(request).update_deployment(
            ModelDeploymentRef(resource_id),
            ProviderConnectionRef(body.connection_ref),
            body.deployment_config,
            body.expected_generation,
            body.actor,
            LLMCapabilities(**body.llm_capabilities.model_dump())
            if body.llm_capabilities
            else None,
            RealtimeCapabilities(**body.realtime_capabilities.model_dump())
            if body.realtime_capabilities
            else None,
            STTCapabilities(**body.stt_capabilities.model_dump())
            if body.stt_capabilities
            else None,
        )
        return jsonable_encoder(_deployment_response(value))

    @router.post("/model-deployments/{resource_id}/{operation}")
    async def set_deployment_enabled(
        request: Request,
        resource_id: UUID,
        operation: str,
        body: GeneratedActorRequest,
    ) -> Any:
        if operation not in {"enable", "disable"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        value = await _managed(request).set_deployment_enabled(
            ModelDeploymentRef(resource_id),
            operation == "enable",
            body.expected_generation,
            body.actor,
        )
        return jsonable_encoder(_deployment_response(value))

    @router.get("/model-deployments/{resource_id}")
    async def get_deployment(request: Request, resource_id: UUID) -> Any:
        value = await _managed(request).get_deployment(ModelDeploymentRef(resource_id))
        return jsonable_encoder(_deployment_response(value))

    @router.get("/model-deployments")
    async def list_deployments(request: Request) -> Any:
        return jsonable_encoder(
            [
                _deployment_response(value)
                for value in await _managed(request).list_deployments()
            ]
        )

    return router
