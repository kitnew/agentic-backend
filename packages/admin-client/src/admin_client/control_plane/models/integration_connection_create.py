from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.integration_connection_create_config import (
        IntegrationConnectionCreateConfig,
    )


T = TypeVar("T", bound="IntegrationConnectionCreate")


@_attrs_define
class IntegrationConnectionCreate:
    """
    Attributes:
        config (IntegrationConnectionCreateConfig):
        integration_kind (str):
        key (str):
        credential_ref (None | Unset | UUID):
    """

    config: IntegrationConnectionCreateConfig
    integration_kind: str
    key: str
    credential_ref: None | Unset | UUID = UNSET

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        integration_kind = self.integration_kind

        key = self.key

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
                "integration_kind": integration_kind,
                "key": key,
            }
        )
        if credential_ref is not UNSET:
            field_dict["credential_ref"] = credential_ref

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.integration_connection_create_config import (
            IntegrationConnectionCreateConfig,
        )

        d = dict(src_dict)
        config = IntegrationConnectionCreateConfig.from_dict(d.pop("config"))

        integration_kind = d.pop("integration_kind")

        key = d.pop("key")

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

        integration_connection_create = cls(
            config=config,
            integration_kind=integration_kind,
            key=key,
            credential_ref=credential_ref,
        )

        return integration_connection_create
