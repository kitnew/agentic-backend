from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from contracts import (
    BackendExecutionContext,
    CreateExecutionRequest,
    ErrorResponse,
    HandoffExecutionMaterial,
    InboundRoute,
    IntegrationExecutionMaterial,
    RuntimeSecretMaterial,
    RuntimeSecretSlot,
    VoiceExecutionContext,
    WorkerExecutionContext,
)
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool

from control_plane import SERVICE_NAME
from control_plane.application.command_support import (
    IdempotencyKeyReused,
    opaque_concurrency_token,
)
from control_plane.application.components import ComponentService
from control_plane.application.credentials import CredentialService
from control_plane.application.execution_materialization import (
    ExecutionMaterializationService,
)
from control_plane.application.integrations import (
    IntegrationService,
    IntegrationValidationResult,
)
from control_plane.application.live_components import (
    LiveComponentPreconditionFailed,
    LiveComponentService,
)
from control_plane.application.platform_catalogs import (
    CatalogConflict,
    CatalogError,
    CatalogNotFound,
    CatalogPreconditionFailed,
    InteractionModeCreate,
    InteractionModeUpdate,
    PlatformCatalogService,
    ProfileCreate,
    ProfileUpdate,
)
from control_plane.application.platform_configuration import (
    PlatformConfiguration,
    PlatformConfigurationApplyResult,
    PlatformConfigurationDesired,
    PlatformConfigurationError,
    PlatformConfigurationNotFound,
    PlatformConfigurationPlan,
    PlatformConfigurationPreconditionFailed,
    PlatformConfigurationPublishResult,
    PlatformConfigurationService,
)
from control_plane.application.providers import ProviderService
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
from control_plane.application.telephony import TelephonyService
from control_plane.application.tenant_configuration import (
    TenantConfiguration,
    TenantConfigurationApplyResult,
    TenantConfigurationDesired,
    TenantConfigurationError,
    TenantConfigurationNotFound,
    TenantConfigurationPlan,
    TenantConfigurationPreconditionFailed,
    TenantConfigurationPublishResult,
    TenantConfigurationService,
)
from control_plane.domain.components import (
    ComponentAddress,
    ComponentDefinitionRegistry,
    ComponentKind,
    ComponentScope,
    InteractionModeScope,
    PlatformScope,
    ProfileScope,
    SystemScope,
    TenantScope,
)
from control_plane.domain.components.errors import (
    ComponentError,
    ComponentNotFound,
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
from control_plane.domain.registries import (
    ArchitectureRegistry,
    DeploymentKindRegistry,
    IntegrationKindRegistry,
    ProviderKindRegistry,
    RegistryEntry,
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

MANAGEMENT_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse}
    for code in (400, 401, 403, 404, 409, 412, 422, 429, 500, 503)
}


def _management_router() -> APIRouter:
    return APIRouter(responses=MANAGEMENT_ERROR_RESPONSES)


class VersionedComponentDraftWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: dict[str, Any]


class VersionedComponentRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_number: int
    schema_version: int
    value: dict[str, Any]
    created_at: datetime
    created_by: str
    restored_from_revision: int | None


class VersionedComponentDraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    value: dict[str, Any]
    based_on_revision_number: int | None
    updated_at: datetime
    updated_by: str


class VersionedComponentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    scope: dict[str, str]
    active: VersionedComponentRevisionResponse | None
    draft: VersionedComponentDraftResponse | None


class CatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    description: str
    status: Literal["enabled", "disabled"]
    created_at: datetime
    updated_at: datetime


class LiveComponentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: dict[str, Any]


class LiveComponentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    scope: dict[str, str]
    value: dict[str, Any]
    updated_at: datetime
    updated_by: str


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
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


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


class IntegrationConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=255)
    integration_kind: str = Field(min_length=1, max_length=64)
    config: dict[str, object]
    credential_ref: UUID | None = None


class IntegrationConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    config: dict[str, object]
    credential_ref: UUID | None = None


class IntegrationConnectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    key: str
    integration_kind: str
    config: dict[str, object]
    credential_ref: UUID | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class IntegrationValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    usable: bool
    code: str | None = None
    message: str | None = None


class HandoffDestinationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(min_length=1, max_length=64)


class HandoffDestinationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=1000)
    phone_number: str = Field(min_length=1, max_length=64)


class PhoneNumberAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(min_length=1, max_length=64)


class PhoneNumberAssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    phone_number: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class HandoffDestinationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    key: str
    description: str
    phone_number: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class InboundRouteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    phone_number: str
    route_version: str


_runtime_secret_auth = Depends(require_service_scope("runtime-secret:materialize"))
_integration_material_auth = Depends(require_service_scope("integration-material:read"))
_execution_create_auth = Depends(require_service_scope("execution:create"))
_voice_context_auth = Depends(require_service_scope("execution:voice-context:read"))
_worker_context_auth = Depends(require_service_scope("execution:worker-context:read"))
_handoff_material_auth = Depends(require_service_scope("handoff-material:read"))
_telephony_resolve_auth = Depends(require_service_scope("telephony:resolve"))
_credential_read_auth = Depends(require_management_permission("resources:read"))
_credential_write_auth = Depends(require_management_permission("credentials:write"))


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


class RegistryEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    description: str
    metadata: dict[str, object]


class ComponentDefinitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    schema_version: int
    allowed_scopes: list[str]
    value_schema: dict[str, object]
    metadata: dict[str, object]


