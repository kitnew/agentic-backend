from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.platform_telephony_response_diagnostics import (
        PlatformTelephonyResponseDiagnostics,
    )


T = TypeVar("T", bound="PlatformTelephonyResponse")


@_attrs_define
class PlatformTelephonyResponse:
    """
    Attributes:
        diagnostics (PlatformTelephonyResponseDiagnostics):
        dispatch (str):
        inbound (str):
        last_error (None | str):
        last_reconciled_at (datetime.datetime | None):
        outbound (str):
        overall (str):
        provider (str):
    """

    diagnostics: PlatformTelephonyResponseDiagnostics
    dispatch: str
    inbound: str
    last_error: None | str
    last_reconciled_at: datetime.datetime | None
    outbound: str
    overall: str
    provider: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        diagnostics = self.diagnostics.to_dict()

        dispatch = self.dispatch

        inbound = self.inbound

        last_error: None | str
        last_error = self.last_error

        last_reconciled_at: None | str
        if isinstance(self.last_reconciled_at, datetime.datetime):
            last_reconciled_at = self.last_reconciled_at.isoformat()
        else:
            last_reconciled_at = self.last_reconciled_at

        outbound = self.outbound

        overall = self.overall

        provider = self.provider

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "diagnostics": diagnostics,
                "dispatch": dispatch,
                "inbound": inbound,
                "last_error": last_error,
                "last_reconciled_at": last_reconciled_at,
                "outbound": outbound,
                "overall": overall,
                "provider": provider,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_telephony_response_diagnostics import (
            PlatformTelephonyResponseDiagnostics,
        )

        d = dict(src_dict)
        diagnostics = PlatformTelephonyResponseDiagnostics.from_dict(
            d.pop("diagnostics")
        )

        dispatch = d.pop("dispatch")

        inbound = d.pop("inbound")

        def _parse_last_error(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        last_error = _parse_last_error(d.pop("last_error"))

        def _parse_last_reconciled_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_reconciled_at_type_0 = datetime.datetime.fromisoformat(data)

                return last_reconciled_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        last_reconciled_at = _parse_last_reconciled_at(d.pop("last_reconciled_at"))

        outbound = d.pop("outbound")

        overall = d.pop("overall")

        provider = d.pop("provider")

        platform_telephony_response = cls(
            diagnostics=diagnostics,
            dispatch=dispatch,
            inbound=inbound,
            last_error=last_error,
            last_reconciled_at=last_reconciled_at,
            outbound=outbound,
            overall=overall,
            provider=provider,
        )

        platform_telephony_response.additional_properties = d
        return platform_telephony_response

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
