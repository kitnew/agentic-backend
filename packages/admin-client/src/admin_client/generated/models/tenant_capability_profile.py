from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.capability_business_policy import CapabilityBusinessPolicy
    from ..models.google_sheets_append_execution import GoogleSheetsAppendExecution
    from ..models.managed_webhook_execution import ManagedWebhookExecution
    from ..models.tenant_capability_profile_agent_input_schema import (
        TenantCapabilityProfileAgentInputSchema,
    )
    from ..models.tenant_capability_profile_validation_fixtures_item import (
        TenantCapabilityProfileValidationFixturesItem,
    )


T = TypeVar("T", bound="TenantCapabilityProfile")


@_attrs_define
class TenantCapabilityProfile:
    """
    Attributes:
        agent_input_schema (TenantCapabilityProfileAgentInputSchema):
        announcement (str):
        description (str):
        enabled (bool):
        execution (GoogleSheetsAppendExecution | ManagedWebhookExecution):
        semantic_version (int):
        validation_fixtures (list[TenantCapabilityProfileValidationFixturesItem]):
        business_policy (CapabilityBusinessPolicy | Unset):
    """

    agent_input_schema: TenantCapabilityProfileAgentInputSchema
    announcement: str
    description: str
    enabled: bool
    execution: GoogleSheetsAppendExecution | ManagedWebhookExecution
    semantic_version: int
    validation_fixtures: list[TenantCapabilityProfileValidationFixturesItem]
    business_policy: CapabilityBusinessPolicy | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.google_sheets_append_execution import GoogleSheetsAppendExecution

        agent_input_schema = self.agent_input_schema.to_dict()

        announcement = self.announcement

        description = self.description

        enabled = self.enabled

        execution: dict[str, Any]
        if isinstance(self.execution, GoogleSheetsAppendExecution):
            execution = self.execution.to_dict()
        else:
            execution = self.execution.to_dict()

        semantic_version = self.semantic_version

        validation_fixtures = []
        for validation_fixtures_item_data in self.validation_fixtures:
            validation_fixtures_item = validation_fixtures_item_data.to_dict()
            validation_fixtures.append(validation_fixtures_item)

        business_policy: dict[str, Any] | Unset = UNSET
        if not isinstance(self.business_policy, Unset):
            business_policy = self.business_policy.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "agent_input_schema": agent_input_schema,
                "announcement": announcement,
                "description": description,
                "enabled": enabled,
                "execution": execution,
                "semantic_version": semantic_version,
                "validation_fixtures": validation_fixtures,
            }
        )
        if business_policy is not UNSET:
            field_dict["business_policy"] = business_policy

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.capability_business_policy import CapabilityBusinessPolicy
        from ..models.google_sheets_append_execution import GoogleSheetsAppendExecution
        from ..models.managed_webhook_execution import ManagedWebhookExecution
        from ..models.tenant_capability_profile_agent_input_schema import (
            TenantCapabilityProfileAgentInputSchema,
        )
        from ..models.tenant_capability_profile_validation_fixtures_item import (
            TenantCapabilityProfileValidationFixturesItem,
        )

        d = dict(src_dict)
        agent_input_schema = TenantCapabilityProfileAgentInputSchema.from_dict(
            d.pop("agent_input_schema")
        )

        announcement = d.pop("announcement")

        description = d.pop("description")

        enabled = d.pop("enabled")

        def _parse_execution(
            data: object,
        ) -> GoogleSheetsAppendExecution | ManagedWebhookExecution:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                execution_type_0 = GoogleSheetsAppendExecution.from_dict(data)

                return execution_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            execution_type_1 = ManagedWebhookExecution.from_dict(data)

            return execution_type_1

        execution = _parse_execution(d.pop("execution"))

        semantic_version = d.pop("semantic_version")

        validation_fixtures = []
        _validation_fixtures = d.pop("validation_fixtures")
        for validation_fixtures_item_data in _validation_fixtures:
            validation_fixtures_item = (
                TenantCapabilityProfileValidationFixturesItem.from_dict(
                    validation_fixtures_item_data
                )
            )

            validation_fixtures.append(validation_fixtures_item)

        _business_policy = d.pop("business_policy", UNSET)
        business_policy: CapabilityBusinessPolicy | Unset
        if isinstance(_business_policy, Unset):
            business_policy = UNSET
        else:
            business_policy = CapabilityBusinessPolicy.from_dict(_business_policy)

        tenant_capability_profile = cls(
            agent_input_schema=agent_input_schema,
            announcement=announcement,
            description=description,
            enabled=enabled,
            execution=execution,
            semantic_version=semantic_version,
            validation_fixtures=validation_fixtures,
            business_policy=business_policy,
        )

        return tenant_capability_profile
