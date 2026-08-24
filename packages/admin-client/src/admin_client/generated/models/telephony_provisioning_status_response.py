from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="TelephonyProvisioningStatusResponse")


@_attrs_define
class TelephonyProvisioningStatusResponse:
    """
    Attributes:
        state (str):
        last_error (None | str | Unset):
        last_reconciled_at (datetime.datetime | None | Unset):
    """

    state: str
    last_error: None | str | Unset = UNSET
    last_reconciled_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        state = self.state

        last_error: None | str | Unset
        if isinstance(self.last_error, Unset):
            last_error = UNSET
        else:
            last_error = self.last_error

        last_reconciled_at: None | str | Unset
        if isinstance(self.last_reconciled_at, Unset):
            last_reconciled_at = UNSET
        elif isinstance(self.last_reconciled_at, datetime.datetime):
            last_reconciled_at = self.last_reconciled_at.isoformat()
        else:
            last_reconciled_at = self.last_reconciled_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "state": state,
            }
        )
        if last_error is not UNSET:
            field_dict["last_error"] = last_error
        if last_reconciled_at is not UNSET:
            field_dict["last_reconciled_at"] = last_reconciled_at

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        state = d.pop("state")

        def _parse_last_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_error = _parse_last_error(d.pop("last_error", UNSET))

        def _parse_last_reconciled_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_reconciled_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_reconciled_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_reconciled_at = _parse_last_reconciled_at(
            d.pop("last_reconciled_at", UNSET)
        )

        telephony_provisioning_status_response = cls(
            state=state,
            last_error=last_error,
            last_reconciled_at=last_reconciled_at,
        )

        telephony_provisioning_status_response.additional_properties = d
        return telephony_provisioning_status_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