def create_http_app(
    lifecycle: ServiceLifecycle,
    components: ComponentService | None = None,
    execution_materialization: ExecutionMaterializationService | None = None,
    credentials: CredentialService | None = None,
    providers: ProviderService | None = None,
    system_configuration: SystemConfigurationService | None = None,
    live_components: LiveComponentService | None = None,
    tenant_live_components: LiveComponentService | None = None,
    platform_configuration: PlatformConfigurationService | None = None,
    platform_catalogs: PlatformCatalogService | None = None,
    integrations: IntegrationService | None = None,
    telephony: TelephonyService | None = None,
    tenant_configuration: TenantConfigurationService | None = None,
    component_registry: ComponentDefinitionRegistry | None = None,
    architecture_registry: ArchitectureRegistry | None = None,
    provider_registry: ProviderKindRegistry | None = None,
    deployment_registry: DeploymentKindRegistry | None = None,
    integration_registry: IntegrationKindRegistry | None = None,
) -> FastAPI:
    app = FastAPI(title="Agentic Backend Control Plane", lifespan=lifecycle.lifespan)
    app.state.settings = None
    app.state.lifecycle = lifecycle
    app.state.components = components
    app.state.execution_materialization = execution_materialization
    app.state.credentials = credentials
    app.state.providers = providers
    app.state.system_configuration = system_configuration
    app.state.live_components = live_components
    app.state.tenant_live_components = tenant_live_components
    app.state.platform_configuration = platform_configuration
    app.state.platform_catalogs = platform_catalogs
    app.state.integrations = integrations
    app.state.telephony = telephony
    app.state.tenant_configuration = tenant_configuration
    app.state.component_registry = component_registry
    app.state.architecture_registry = architecture_registry
    app.state.provider_registry = provider_registry
    app.state.deployment_registry = deployment_registry
    app.state.integration_registry = integration_registry

    @app.middleware("http")
    async def management_boundary(request: Request, call_next):
        target = request.url.path.startswith("/management/v1/")
        structured = request.url.path.startswith(("/management/v1/", "/internal/v1/"))
        request.state.request_id = str(uuid4())
        if target:
            try:
                request.state.management_principal = require_management_token(request)
            except HTTPException as error:
                return _management_error(
                    request,
                    error.status_code,
                    "unauthenticated",
                    str(error.detail),
                    headers=error.headers,
                )
        try:
            return await call_next(request)
        except Exception:
            if structured:
                return _management_error(
                    request,
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "internal_error",
                    "unexpected internal failure",
                )
            raise

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if request.url.path.startswith(("/management/v1/", "/internal/v1/")):
            code = (
                "permission_denied"
                if exc.status_code == status.HTTP_403_FORBIDDEN
                else "unauthenticated"
                if exc.status_code == status.HTTP_401_UNAUTHORIZED
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
        if request.url.path.startswith(("/management/v1/", "/internal/v1/")):
            issues = [
                {
                    "code": error["type"],
                    "path": ".".join(str(item) for item in error["loc"]),
                    "message": error["msg"],
                }
                for error in exc.errors()
            ]
            return _management_error(
                request,
                (
                    status.HTTP_400_BAD_REQUEST
                    if any(error["type"] == "json_invalid" for error in exc.errors())
                    else status.HTTP_422_UNPROCESSABLE_CONTENT
                ),
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
        if request.url.path.startswith(("/management/v1/", "/internal/v1/")):
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
        if request.url.path.startswith(("/management/v1/", "/internal/v1/")):
            return _management_error(request, code, exc.code, str(exc))
        return JSONResponse(
            status_code=code,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(RuntimeResolutionError)
    async def runtime_resolution_error(
        request: Request, exc: RuntimeResolutionError
    ) -> JSONResponse:
        if request.url.path.startswith(("/management/v1/", "/internal/v1/")):
            return _management_error(
                request,
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "runtime_resolution_failed",
                "execution configuration could not be resolved",
                details={
                    "reason": exc.reason,
                    "details": exc.details,
                    "attempts": exc.attempts,
                },
            )
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

    @app.exception_handler(PlatformConfigurationError)
    async def platform_configuration_error(
        request: Request, exc: PlatformConfigurationError
    ) -> JSONResponse:
        code = (
            status.HTTP_404_NOT_FOUND
            if isinstance(exc, PlatformConfigurationNotFound)
            else status.HTTP_412_PRECONDITION_FAILED
            if isinstance(exc, PlatformConfigurationPreconditionFailed)
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        return _management_error(request, code, exc.code, str(exc))

    @app.exception_handler(TenantConfigurationError)
    async def tenant_configuration_error(
        request: Request, exc: TenantConfigurationError
    ) -> JSONResponse:
        code = (
            status.HTTP_404_NOT_FOUND
            if isinstance(exc, TenantConfigurationNotFound)
            else status.HTTP_412_PRECONDITION_FAILED
            if isinstance(exc, TenantConfigurationPreconditionFailed)
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        return _management_error(request, code, exc.code, str(exc))

    @app.exception_handler(CatalogError)
    async def catalog_error(request: Request, exc: CatalogError) -> JSONResponse:
        code = (
            status.HTTP_404_NOT_FOUND
            if isinstance(exc, CatalogNotFound)
            else status.HTTP_412_PRECONDITION_FAILED
            if isinstance(exc, CatalogPreconditionFailed)
            else status.HTTP_409_CONFLICT
            if isinstance(exc, CatalogConflict)
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

    if credentials is not None:
        app.include_router(_credential_router(), prefix="/management/v1")
    if providers is not None:
        app.include_router(_provider_router(), prefix="/management/v1/providers")
    if integrations is not None:
        app.include_router(_integration_router(), prefix="/management/v1")
    if telephony is not None:
        app.include_router(_telephony_router(), prefix="/management/v1")
    if system_configuration is not None:
        app.include_router(_system_configuration_router(), prefix="/management/v1")
    if live_components is not None:
        app.include_router(_system_live_component_router(), prefix="/management/v1")
    if platform_configuration is not None:
        app.include_router(_platform_configuration_router(), prefix="/management/v1")
    if platform_catalogs is not None:
        app.include_router(_platform_catalog_router(), prefix="/management/v1")
    if tenant_configuration is not None:
        app.include_router(_tenant_configuration_router(), prefix="/management/v1")
    if all(
        registry is not None
        for registry in (
            component_registry,
            architecture_registry,
            provider_registry,
            deployment_registry,
            integration_registry,
        )
    ):
        app.include_router(_registry_router(), prefix="/management/v1")
    if components is not None:
        for prefix in (
            "/management/v1/platform",
            "/management/v1/platform/profiles/{profile_key}",
            "/management/v1/platform/interaction-modes/{mode_key}",
        ):
            app.include_router(_target_component_router(), prefix=prefix)
        app.include_router(
            _target_component_router(include_live=True),
            prefix="/management/v1/tenants/{tenant_id}",
        )
    app.include_router(_internal_router(), prefix="/internal/v1")

    def management_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        for path, item in schema["paths"].items():
            if not path.startswith("/management/v1/"):
                continue
            for method, operation in item.items():
                if method not in {"post", "put", "delete"}:
                    continue
                read_only = path.endswith(("/plan", "/validate"))
                draft_write = path.endswith("/draft")
                if method == "post" and not read_only:
                    _openapi_header(operation, "Idempotency-Key")
                if (method in {"put", "delete"} or method == "post") and (
                    draft_write
                    or method == "put"
                    or path.endswith(
                        (
                            "/publish",
                            "/rollback",
                            "/rotate",
                            "/revoke",
                            "/enable",
                            "/disable",
                        )
                    )
                ):
                    _openapi_header(operation, "If-Match")
                if method == "put" and not draft_write:
                    _openapi_header(operation, "Idempotency-Key")
                if method == "put" and path in {
                    "/management/v1/system/configuration",
                    "/management/v1/platform/configuration",
                    "/management/v1/tenants/{tenant_id}/configuration",
                }:
                    for parameter in operation.get("parameters", []):
                        if parameter.get("name") == "If-Match":
                            parameter["required"] = False
                    _openapi_header(operation, "If-None-Match", required=False)
        app.openapi_schema = schema
        return schema

    app.openapi = management_openapi  # type: ignore[method-assign]
    return app


def _openapi_header(
    operation: dict[str, Any], name: str, *, required: bool = True
) -> None:
    parameters = operation.setdefault("parameters", [])
    if any(parameter.get("name") == name for parameter in parameters):
        return
    parameters.append(
        {
            "name": name,
            "in": "header",
            "required": required,
            "schema": {"type": "string", "minLength": 1},
        }
    )


def _internal_router() -> APIRouter:
    router = APIRouter(responses=MANAGEMENT_ERROR_RESPONSES)

    @router.post(
        "/executions",
        response_model=BackendExecutionContext,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_execution(
        request: Request,
        body: CreateExecutionRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
        principal: ServicePrincipal = _execution_create_auth,
    ) -> Any:
        return jsonable_encoder(
            await request.app.state.execution_materialization.create_execution(
                body.tenant_id,
                body.context,
                principal=principal.subject,
                idempotency_key=idempotency_key,
            )
        )

    @router.get(
        "/executions/{execution_id}/voice-context",
        response_model=VoiceExecutionContext,
    )
    async def voice_context(
        request: Request,
        execution_id: UUID,
        _principal: ServicePrincipal = _voice_context_auth,
    ) -> Any:
        return jsonable_encoder(
            await request.app.state.execution_materialization.voice_context(
                execution_id
            )
        )

    @router.get(
        "/executions/{execution_id}/worker-context",
        response_model=WorkerExecutionContext,
    )
    async def worker_context(
        request: Request,
        execution_id: UUID,
        action_key: Annotated[str, Query(min_length=1)],
        _principal: ServicePrincipal = _worker_context_auth,
    ) -> Any:
        return jsonable_encoder(
            await request.app.state.execution_materialization.worker_context(
                execution_id, action_key
            )
        )

    @router.post(
        "/executions/{execution_id}/secrets/{slot}",
        response_model=RuntimeSecretMaterial,
    )
    async def runtime_secret(
        request: Request,
        execution_id: UUID,
        slot: RuntimeSecretSlot,
        _principal: ServicePrincipal = _runtime_secret_auth,
    ) -> JSONResponse:
        material = await request.app.state.execution_materialization.runtime_secret(
            execution_id, slot
        )
        return JSONResponse(jsonable_encoder(material), headers=_secret_headers())

    @router.post(
        "/executions/{execution_id}/integrations/{integration_key}/material",
        response_model=IntegrationExecutionMaterial,
    )
    async def integration_material(
        request: Request,
        execution_id: UUID,
        integration_key: str,
        _principal: ServicePrincipal = _integration_material_auth,
    ) -> JSONResponse:
        material = (
            await request.app.state.execution_materialization.integration_material(
                execution_id, integration_key
            )
        )
        return JSONResponse(jsonable_encoder(material), headers=_secret_headers())

    @router.post(
        "/executions/{execution_id}/handoff/{destination_key}/material",
        response_model=HandoffExecutionMaterial,
    )
    async def handoff_material(
        request: Request,
        execution_id: UUID,
        destination_key: str,
        _principal: ServicePrincipal = _handoff_material_auth,
    ) -> JSONResponse:
        material = await request.app.state.execution_materialization.handoff_material(
            execution_id, destination_key
        )
        return JSONResponse(jsonable_encoder(material), headers=_secret_headers())

    @router.get("/telephony/inbound-route", response_model=InboundRoute)
    async def inbound_route(
        request: Request,
        phone_number: Annotated[str, Query(min_length=1, max_length=64)],
        _principal: ServicePrincipal = _telephony_resolve_auth,
    ) -> Any:
        return jsonable_encoder(
            await request.app.state.telephony.resolve_inbound(phone_number)
        )

    return router


def _system_configuration_router() -> APIRouter:
    router = _management_router()
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

    @router.put(
        "/system/configuration",
        response_model=SystemConfigurationApplyResult,
        responses={428: {"model": ErrorResponse}},
    )
    async def apply_system_configuration(
        request: Request,
        body: SystemConfigurationDesired,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _configuration_command_headers(request)
        service = request.app.state.system_configuration
        result = await service.apply(
            body, expected_token, principal.subject, idempotency_key
        )
        return JSONResponse(
            jsonable_encoder(result),
            headers={"ETag": f'"{service.concurrency_token(result.configuration)}"'},
        )

    return router


def _registry_router() -> APIRouter:
    router = _management_router()
    read_auth = Depends(require_management_permission("registries:read"))

    def entries(values: tuple[RegistryEntry, ...]) -> list[dict[str, object]]:
        return [
            {
                "key": value.key,
                "name": value.name,
                "description": value.description,
                "metadata": dict(value.metadata),
            }
            for value in values
        ]

    @router.get("/registries/architectures", response_model=list[RegistryEntryResponse])
    async def architectures(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(
            entries(request.app.state.architecture_registry.entries)
        )

    @router.get(
        "/registries/components", response_model=list[ComponentDefinitionResponse]
    )
    async def components(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(
            [
                {
                    "key": value.key,
                    "schema_version": value.schema_version,
                    "allowed_scopes": value.allowed_scopes,
                    "value_schema": value.value_schema,
                    "metadata": dict(value.metadata),
                }
                for value in request.app.state.component_registry.entries
            ]
        )

    @router.get(
        "/registries/provider-kinds", response_model=list[RegistryEntryResponse]
    )
    async def provider_kinds(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(entries(request.app.state.provider_registry.entries))

    @router.get(
        "/registries/deployment-kinds", response_model=list[RegistryEntryResponse]
    )
    async def deployment_kinds(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(entries(request.app.state.deployment_registry.entries))

    @router.get(
        "/registries/integration-kinds", response_model=list[RegistryEntryResponse]
    )
    async def integration_kinds(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(entries(request.app.state.integration_registry.entries))

    return router


def _platform_configuration_router() -> APIRouter:
    router = _management_router()
    read_auth = Depends(require_management_permission("configuration:read"))
    write_auth = Depends(require_management_permission("configuration:write"))
    publish_auth = Depends(require_management_permission("configuration:publish"))

    @router.get("/platform/configuration", response_model=PlatformConfiguration)
    async def get_configuration(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> JSONResponse:
        service = request.app.state.platform_configuration
        value = await service.get()
        return JSONResponse(
            jsonable_encoder(value),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.post(
        "/platform/configuration/plan", response_model=PlatformConfigurationPlan
    )
    async def plan_configuration(
        request: Request,
        body: PlatformConfigurationDesired,
        _principal: ManagementPrincipal = write_auth,
    ) -> Any:
        return jsonable_encoder(
            await request.app.state.platform_configuration.plan(body)
        )

    @router.put(
        "/platform/configuration",
        response_model=PlatformConfigurationApplyResult,
        responses={428: {"model": ErrorResponse}},
    )
    async def apply_configuration(
        request: Request,
        body: PlatformConfigurationDesired,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        key, token = _configuration_command_headers(request)
        service = request.app.state.platform_configuration
        result = await service.apply(body, token, principal.subject, key)
        return JSONResponse(
            jsonable_encoder(result),
            headers={"ETag": f'"{service.concurrency_token(result.configuration)}"'},
        )

    @router.post(
        "/platform/configuration/publish",
        response_model=PlatformConfigurationPublishResult,
    )
    async def publish_configuration(
        request: Request, principal: ManagementPrincipal = publish_auth
    ) -> JSONResponse:
        key, token = _command_headers(request, precondition=True)
        service = request.app.state.platform_configuration
        result = await service.publish(token, principal.subject, key)
        return JSONResponse(
            jsonable_encoder(result),
            headers={"ETag": f'"{service.concurrency_token(result.configuration)}"'},
        )

    return router


def _tenant_configuration_router() -> APIRouter:
    router = _management_router()
    read_auth = Depends(require_management_permission("configuration:read"))
    write_auth = Depends(require_management_permission("configuration:write"))
    publish_auth = Depends(require_management_permission("configuration:publish"))

    @router.get(
        "/tenants/{tenant_id}/configuration", response_model=TenantConfiguration
    )
    async def get_configuration(
        request: Request,
        tenant_id: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = request.app.state.tenant_configuration
        value = await service.get(tenant_id)
        return JSONResponse(
            jsonable_encoder(value),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.post(
        "/tenants/{tenant_id}/configuration/plan",
        response_model=TenantConfigurationPlan,
    )
    async def plan_configuration(
        request: Request,
        tenant_id: str,
        body: TenantConfigurationDesired,
        _principal: ManagementPrincipal = write_auth,
    ) -> Any:
        return jsonable_encoder(
            await request.app.state.tenant_configuration.plan(tenant_id, body)
        )

    @router.put(
        "/tenants/{tenant_id}/configuration",
        response_model=TenantConfigurationApplyResult,
        responses={428: {"model": ErrorResponse}},
    )
    async def apply_configuration(
        request: Request,
        tenant_id: str,
        body: TenantConfigurationDesired,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        key, token = _configuration_command_headers(request)
        service = request.app.state.tenant_configuration
        result = await service.apply(tenant_id, body, token, principal.subject, key)
        return JSONResponse(
            jsonable_encoder(result),
            headers={"ETag": f'"{service.concurrency_token(result.configuration)}"'},
        )

    @router.post(
        "/tenants/{tenant_id}/configuration/publish",
        response_model=TenantConfigurationPublishResult,
    )
    async def publish_configuration(
        request: Request,
        tenant_id: str,
        principal: ManagementPrincipal = publish_auth,
    ) -> JSONResponse:
        key, token = _command_headers(request, precondition=True)
        service = request.app.state.tenant_configuration
        result = await service.publish(tenant_id, token, principal.subject, key)
        return JSONResponse(
            jsonable_encoder(result),
            headers={"ETag": f'"{service.concurrency_token(result.configuration)}"'},
        )

    return router


def _catalog_response(service, value, *, status_code=200) -> JSONResponse:
    return JSONResponse(
        jsonable_encoder(_catalog_payload(value)),
        status_code=status_code,
        headers={"ETag": f'"{service.concurrency_token(value)}"'},
    )


def _catalog_payload(value) -> dict[str, object]:
    return {
        "key": value.key,
        "name": value.name,
        "description": value.description,
        "status": value.status,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _platform_catalog_router() -> APIRouter:
    router = _management_router()
    read_auth = Depends(require_management_permission("configuration:read"))
    write_auth = Depends(require_management_permission("configuration:write"))

    @router.get("/platform/profiles", response_model=list[CatalogResponse])
    async def list_profiles(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(
            [
                _catalog_payload(value)
                for value in await request.app.state.platform_catalogs.list_profiles()
            ]
        )

    @router.post(
        "/platform/profiles",
        status_code=status.HTTP_201_CREATED,
        response_model=CatalogResponse,
    )
    async def create_profile(
        request: Request,
        body: ProfileCreate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        key, _ = _command_headers(request, precondition=False)
        service = request.app.state.platform_catalogs
        value = await service.create_profile(body, principal.subject, key)
        return _catalog_response(service, value, status_code=status.HTTP_201_CREATED)

    @router.get("/platform/profiles/{profile_key}", response_model=CatalogResponse)
    async def get_profile(
        request: Request,
        profile_key: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = request.app.state.platform_catalogs
        return _catalog_response(service, await service.get_profile(profile_key))

    @router.put("/platform/profiles/{profile_key}", response_model=CatalogResponse)
    async def update_profile(
        request: Request,
        profile_key: str,
        body: ProfileUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        key, token = _command_headers(request, precondition=True)
        service = request.app.state.platform_catalogs
        value = await service.update_profile(
            profile_key, body, token, principal.subject, key
        )
        return _catalog_response(service, value)

    async def set_profile(request, profile_key, enabled, principal):
        key, token = _command_headers(request, precondition=True)
        service = request.app.state.platform_catalogs
        value = await service.set_profile_enabled(
            profile_key, enabled, token, principal.subject, key
        )
        return _catalog_response(service, value)

    @router.post(
        "/platform/profiles/{profile_key}/enable", response_model=CatalogResponse
    )
    async def enable_profile(
        request: Request,
        profile_key: str,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_profile(request, profile_key, True, principal)

    @router.post(
        "/platform/profiles/{profile_key}/disable", response_model=CatalogResponse
    )
    async def disable_profile(
        request: Request,
        profile_key: str,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_profile(request, profile_key, False, principal)

    @router.get("/platform/interaction-modes", response_model=list[CatalogResponse])
    async def list_modes(
        request: Request, _principal: ManagementPrincipal = read_auth
    ) -> Any:
        return jsonable_encoder(
            [
                _catalog_payload(value)
                for value in await request.app.state.platform_catalogs.list_interaction_modes()
            ]
        )

    @router.post(
        "/platform/interaction-modes",
        status_code=status.HTTP_201_CREATED,
        response_model=CatalogResponse,
    )
    async def create_mode(
        request: Request,
        body: InteractionModeCreate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        key, _ = _command_headers(request, precondition=False)
        service = request.app.state.platform_catalogs
        value = await service.create_interaction_mode(body, principal.subject, key)
        return _catalog_response(service, value, status_code=status.HTTP_201_CREATED)

    @router.get(
        "/platform/interaction-modes/{mode_key}", response_model=CatalogResponse
    )
    async def get_mode(
        request: Request,
        mode_key: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = request.app.state.platform_catalogs
        return _catalog_response(service, await service.get_interaction_mode(mode_key))

    @router.put(
        "/platform/interaction-modes/{mode_key}", response_model=CatalogResponse
    )
    async def update_mode(
        request: Request,
        mode_key: str,
        body: InteractionModeUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        key, token = _command_headers(request, precondition=True)
        service = request.app.state.platform_catalogs
        value = await service.update_interaction_mode(
            mode_key, body, token, principal.subject, key
        )
        return _catalog_response(service, value)

    async def set_mode(request, mode_key, enabled, principal):
        key, token = _command_headers(request, precondition=True)
        service = request.app.state.platform_catalogs
        value = await service.set_interaction_mode_enabled(
            mode_key, enabled, token, principal.subject, key
        )
        return _catalog_response(service, value)

    @router.post(
        "/platform/interaction-modes/{mode_key}/enable",
        response_model=CatalogResponse,
    )
    async def enable_mode(
        request: Request,
        mode_key: str,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_mode(request, mode_key, True, principal)

    @router.post(
        "/platform/interaction-modes/{mode_key}/disable",
        response_model=CatalogResponse,
    )
    async def disable_mode(
        request: Request,
        mode_key: str,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_mode(request, mode_key, False, principal)

    return router


def _system_live_component_router() -> APIRouter:
    router = _management_router()
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


def _live_component_payload(state) -> dict[str, object]:
    scope = {"type": state.address.scope.type.value}
    if state.address.scope.key is not None:
        scope["tenant_id"] = state.address.scope.key
    return {
        "kind": str(state.address.kind),
        "scope": scope,
        "value": state.value,
        "updated_at": state.updated_at,
        "updated_by": state.updated_by,
    }


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
    details: dict[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    content: dict[str, object] = {
        "code": code,
        "message": message,
        "request_id": request.state.request_id,
    }
    if issues:
        content["issues"] = issues
    if details is not None:
        content["details"] = details
    return JSONResponse(content, status_code=status_code, headers=headers)


def _address(request: Request, kind: str) -> ComponentAddress:
    scope: ComponentScope
    if tenant_id := request.path_params.get("tenant_id"):
        scope = TenantScope(tenant_id)
    elif profile_key := request.path_params.get("profile_key"):
        scope = ProfileScope(profile_key)
    elif mode_key := request.path_params.get("mode_key"):
        scope = InteractionModeScope(mode_key)
    else:
        scope = PlatformScope()
    return ComponentAddress(ComponentKind(kind), scope)


def _service(request: Request) -> ComponentService:
    return request.app.state.components


def _management_actor(request: Request) -> str:
    principal = request.state.management_principal
    assert isinstance(principal, ManagementPrincipal)
    return principal.subject


def _component_etag(value) -> str:
    return opaque_concurrency_token(
        {
            "active_revision_id": (
                str(value.active.revision_id) if value.active is not None else None
            ),
            "draft_version": value.draft.version if value.draft is not None else None,
        }
    )


def _component_scope(value) -> dict[str, str]:
    result = {"type": value.type.value}
    if isinstance(value, ProfileScope):
        result["profile_key"] = value.profile_key
    elif isinstance(value, InteractionModeScope):
        result["mode_key"] = value.mode_key
    elif isinstance(value, TenantScope):
        result["tenant_id"] = value.tenant_id
    return result


def _revision_payload(value) -> dict[str, object]:
    return {
        "revision_number": value.revision_number,
        "schema_version": value.schema_version,
        "value": value.value,
        "created_at": value.created_at,
        "created_by": value.created_by,
        "restored_from_revision": None,
    }


def _draft_payload(value, active) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "value": value.value,
        "based_on_revision_number": (
            active.revision_number
            if active is not None and value.based_on_revision_id == active.revision_id
            else None
        ),
        "updated_at": value.updated_at,
        "updated_by": value.updated_by,
    }


def _component_payload(value) -> dict[str, object]:
    return {
        "kind": str(value.address.kind),
        "scope": _component_scope(value.address.scope),
        "active": _revision_payload(value.active) if value.active is not None else None,
        "draft": (
            _draft_payload(value.draft, value.active)
            if value.draft is not None
            else None
        ),
    }


def _require_component_precondition(request: Request, current) -> None:
    raw = request.headers.get("if-match", "").strip()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "If-Match is required")
    supplied = raw.removeprefix("W/").strip('"')
    expected = "*" if current is None else _component_etag(current)
    if supplied != expected:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            "versioned component precondition failed",
        )


async def _target_snapshot(request: Request, kind: str):
    try:
        return await _service(request).get_component(_address(request, kind))
    except ComponentNotFound:
        return None


def _require_versioned(request: Request, kind: str) -> None:
    if _service(request).lifecycle(_address(request, kind)) != "versioned":
        raise InvalidComponentValue(f"{kind} is not a versioned component")


def _component_response(value, *, status_code=200) -> JSONResponse:
    return JSONResponse(
        jsonable_encoder(_component_payload(value)),
        status_code=status_code,
        headers={"ETag": f'"{_component_etag(value)}"'},
    )


def _target_component_router(*, include_live: bool = False) -> APIRouter:
    router = _management_router()
    read_auth = Depends(require_management_permission("configuration:read"))
    write_auth = Depends(require_management_permission("configuration:write"))
    publish_auth = Depends(require_management_permission("configuration:publish"))

    @router.get(
        "/components/{kind}",
        response_model=LiveComponentResponse | VersionedComponentResponse,
    )
    async def get_component(
        request: Request,
        kind: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        address = _address(request, kind)
        if _service(request).lifecycle(address) == "live":
            service = request.app.state.tenant_live_components
            value = await service.get(address)
            return JSONResponse(
                jsonable_encoder(_live_component_payload(value)),
                headers={"ETag": f'"{service.concurrency_token(value)}"'},
            )
        return _component_response(await _service(request).get_component(address))

    async def set_live_component(
        request: Request,
        kind: str,
        body: LiveComponentWrite,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        key, token = _command_headers(request, precondition=True)
        address = _address(request, kind)
        if _service(request).lifecycle(address) != "live":
            raise InvalidComponentValue(f"{kind} is not a live component")
        service = request.app.state.tenant_live_components
        value = await service.set(address, body.value, token, principal.subject, key)
        return JSONResponse(
            jsonable_encoder(_live_component_payload(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    if include_live:
        router.add_api_route(
            "/components/{kind}",
            set_live_component,
            methods=["PUT"],
            response_model=LiveComponentResponse,
        )

    @router.get(
        "/components/{kind}/draft", response_model=VersionedComponentDraftResponse
    )
    async def get_draft(
        request: Request,
        kind: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> Any:
        _require_versioned(request, kind)
        snapshot = await _service(request).get_component(_address(request, kind))
        if snapshot.draft is None:
            raise ComponentNotFound("component draft does not exist")
        return jsonable_encoder(_draft_payload(snapshot.draft, snapshot.active))

    @router.put("/components/{kind}/draft", response_model=VersionedComponentResponse)
    async def save_draft(
        request: Request,
        kind: str,
        body: VersionedComponentDraftWrite,
        _principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        _require_versioned(request, kind)
        current = await _target_snapshot(request, kind)
        _require_component_precondition(request, current)
        await _service(request).save_draft(
            _address(request, kind),
            body.value,
            current.draft.version if current and current.draft else None,
            current.active.revision_id if current and current.active else None,
            _management_actor(request),
        )
        return _component_response(
            await _service(request).get_component(_address(request, kind))
        )

    @router.delete("/components/{kind}/draft", status_code=status.HTTP_204_NO_CONTENT)
    async def discard_draft(
        request: Request,
        kind: str,
        _principal: ManagementPrincipal = write_auth,
    ) -> None:
        _require_versioned(request, kind)
        current = await _service(request).get_component(_address(request, kind))
        _require_component_precondition(request, current)
        if current.draft is None:
            raise ComponentNotFound("component draft does not exist")
        await _service(request).discard_draft(
            _address(request, kind), current.draft.version
        )

    @router.post(
        "/components/{kind}/publish", response_model=VersionedComponentResponse
    )
    async def publish(
        request: Request,
        kind: str,
        principal: ManagementPrincipal = publish_auth,
    ) -> JSONResponse:
        _require_versioned(request, kind)
        key, _ = _command_headers(request, precondition=True)
        current = await _service(request).get_component(_address(request, kind))
        _require_component_precondition(request, current)
        if current.draft is None:
            raise ComponentNotFound("component draft does not exist")
        await _service(request).publish_draft(
            _address(request, kind),
            current.draft.version,
            principal.subject,
            idempotency_key=key,
        )
        return _component_response(
            await _service(request).get_component(_address(request, kind))
        )

    @router.get(
        "/components/{kind}/active", response_model=VersionedComponentRevisionResponse
    )
    async def active(
        request: Request,
        kind: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> Any:
        _require_versioned(request, kind)
        return jsonable_encoder(
            _revision_payload(
                await _service(request).get_active(_address(request, kind))
            )
        )

    @router.get(
        "/components/{kind}/revisions",
        response_model=list[VersionedComponentRevisionResponse],
    )
    async def revisions(
        request: Request,
        kind: str,
        limit: int = Query(100, ge=1, le=500),
        _principal: ManagementPrincipal = read_auth,
    ) -> Any:
        _require_versioned(request, kind)
        return jsonable_encoder(
            [
                _revision_payload(value)
                for value in await _service(request).list_revisions(
                    _address(request, kind), limit
                )
            ]
        )

    @router.get(
        "/components/{kind}/revisions/{revision_number}",
        response_model=VersionedComponentRevisionResponse,
    )
    async def revision(
        request: Request,
        kind: str,
        revision_number: int,
        _principal: ManagementPrincipal = read_auth,
    ) -> Any:
        _require_versioned(request, kind)
        return jsonable_encoder(
            _revision_payload(
                await _service(request).get_revision(
                    _address(request, kind), revision_number
                )
            )
        )

    @router.post(
        "/components/{kind}/rollback", response_model=VersionedComponentResponse
    )
    async def rollback(
        request: Request,
        kind: str,
        body: RollbackRequest,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        _require_versioned(request, kind)
        key, _ = _command_headers(request, precondition=True)
        current = await _service(request).get_component(_address(request, kind))
        _require_component_precondition(request, current)
        await _service(request).rollback(
            _address(request, kind),
            body.revision_number,
            principal.subject,
            idempotency_key=key,
        )
        return _component_response(
            await _service(request).get_component(_address(request, kind))
        )

    return router


def _provider(request: Request) -> ProviderService:
    return request.app.state.providers


def _credential(request: Request) -> CredentialService:
    return request.app.state.credentials


def _credential_response(value: object) -> CredentialResponse:
    from control_plane.domain.managed_resources import Credential

    assert isinstance(value, Credential)
    assert value.active_secret_version_number is not None
    scope = (
        {"type": "tenant", "tenant_id": value.scope.tenant_id}
        if isinstance(value.scope, TenantCredentialScope)
        else {"type": "platform"}
    )
    return CredentialResponse(
        id=value.ref.value,
        scope=scope,  # type: ignore[arg-type]
        name=value.name,
        status=value.status.value,
        active_secret_version=value.active_secret_version_number,
        created_at=value.created_at,
        updated_at=value.revoked_at or value.created_at,
        revoked_at=value.revoked_at,
    )


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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "If-Match is required")
    return idempotency_key, if_match.removeprefix("W/").strip('"')


def _configuration_command_headers(request: Request) -> tuple[str, str]:
    idempotency_key, _ = _command_headers(request, precondition=False)
    if_match = request.headers.get("if-match", "").strip()
    if_none_match = request.headers.get("if-none-match", "").strip()
    if if_match and if_none_match:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "If-Match and If-None-Match cannot both be supplied",
        )
    if not if_match and not if_none_match:
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED,
            "If-Match or If-None-Match: * is required",
        )
    if if_none_match:
        return idempotency_key, if_none_match.removeprefix("W/").strip('"')
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
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _handoff_destination_response(value: HandoffDestination) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "tenant_id": value.tenant_id,
        "key": value.key,
        "description": value.description,
        "phone_number": value.phone_number,
        "enabled": value.enabled,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
    }


def _phone_number_assignment_response(
    value: PhoneNumberAssignment,
) -> dict[str, object]:
    return {
        "id": value.ref.value,
        "tenant_id": value.tenant_id,
        "phone_number": value.phone_number,
        "enabled": value.enabled,
        "created_at": value.created_at,
        "updated_at": value.updated_at,
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
    router = _management_router()

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
            _credential_response(value).model_dump(mode="json"),
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
        return [
            _credential_response(value)
            for value in await _credential(request).list(scope)
        ]

    @router.get("/credentials/{id}", response_model=CredentialResponse)
    async def get_credential(
        request: Request,
        id: UUID,
        _principal: ManagementPrincipal = _credential_read_auth,
    ) -> JSONResponse:
        service = _credential(request)
        value = await service.get(CredentialRef(id))
        return JSONResponse(
            _credential_response(value).model_dump(mode="json"),
            headers={"ETag": _etag(service, value)},
        )

    @router.post("/credentials/{id}/rotate", response_model=CredentialResponse)
    async def rotate_credential(
        request: Request,
        id: UUID,
        body: CredentialRotate,
        principal: ManagementPrincipal = _credential_write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _credential(request)
        value = await service.rotate(
            CredentialRef(id),
            body.secret.get_secret_value(),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            _credential_response(value).model_dump(mode="json"),
            headers={"ETag": _etag(service, value)},
        )

    @router.post("/credentials/{id}/revoke", response_model=CredentialResponse)
    async def revoke_credential(
        request: Request,
        id: UUID,
        principal: ManagementPrincipal = _credential_write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _credential(request)
        value = await service.revoke(
            CredentialRef(id),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            _credential_response(value).model_dump(mode="json"),
            headers={"ETag": _etag(service, value)},
        )

    return router


def _provider_router() -> APIRouter:
    router = _management_router()
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

    @router.get("/connections/{id}", response_model=ProviderConnectionResponse)
    async def get_connection(
        request: Request,
        id: UUID,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = _provider(request)
        value = await service.get_connection(ProviderConnectionRef(id))
        return JSONResponse(
            jsonable_encoder(_connection_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.put("/connections/{id}", response_model=ProviderConnectionResponse)
    async def update_connection(
        request: Request,
        id: UUID,
        body: ProviderConnectionUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        value = await service.update_connection(
            ProviderConnectionRef(id),
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

    @router.post("/connections/{id}/enable", response_model=ProviderConnectionResponse)
    async def enable_connection(
        request: Request,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await connection_lifecycle(request, id, principal, True)

    @router.post("/connections/{id}/disable", response_model=ProviderConnectionResponse)
    async def disable_connection(
        request: Request,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await connection_lifecycle(request, id, principal, False)

    async def connection_lifecycle(
        request: Request,
        id: UUID,
        principal: ManagementPrincipal,
        enabled: bool,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        command = service.enable_connection if enabled else service.disable_connection
        value = await command(
            ProviderConnectionRef(id),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_connection_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.post(
        "/connections/{id}/validate",
        response_model=ProviderValidationResponse,
    )
    async def validate_connection(
        request: Request,
        id: UUID,
        _principal: ManagementPrincipal = write_auth,
    ) -> Any:
        return jsonable_encoder(
            await _provider(request).validate_connection(ProviderConnectionRef(id))
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

    @router.get("/deployments/{id}", response_model=ModelDeploymentResponse)
    async def get_deployment(
        request: Request,
        id: UUID,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service = _provider(request)
        value = await service.get_deployment(ModelDeploymentRef(id))
        return JSONResponse(
            jsonable_encoder(_deployment_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.put("/deployments/{id}", response_model=ModelDeploymentResponse)
    async def update_deployment(
        request: Request,
        id: UUID,
        body: ModelDeploymentUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        value = await service.update_deployment(
            ModelDeploymentRef(id),
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

    @router.post("/deployments/{id}/enable", response_model=ModelDeploymentResponse)
    async def enable_deployment(
        request: Request,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await deployment_lifecycle(request, id, principal, True)

    @router.post("/deployments/{id}/disable", response_model=ModelDeploymentResponse)
    async def disable_deployment(
        request: Request,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await deployment_lifecycle(request, id, principal, False)

    async def deployment_lifecycle(
        request: Request,
        id: UUID,
        principal: ManagementPrincipal,
        enabled: bool,
    ) -> JSONResponse:
        idempotency_key, expected_token = _command_headers(request, precondition=True)
        service = _provider(request)
        command = service.enable_deployment if enabled else service.disable_deployment
        value = await command(
            ModelDeploymentRef(id),
            expected_token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_deployment_response(value)),
            headers={"ETag": _provider_etag(service, value)},
        )

    @router.post(
        "/deployments/{id}/validate",
        response_model=ProviderValidationResponse,
    )
    async def validate_deployment(
        request: Request,
        id: UUID,
        _principal: ManagementPrincipal = write_auth,
    ) -> Any:
        return jsonable_encoder(
            await _provider(request).validate_deployment(ModelDeploymentRef(id))
        )

    return router


def _integration_router() -> APIRouter:
    router = _management_router()
    read_auth = Depends(require_management_permission("resources:read"))
    write_auth = Depends(require_management_permission("resources:write"))

    @router.get(
        "/tenants/{tenant_id}/integrations",
        response_model=list[IntegrationConnectionResponse],
    )
    async def list_integrations(
        request: Request,
        tenant_id: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> Any:
        return jsonable_encoder(
            [
                _integration_connection_response(value)
                for value in await request.app.state.integrations.list(tenant_id)
            ]
        )

    @router.post(
        "/tenants/{tenant_id}/integrations",
        status_code=status.HTTP_201_CREATED,
        response_model=IntegrationConnectionResponse,
    )
    async def create_integration_connection(
        request: Request,
        tenant_id: str,
        body: IntegrationConnectionCreate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, _ = _command_headers(request, precondition=False)
        service: IntegrationService = request.app.state.integrations
        value = await service.create(
            tenant_id,
            body.key,
            body.integration_kind,
            body.config,
            CredentialRef(body.credential_ref) if body.credential_ref else None,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_integration_connection_response(value)),
            status_code=status.HTTP_201_CREATED,
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.get(
        "/tenants/{tenant_id}/integrations/{id}",
        response_model=IntegrationConnectionResponse,
    )
    async def get_integration_connection(
        request: Request,
        tenant_id: str,
        id: UUID,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service: IntegrationService = request.app.state.integrations
        value = await service.get(tenant_id, IntegrationConnectionRef(id))
        return JSONResponse(
            jsonable_encoder(_integration_connection_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.put(
        "/tenants/{tenant_id}/integrations/{id}",
        response_model=IntegrationConnectionResponse,
    )
    async def update_integration_connection(
        request: Request,
        tenant_id: str,
        id: UUID,
        body: IntegrationConnectionUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, token = _command_headers(request, precondition=True)
        service: IntegrationService = request.app.state.integrations
        value = await service.update(
            tenant_id,
            IntegrationConnectionRef(id),
            body.config,
            CredentialRef(body.credential_ref) if body.credential_ref else None,
            token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_integration_connection_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    async def set_enabled(request, tenant_id, id, enabled, principal):
        idempotency_key, token = _command_headers(request, precondition=True)
        service: IntegrationService = request.app.state.integrations
        command = service.enable if enabled else service.disable
        value = await command(
            tenant_id,
            IntegrationConnectionRef(id),
            token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_integration_connection_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.post(
        "/tenants/{tenant_id}/integrations/{id}/enable",
        response_model=IntegrationConnectionResponse,
    )
    async def enable_integration(
        request: Request,
        tenant_id: str,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_enabled(request, tenant_id, id, True, principal)

    @router.post(
        "/tenants/{tenant_id}/integrations/{id}/disable",
        response_model=IntegrationConnectionResponse,
    )
    async def disable_integration(
        request: Request,
        tenant_id: str,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_enabled(request, tenant_id, id, False, principal)

    @router.post(
        "/tenants/{tenant_id}/integrations/{id}/validate",
        response_model=IntegrationValidationResponse,
    )
    async def validate_integration(
        request: Request,
        tenant_id: str,
        id: UUID,
        _principal: ManagementPrincipal = write_auth,
    ) -> IntegrationValidationResult:
        return await request.app.state.integrations.validate(
            tenant_id, IntegrationConnectionRef(id)
        )

    return router


def _telephony_router() -> APIRouter:
    router = _management_router()
    read_auth = Depends(require_management_permission("resources:read"))
    write_auth = Depends(require_management_permission("resources:write"))

    assignment_path = "/tenants/{tenant_id}/telephony/phone-number-assignments"
    destination_path = "/tenants/{tenant_id}/telephony/handoff-destinations"

    @router.post(
        assignment_path,
        status_code=status.HTTP_201_CREATED,
        response_model=PhoneNumberAssignmentResponse,
    )
    async def create_phone_number_assignment(
        request: Request,
        tenant_id: str,
        body: PhoneNumberAssignmentCreate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, _ = _command_headers(request, precondition=False)
        service: TelephonyService = request.app.state.telephony
        value = await service.create_assignment(
            tenant_id, body.phone_number, principal.subject, idempotency_key
        )
        return JSONResponse(
            jsonable_encoder(_phone_number_assignment_response(value)),
            status_code=status.HTTP_201_CREATED,
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.get(assignment_path, response_model=list[PhoneNumberAssignmentResponse])
    async def list_phone_number_assignments(
        request: Request,
        tenant_id: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> Any:
        return jsonable_encoder(
            [
                _phone_number_assignment_response(value)
                for value in await request.app.state.telephony.list_assignments(
                    tenant_id
                )
            ]
        )

    @router.get(
        f"{assignment_path}/{{id}}",
        response_model=PhoneNumberAssignmentResponse,
    )
    async def get_phone_number_assignment(
        request: Request,
        tenant_id: str,
        id: UUID,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service: TelephonyService = request.app.state.telephony
        value = await service.get_assignment(tenant_id, PhoneNumberAssignmentRef(id))
        return JSONResponse(
            jsonable_encoder(_phone_number_assignment_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    async def set_assignment_enabled(
        request: Request, tenant_id: str, id: UUID, enabled: bool, principal
    ) -> JSONResponse:
        idempotency_key, token = _command_headers(request, precondition=True)
        service: TelephonyService = request.app.state.telephony
        command = service.enable_assignment if enabled else service.disable_assignment
        value = await command(
            tenant_id,
            PhoneNumberAssignmentRef(id),
            token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_phone_number_assignment_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.post(
        f"{assignment_path}/{{id}}/enable",
        response_model=PhoneNumberAssignmentResponse,
    )
    async def enable_phone_number_assignment(
        request: Request,
        tenant_id: str,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_assignment_enabled(request, tenant_id, id, True, principal)

    @router.post(
        f"{assignment_path}/{{id}}/disable",
        response_model=PhoneNumberAssignmentResponse,
    )
    async def disable_phone_number_assignment(
        request: Request,
        tenant_id: str,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_assignment_enabled(request, tenant_id, id, False, principal)

    @router.post(
        destination_path,
        status_code=status.HTTP_201_CREATED,
        response_model=HandoffDestinationResponse,
    )
    async def create_handoff_destination(
        request: Request,
        tenant_id: str,
        body: HandoffDestinationCreate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, _ = _command_headers(request, precondition=False)
        service: TelephonyService = request.app.state.telephony
        value = await service.create_destination(
            tenant_id,
            body.key,
            body.description,
            body.phone_number,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_handoff_destination_response(value)),
            status_code=status.HTTP_201_CREATED,
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.put(
        f"{destination_path}/{{id}}",
        response_model=HandoffDestinationResponse,
    )
    async def update_handoff_destination(
        request: Request,
        tenant_id: str,
        id: UUID,
        body: HandoffDestinationUpdate,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        idempotency_key, token = _command_headers(request, precondition=True)
        service: TelephonyService = request.app.state.telephony
        value = await service.update_destination(
            tenant_id,
            HandoffDestinationRef(id),
            body.description,
            body.phone_number,
            token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_handoff_destination_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    async def set_destination_enabled(
        request: Request, tenant_id: str, id: UUID, enabled: bool, principal
    ) -> JSONResponse:
        idempotency_key, token = _command_headers(request, precondition=True)
        service: TelephonyService = request.app.state.telephony
        command = service.enable_destination if enabled else service.disable_destination
        value = await command(
            tenant_id,
            HandoffDestinationRef(id),
            token,
            principal.subject,
            idempotency_key,
        )
        return JSONResponse(
            jsonable_encoder(_handoff_destination_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.post(
        f"{destination_path}/{{id}}/enable",
        response_model=HandoffDestinationResponse,
    )
    async def enable_handoff_destination(
        request: Request,
        tenant_id: str,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_destination_enabled(request, tenant_id, id, True, principal)

    @router.post(
        f"{destination_path}/{{id}}/disable",
        response_model=HandoffDestinationResponse,
    )
    async def disable_handoff_destination(
        request: Request,
        tenant_id: str,
        id: UUID,
        principal: ManagementPrincipal = write_auth,
    ) -> JSONResponse:
        return await set_destination_enabled(request, tenant_id, id, False, principal)

    @router.get(
        f"{destination_path}/{{id}}",
        response_model=HandoffDestinationResponse,
    )
    async def get_handoff_destination(
        request: Request,
        tenant_id: str,
        id: UUID,
        _principal: ManagementPrincipal = read_auth,
    ) -> JSONResponse:
        service: TelephonyService = request.app.state.telephony
        value = await service.get_destination(tenant_id, HandoffDestinationRef(id))
        return JSONResponse(
            jsonable_encoder(_handoff_destination_response(value)),
            headers={"ETag": f'"{service.concurrency_token(value)}"'},
        )

    @router.get(destination_path, response_model=list[HandoffDestinationResponse])
    async def list_handoff_destinations(
        request: Request,
        tenant_id: str,
        _principal: ManagementPrincipal = read_auth,
    ) -> Any:
        return jsonable_encoder(
            [
                _handoff_destination_response(value)
                for value in await request.app.state.telephony.list_destinations(
                    tenant_id
                )
            ]
        )

    return router
