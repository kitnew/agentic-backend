from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.integration_connection_status import IntegrationConnectionStatus
from ..types import UNSET, Unset

T = TypeVar("T", bound="UpdateIntegrationConnectionRequest")


@_attrs_define
class UpdateIntegrationConnectionRequest:
    """
    Attributes:
        credential_ref (None | str | Unset):
        status (IntegrationConnectionStatus | None | Unset):
    """

    credential_ref: None | str | Unset = UNSET
    status: IntegrationConnectionStatus | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        credential_ref: None | str | Unset
        if isinstance(self.credential_ref, Unset):
            credential_ref = UNSET
        else:
            credential_ref = self.credential_ref

        status: None | str | Unset
        if isinstance(self.status, Unset):
            status = UNSET
        elif isinstance(self.status, IntegrationConnectionStatus):
            status = self.status.value
        else:
            status = self.status

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if credential_ref is not UNSET:
            field_dict["credential_ref"] = credential_ref
        if status is not UNSET:
            field_dict["status"] = status

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)

        def _parse_credential_ref(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        credential_ref = _parse_credential_ref(d.pop("credential_ref", UNSET))

        def _parse_status(data: object) -> IntegrationConnectionStatus | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                status_type_0 = IntegrationConnectionStatus(data)

                return status_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(IntegrationConnectionStatus | None | Unset, data)

        status = _parse_status(d.pop("status", UNSET))

        update_integration_connection_request = cls(
            credential_ref=credential_ref,
            status=status,
        )

        return update_integration_connection_request
