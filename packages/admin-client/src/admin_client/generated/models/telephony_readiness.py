from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

T = TypeVar("T", bound="TelephonyReadiness")


@_attrs_define
class TelephonyReadiness:
    """
    Attributes:
        human_handoff (str):
        incoming_calls (str):
        outgoing_calls (str):
        phone_number (str):
    """

    human_handoff: str
    incoming_calls: str
    outgoing_calls: str
    phone_number: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        human_handoff = self.human_handoff

        incoming_calls = self.incoming_calls

        outgoing_calls = self.outgoing_calls

        phone_number = self.phone_number

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "human_handoff": human_handoff,
                "incoming_calls": incoming_calls,
                "outgoing_calls": outgoing_calls,
                "phone_number": phone_number,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        human_handoff = d.pop("human_handoff")

        incoming_calls = d.pop("incoming_calls")

        outgoing_calls = d.pop("outgoing_calls")

        phone_number = d.pop("phone_number")

        telephony_readiness = cls(
            human_handoff=human_handoff,
            incoming_calls=incoming_calls,
            outgoing_calls=outgoing_calls,
            phone_number=phone_number,
        )

        telephony_readiness.additional_properties = d
        return telephony_readiness

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
