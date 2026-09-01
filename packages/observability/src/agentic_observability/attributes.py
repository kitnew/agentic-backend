"""Telemetry Contract v1 attribute policy."""

from collections.abc import Mapping

SERVICE_NAMESPACE = "agentic-backend"
SERVICE_NAMES = frozenset(
    {"backend-core", "control-plane-service", "job-worker", "voice-agent"}
)
REQUIRED_RESOURCE_ATTRIBUTES = frozenset(
    {"service.version", "deployment.environment.name", "vcs.ref.head.revision"}
)
DOMAIN_ATTRIBUTES = frozenset(
    {
        "tenant.id",
        "call.id",
        "conversation.id",
        "agent.id",
        "agent.revision",
        "operation.id",
        "capability.name",
        "capability.version",
        "command.id",
        "action.id",
        "artifact.type",
    }
)
IDENTIFIER_ATTRIBUTES = frozenset(
    {
        "tenant.id",
        "call.id",
        "conversation.id",
        "agent.id",
        "agent.revision",
        "operation.id",
        "command.id",
        "action.id",
    }
)
METRIC_ATTRIBUTE_ALLOWLIST = frozenset(
    {
        "capability.name",
        "capability.version",
        "artifact.type",
        "status",
        "reason",
        "outcome",
        "error.type",
        "voice.component",
        "voice.model",
        "voice.provider",
        "operation.type",
    }
)
SAFE_LOG_FIELD_ALLOWLIST = frozenset(
    {attribute.replace(".", "_") for attribute in DOMAIN_ATTRIBUTES}
    | {"trace_id", "span_id", "event", "status", "outcome", "error_type"}
)
PRIVATE_ATTRIBUTE_TERMS = frozenset(
    {
        "audio",
        "authorization",
        "body",
        "content",
        "credential",
        "password",
        "payload",
        "phone",
        "prompt",
        "recording",
        "result",
        "sip",
        "token",
        "tool_argument",
        "transcript",
    }
)


def metric_attributes(
    attributes: Mapping[str, str | bool | int | float],
) -> dict[str, str | bool | int | float]:
    invalid = set(attributes) - METRIC_ATTRIBUTE_ALLOWLIST
    if invalid:
        raise ValueError(
            f"metric attributes are not allowed: {', '.join(sorted(invalid))}"
        )
    return dict(attributes)


def safe_log_fields(fields: Mapping[str, object]) -> dict[str, object]:
    invalid = set(fields) - SAFE_LOG_FIELD_ALLOWLIST
    private = {field for field in fields if _is_private(field)}
    if invalid or private:
        rejected = invalid | private
        raise ValueError(f"unsafe log fields: {', '.join(sorted(rejected))}")
    return dict(fields)


def validate_resource_attributes(attributes: Mapping[str, str]) -> dict[str, str]:
    missing = REQUIRED_RESOURCE_ATTRIBUTES - set(attributes)
    if missing:
        raise ValueError(f"missing resource attributes: {', '.join(sorted(missing))}")
    if "deployment.environment" in attributes:
        raise ValueError(
            "deployment.environment is deprecated; use deployment.environment.name"
        )
    invalid_build_ids = {
        name
        for name in attributes
        if name.endswith("build.id") and name != "agentic_backend.build.id"
    }
    if invalid_build_ids:
        raise ValueError(
            "only agentic_backend.build.id is permitted as a build identifier"
        )
    private = {name for name in attributes if _is_private(name)}
    if private:
        raise ValueError(f"private resource attributes: {', '.join(sorted(private))}")
    return dict(attributes)


def _is_private(name: str) -> bool:
    normalized = name.lower().replace("-", "_").replace(".", "_")
    return any(term in normalized for term in PRIVATE_ATTRIBUTE_TERMS)
