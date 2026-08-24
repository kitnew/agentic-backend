from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.http_operation import HttpOperation
    from ..models.tenant_capability_authoring_agent_input_schema import (
        TenantCapabilityAuthoringAgentInputSchema,
    )
    from ..models.tenant_capability_authoring_announcement_type_1 import (
        TenantCapabilityAuthoringAnnouncementType1,
    )
    from ..models.tenant_capability_authoring_bindings import (
        TenantCapabilityAuthoringBindings,
    )
    from ..models.tenant_capability_authoring_business_policy import (
        TenantCapabilityAuthoringBusinessPolicy,
    )
    from ..models.tenant_capability_authoring_result_schema_type_0 import (
        TenantCapabilityAuthoringResultSchemaType0,
    )


T = TypeVar("T", bound="TenantCapabilityAuthoring")


@_attrs_define
class TenantCapabilityAuthoring:
    """
    Attributes:
        agent_input_schema (TenantCapabilityAuthoringAgentInputSchema):
        announcement (str | TenantCapabilityAuthoringAnnouncementType1):
        description (str):
        execution (HttpOperation):
        bindings (TenantCapabilityAuthoringBindings | Unset):
        business_policy (TenantCapabilityAuthoringBusinessPolicy | Unset):
        enabled (bool | Unset):  Default: True.
        result_schema (None | TenantCapabilityAuthoringResultSchemaType0 | Unset):
    """

    agent_input_schema: TenantCapabilityAuthoringAgentInputSchema
    announcement: str | TenantCapabilityAuthoringAnnouncementType1
    description: str
    execution: HttpOperation
    bindings: TenantCapabilityAuthoringBindings | Unset = UNSET
    business_policy: TenantCapabilityAuthoringBusinessPolicy | Unset = UNSET
    enabled: bool | Unset = True
    result_schema: None | TenantCapabilityAuthoringResultSchemaType0 | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.tenant_capability_authoring_announcement_type_1 import (
            TenantCapabilityAuthoringAnnouncementType1,
        )
        from ..models.tenant_capability_authoring_result_schema_type_0 import (
            TenantCapabilityAuthoringResultSchemaType0,
        )

        agent_input_schema = self.agent_input_schema.to_dict()

        announcement: dict[str, Any] | str
        if isinstance(self.announcement, TenantCapabilityAuthoringAnnouncementType1):
            announcement = self.announcement.to_dict()
        else:
            announcement = self.announcement

        description = self.description

        execution = self.execution.to_dict()

        bindings: dict[str, Any] | Unset = UNSET
        if not isinstance(self.bindings, Unset):
            bindings = self.bindings.to_dict()

        business_policy: dict[str, Any] | Unset = UNSET
        if not isinstance(self.business_policy, Unset):
            business_policy = self.business_policy.to_dict()

        enabled = self.enabled

        result_schema: dict[str, Any] | None | Unset
        if isinstance(self.result_schema, Unset):
            result_schema = UNSET
        elif isinstance(self.result_schema, TenantCapabilityAuthoringResultSchemaType0):
            result_schema = self.result_schema.to_dict()
        else:
            result_schema = self.result_schema

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "agent_input_schema": agent_input_schema,
                "announcement": announcement,
                "description": description,
                "execution": execution,
            }
        )
        if bindings is not UNSET:
            field_dict["bindings"] = bindings
        if business_policy is not UNSET:
            field_dict["business_policy"] = business_policy
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if result_schema is not UNSET:
            field_dict["result_schema"] = result_schema

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.http_operation import HttpOperation
        from ..models.tenant_capability_authoring_agent_input_schema import (
            TenantCapabilityAuthoringAgentInputSchema,
        )
        from ..models.tenant_capability_authoring_announcement_type_1 import (
            TenantCapabilityAuthoringAnnouncementType1,
        )
        from ..models.tenant_capability_authoring_bindings import (
            TenantCapabilityAuthoringBindings,
        )
        from ..models.tenant_capability_authoring_business_policy import (
            TenantCapabilityAuthoringBusinessPolicy,
        )
        from ..models.tenant_capability_authoring_result_schema_type_0 import (
            TenantCapabilityAuthoringResultSchemaType0,
        )

        d = dict(src_dict)
        agent_input_schema = TenantCapabilityAuthoringAgentInputSchema.from_dict(
            d.pop("agent_input_schema")
        )

        def _parse_announcement(
            data: object,
        ) -> str | TenantCapabilityAuthoringAnnouncementType1:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                announcement_type_1 = (
                    TenantCapabilityAuthoringAnnouncementType1.from_dict(data)
                )

                return announcement_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(str | TenantCapabilityAuthoringAnnouncementType1, data)

        announcement = _parse_announcement(d.pop("announcement"))

        description = d.pop("description")

        execution = HttpOperation.from_dict(d.pop("execution"))

        _bindings = d.pop("bindings", UNSET)
        bindings: TenantCapabilityAuthoringBindings | Unset
        if isinstance(_bindings, Unset):
            bindings = UNSET
        else:
            bindings = TenantCapabilityAuthoringBindings.from_dict(_bindings)

        _business_policy = d.pop("business_policy", UNSET)
        business_policy: TenantCapabilityAuthoringBusinessPolicy | Unset
        if isinstance(_business_policy, Unset):
            business_policy = UNSET
        else:
            business_policy = TenantCapabilityAuthoringBusinessPolicy.from_dict(
                _business_policy
            )

        enabled = d.pop("enabled", UNSET)

        def _parse_result_schema(
            data: object,
        ) -> None | TenantCapabilityAuthoringResultSchemaType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                result_schema_type_0 = (
                    TenantCapabilityAuthoringResultSchemaType0.from_dict(data)
                )

                return result_schema_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TenantCapabilityAuthoringResultSchemaType0 | Unset, data)

        result_schema = _parse_result_schema(d.pop("result_schema", UNSET))

        tenant_capability_authoring = cls(
            agent_input_schema=agent_input_schema,
            announcement=announcement,
            description=description,
            execution=execution,
            bindings=bindings,
            business_policy=business_policy,
            enabled=enabled,
            result_schema=result_schema,
        )

        return tenant_capability_authoring
