from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.integration_connection_update_config import (
        IntegrationConnectionUpdateConfig,
    )


T = TypeVar("T", bound="IntegrationConnectionUpdate")


@_attrs_define
class IntegrationConnectionUpdate:
    """
    Attributes:
        config (IntegrationConnectionUpdateConfig):
        credential_ref (None | Unset | UUID):
    """

    config: IntegrationConnectionUpdateConfig
    credential_ref: None | Unset | UUID = UNSET

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        credential_ref: None | str | Unset
        if isinstance(self.credential_ref, Unset):
            credential_ref = UNSET
        elif isinstance(self.credential_ref, UUID):
            credential_ref = str(self.credential_ref)
        else:
            credential_ref = self.credential_ref

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "config": config,
            }
        )
        if credential_ref is not UNSET:
            field_dict["credential_ref"] = credential_ref

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.integration_connection_update_config import (
            IntegrationConnectionUpdateConfig,
        )

        d = dict(src_dict)
        config = IntegrationConnectionUpdateConfig.from_dict(d.pop("config"))

        def _parse_credential_ref(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                credential_ref_type_0 = UUID(data)

                return credential_ref_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        credential_ref = _parse_credential_ref(d.pop("credential_ref", UNSET))

        integration_connection_update = cls(
            config=config,
            credential_ref=credential_ref,
        )

        return integration_connection_update
