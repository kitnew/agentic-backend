from uuid import UUID

from contracts.authoring import (
    TenantCapabilitiesAuthoring,
    TenantCapabilityAuthoring,
    TenantConfigAuthoring,
    TenantKnowledgeAuthoring,
    TenantPostCallActionAuthoring,
    TenantPostCallAuthoring,
    TenantPromptAuthoring,
    TenantRuntimeAuthoring,
)
from contracts.http_operation import HttpOperation
from contracts.tenant_components import (
    HttpExecution,
    PostCallAction,
    TenantCapabilitiesConfig,
    TenantCapabilityProfile,
    TenantPostCallConfig,
)

from backend_core.modules.integrations.repository import IntegrationConnectionRepository
from backend_core.runtime.capabilities.domain import (
    CapabilityValidationError,
    resolve_capability,
)


class AuthoringTranslationError(ValueError):
    def __init__(self, code: str, path: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message


def semantic_plan(before: object | None, after: object) -> dict[str, object]:
    if before == after:
        return {"valid": True, "changes": [], "errors": []}
    return {
        "valid": True,
        "changes": [{"path": "/", "operation": "replace", "before": before, "after": after}],
        "errors": [],
    }


async def _connection_id(
    connections: IntegrationConnectionRepository, tenant_id: UUID, key: str, path: str
) -> UUID:
    connection = await connections.get_by_key(tenant_id, key)
    if connection is None:
        raise AuthoringTranslationError(
            "integration_not_found", path, f"integration connection {key!r} was not found"
        )
    return connection.id


async def integration_readiness_warnings(
    operations: list[object],
    tenant_id: UUID,
    connections: IntegrationConnectionRepository,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for operation in operations:
        connection = await connections.get_by_key(tenant_id, operation.connection)
        if connection is not None and not getattr(connection, "enabled", True):
            warnings.append(
                {
                    "code": "integration_not_ready",
                    "path": "execution.connection",
                    "message": "Integration exists but is currently disabled",
                }
            )
    return warnings


async def _http_execution(
    operation: HttpOperation,
    tenant_id: UUID,
    connections: IntegrationConnectionRepository,
) -> HttpExecution:
    connection_id = await _connection_id(connections, tenant_id, operation.connection, "/execution/connection")
    return HttpExecution(
        connection_id=connection_id,
        method=operation.method,
        path=operation.path,
        query=operation.query,
        headers=operation.headers,
        request=operation.request,
        response=operation.response,
        timeout_seconds=operation.timeout_seconds,
        success_statuses=operation.success_statuses,
    )


async def translate_capabilities(
    value: TenantCapabilitiesAuthoring,
    *,
    tenant_id: UUID,
    connections: IntegrationConnectionRepository,
) -> TenantCapabilitiesConfig:
    capabilities: dict[str, bool | TenantCapabilityProfile] = {}
    for key, profile in value.capabilities.items():
        if isinstance(profile, bool):
            capabilities[key] = profile
            continue
        announcement = profile.announcement
        if isinstance(announcement, dict):
            announcement = announcement.get("before", "")
        capability = TenantCapabilityProfile.model_validate(
            {
                "enabled": profile.enabled,
                "semantic_version": 1,
                "description": profile.description,
                "announcement": announcement,
                "agent_input_schema": profile.agent_input_schema,
                "bindings": profile.bindings,
                "input_constraints": profile.input_constraints,
                "business_policy": profile.business_policy,
                "execution": (
                    await _http_execution(profile.execution, tenant_id, connections)
                ).model_copy(update={"result_schema": profile.result_schema}),
            }
        )
        try:
            resolve_capability(key, capability)
        except CapabilityValidationError as error:
            raise AuthoringTranslationError(
                error.code, error.path, error.message
            ) from error
        capabilities[key] = capability
    return TenantCapabilitiesConfig(capabilities=capabilities)


async def translate_post_call(
    value: TenantPostCallAuthoring,
    *,
    tenant_id: UUID,
    connections: IntegrationConnectionRepository,
) -> TenantPostCallConfig:
    actions = []
    for index, action in enumerate(value.actions):
        actions.append(
            PostCallAction(
                action_id=action.action_id,
                inputs=action.inputs,
                execution=await _http_execution(action.execution, tenant_id, connections),
            )
        )
    return TenantPostCallConfig(actions=actions)


async def authoring_value(
    component: str,
    payload: dict[str, object],
    *,
    tenant_id: UUID,
    connections: IntegrationConnectionRepository,
) -> object:
    if component == "agent":
        return TenantConfigAuthoring.model_validate(payload)
    if component == "runtime":
        return TenantRuntimeAuthoring.model_validate(payload)
    if component == "prompt":
        return TenantPromptAuthoring.model_validate(payload)
    if component == "knowledge":
        return TenantKnowledgeAuthoring(
            content=str(payload.get("inline_context") or "")
        )
    if component == "capabilities":
        return await _capabilities_authoring(payload, tenant_id, connections)
    if component == "post_call":
        return await _post_call_authoring(payload, tenant_id, connections)
    raise ValueError(f"unsupported authoring component: {component}")


async def _connection_key(
    connections: IntegrationConnectionRepository,
    tenant_id: UUID,
    connection_id: UUID,
) -> str:
    connection = await connections.get(tenant_id, connection_id)
    if connection is None:
        raise AuthoringTranslationError(
            "integration_not_found",
            "execution.connection",
            f"integration connection {connection_id!r} was not found",
        )
    return connection.key


def _operator_operation(execution: HttpExecution, connection: str) -> HttpOperation:
    return HttpOperation.model_validate(
        execution.model_dump(
            mode="json",
            exclude={"plan_type", "connection_id", "result_schema"},
        )
        | {"connection": connection}
    )


async def _capabilities_authoring(
    payload: dict[str, object],
    tenant_id: UUID,
    connections: IntegrationConnectionRepository,
) -> TenantCapabilitiesAuthoring:
    capabilities: dict[str, bool | TenantCapabilityAuthoring] = {}
    for key, raw in dict(payload.get("capabilities") or {}).items():
        if isinstance(raw, bool):
            capabilities[key] = raw
            continue
        profile = TenantCapabilityProfile.model_validate(raw)
        execution = HttpExecution.model_validate(profile.execution)
        capabilities[key] = TenantCapabilityAuthoring(
            enabled=profile.enabled,
            description=profile.description,
            announcement=profile.announcement,
            agent_input_schema=profile.agent_input_schema,
            bindings=profile.bindings,
            input_constraints=profile.input_constraints,
            business_policy=profile.business_policy.model_dump(mode="json"),
            execution=_operator_operation(
                execution,
                await _connection_key(connections, tenant_id, execution.connection_id),
            ),
            result_schema=execution.result_schema,
        )
    return TenantCapabilitiesAuthoring(capabilities=capabilities)


async def _post_call_authoring(
    payload: dict[str, object],
    tenant_id: UUID,
    connections: IntegrationConnectionRepository,
) -> TenantPostCallAuthoring:
    actions = []
    for raw in list(payload.get("actions") or []):
        action = PostCallAction.model_validate(raw)
        execution = action.execution
        actions.append(
            TenantPostCallActionAuthoring(
                action_id=action.action_id,
                inputs=action.inputs,
                execution=_operator_operation(
                    execution,
                    await _connection_key(connections, tenant_id, execution.connection_id),
                ),
            )
        )
    return TenantPostCallAuthoring(actions=actions)
