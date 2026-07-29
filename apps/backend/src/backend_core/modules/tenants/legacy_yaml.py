from dataclasses import dataclass
from typing import Annotated, Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from yaml import YAMLError

from backend_core.modules.tenants.models import Tenant
from backend_core.modules.tenants.schemas import (
    LegacyTenantIdentity,
    ValidationIssue,
)


class _LegacyModel(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class _LegacyAgent(_LegacyModel):
    display_name: Annotated[str, Field(min_length=1)]
    greeting_phrase: Annotated[str, Field(min_length=1)]


class _LegacyConversationScope(_LegacyModel):
    mode: str = "property_only"


class _LegacyConfig(_LegacyModel):
    schema_version: Literal[1] = 1
    tenant_id: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    business_type: Annotated[str, Field(min_length=1)]
    locale: Annotated[str, Field(min_length=1)]
    timezone: Annotated[str, Field(min_length=1)]
    agent: _LegacyAgent
    conversation_scope: _LegacyConversationScope = Field(
        default_factory=_LegacyConversationScope
    )


class LegacyYamlError(Exception):
    def __init__(self, errors: list[ValidationIssue]) -> None:
        self.errors = errors
        super().__init__("invalid legacy YAML")


@dataclass(frozen=True, slots=True)
class LegacyYamlDocument:
    identity: LegacyTenantIdentity
    config: dict[str, Any]
    unsupported_fields: list[str]

    def validate_tenant(self, tenant: Tenant) -> list[ValidationIssue]:
        expected = {
            "tenant_id": tenant.slug,
            "name": tenant.display_name,
            "business_type": tenant.business_type,
        }
        actual = {
            "tenant_id": self.identity.legacy_id.replace("_", "-").lower(),
            "name": self.identity.display_name,
            "business_type": self.identity.business_type,
        }
        return [
            ValidationIssue(
                path=path,
                code="tenant_identity_mismatch",
                message=f"Expected {expected[path]!r}",
            )
            for path in expected
            if actual[path] != expected[path]
        ]


def parse_legacy_yaml(raw_yaml: str) -> LegacyYamlDocument:
    try:
        raw = yaml.safe_load(raw_yaml)
    except YAMLError as error:
        raise LegacyYamlError(
            [
                ValidationIssue(
                    path="$",
                    code="invalid_yaml",
                    message="YAML cannot be parsed",
                )
            ]
        ) from error

    try:
        legacy = _LegacyConfig.model_validate(raw)
    except ValidationError as error:
        raise LegacyYamlError(
            [
                ValidationIssue(
                    path=".".join(str(part) for part in item["loc"]) or "$",
                    code=item["type"],
                    message=item["msg"],
                )
                for item in error.errors(
                    include_url=False,
                    include_context=False,
                    include_input=False,
                )
            ]
        ) from error

    unsupported_fields = [
        *(legacy.model_extra or {}),
        *(f"agent.{field}" for field in (legacy.agent.model_extra or {})),
        *(
            f"conversation_scope.{field}"
            for field in (legacy.conversation_scope.model_extra or {})
        ),
    ]
    return LegacyYamlDocument(
        identity=LegacyTenantIdentity(
            legacy_id=legacy.tenant_id,
            display_name=legacy.name,
            business_type=legacy.business_type,
        ),
        config={
            "schema_version": 1,
            "localization": {
                "default_locale": legacy.locale,
                "timezone": legacy.timezone,
            },
            "agent": {
                "display_name": legacy.agent.display_name,
                "greeting": legacy.agent.greeting_phrase,
            },
            "conversation": {"scope": legacy.conversation_scope.mode},
            "capabilities": {},
        },
        unsupported_fields=sorted(unsupported_fields),
    )
