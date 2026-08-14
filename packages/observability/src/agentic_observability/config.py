"""Standard OpenTelemetry environment configuration without application settings wiring."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .attributes import SERVICE_NAMES, SERVICE_NAMESPACE, validate_resource_attributes

DEFAULT_OTLP_ENDPOINT = "http://otel-collector:4318"


@dataclass(frozen=True, slots=True)
class TelemetryConfig:
    service_name: str
    resource_attributes: Mapping[str, str]
    enabled: bool = False
    endpoint: str = DEFAULT_OTLP_ENDPOINT
    sdk_disabled: bool = False
    protocol: str = "http/protobuf"
    propagators: str = "tracecontext"

    def __post_init__(self) -> None:
        if self.service_name not in SERVICE_NAMES:
            raise ValueError(f"unsupported service.name: {self.service_name}")
        if self.protocol != "http/protobuf":
            raise ValueError("OTEL_EXPORTER_OTLP_PROTOCOL must be http/protobuf")
        if self.propagators != "tracecontext":
            raise ValueError("OTEL_PROPAGATORS must be tracecontext")
        attributes = validate_resource_attributes(self.resource_attributes)
        attributes["service.namespace"] = SERVICE_NAMESPACE
        attributes["service.name"] = self.service_name
        object.__setattr__(self, "resource_attributes", MappingProxyType(attributes))

    @classmethod
    def from_env(
        cls,
        *,
        default_service_name: str | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> TelemetryConfig:
        values = os.environ if environ is None else environ
        service_name = values.get("OTEL_SERVICE_NAME", default_service_name)
        if service_name is None:
            raise ValueError("OTEL_SERVICE_NAME or default_service_name is required")
        return cls(
            service_name=service_name,
            resource_attributes=_parse_resource_attributes(
                values.get("OTEL_RESOURCE_ATTRIBUTES", "")
            ),
            enabled=values.get("OTEL_ENABLED", "").lower() == "true",
            endpoint=values.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT),
            sdk_disabled=values.get("OTEL_SDK_DISABLED", "").lower() == "true",
            protocol=values.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
            propagators=values.get("OTEL_PROPAGATORS", "tracecontext"),
        )


def _parse_resource_attributes(value: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in value.split(","))):
        name, separator, attribute_value = item.partition("=")
        if not separator or not name or not attribute_value:
            raise ValueError("OTEL_RESOURCE_ATTRIBUTES entries must be key=value")
        attributes[name] = attribute_value
    return attributes
