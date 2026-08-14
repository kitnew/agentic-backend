from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.managed_webhook_response_config_mode import (
    ManagedWebhookResponseConfigMode,
)
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.managed_webhook_response_config_output_schema import (
        ManagedWebhookResponseConfigOutputSchema,
    )
    from ..models.managed_webhook_response_config_success_output_type_0 import (
        ManagedWebhookResponseConfigSuccessOutputType0,
    )


T = TypeVar("T", bound="ManagedWebhookResponseConfig")


@_attrs_define
class ManagedWebhookResponseConfig:
    """
    Attributes:
        mode (ManagedWebhookResponseConfigMode):
        output_schema (ManagedWebhookResponseConfigOutputSchema):
        mapping (None | str | Unset):
        success_output (ManagedWebhookResponseConfigSuccessOutputType0 | None | Unset):
    """

    mode: ManagedWebhookResponseConfigMode
    output_schema: ManagedWebhookResponseConfigOutputSchema
    mapping: None | str | Unset = UNSET
    success_output: ManagedWebhookResponseConfigSuccessOutputType0 | None | Unset = (
        UNSET
    )

    def to_dict(self) -> dict[str, Any]:
        from ..models.managed_webhook_response_config_success_output_type_0 import (
            ManagedWebhookResponseConfigSuccessOutputType0,
        )

        mode = self.mode.value

        output_schema = self.output_schema.to_dict()

        mapping: None | str | Unset
        if isinstance(self.mapping, Unset):
            mapping = UNSET
        else:
            mapping = self.mapping

        success_output: dict[str, Any] | None | Unset
        if isinstance(self.success_output, Unset):
            success_output = UNSET
        elif isinstance(
            self.success_output, ManagedWebhookResponseConfigSuccessOutputType0
        ):
            success_output = self.success_output.to_dict()
        else:
            success_output = self.success_output

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "mode": mode,
                "output_schema": output_schema,
            }
        )
        if mapping is not UNSET:
            field_dict["mapping"] = mapping
        if success_output is not UNSET:
            field_dict["success_output"] = success_output

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.managed_webhook_response_config_output_schema import (
            ManagedWebhookResponseConfigOutputSchema,
        )
        from ..models.managed_webhook_response_config_success_output_type_0 import (
            ManagedWebhookResponseConfigSuccessOutputType0,
        )

        d = dict(src_dict)
        mode = ManagedWebhookResponseConfigMode(d.pop("mode"))

        output_schema = ManagedWebhookResponseConfigOutputSchema.from_dict(
            d.pop("output_schema")
        )

        def _parse_mapping(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        mapping = _parse_mapping(d.pop("mapping", UNSET))

        def _parse_success_output(
            data: object,
        ) -> ManagedWebhookResponseConfigSuccessOutputType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                success_output_type_0 = (
                    ManagedWebhookResponseConfigSuccessOutputType0.from_dict(data)
                )

                return success_output_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                ManagedWebhookResponseConfigSuccessOutputType0 | None | Unset, data
            )

        success_output = _parse_success_output(d.pop("success_output", UNSET))

        managed_webhook_response_config = cls(
            mode=mode,
            output_schema=output_schema,
            mapping=mapping,
            success_output=success_output,
        )

        return managed_webhook_response_config
