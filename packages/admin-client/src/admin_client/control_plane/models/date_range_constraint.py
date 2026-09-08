from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="DateRangeConstraint")


@_attrs_define
class DateRangeConstraint:
    """
    Attributes:
        end (str):
        kind (Literal['date_range']):
        start (str):
        start_not_in_past (bool | Unset):  Default: False.
    """

    end: str
    kind: Literal["date_range"]
    start: str
    start_not_in_past: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        end = self.end

        kind = self.kind

        start = self.start

        start_not_in_past = self.start_not_in_past

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "end": end,
                "kind": kind,
                "start": start,
            }
        )
        if start_not_in_past is not UNSET:
            field_dict["start_not_in_past"] = start_not_in_past

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        end = d.pop("end")

        kind = cast(Literal["date_range"], d.pop("kind"))
        if kind != "date_range":
            raise ValueError(f"kind must match const 'date_range', got '{kind}'")

        start = d.pop("start")

        start_not_in_past = d.pop("start_not_in_past", UNSET)

        date_range_constraint = cls(
            end=end,
            kind=kind,
            start=start,
            start_not_in_past=start_not_in_past,
        )

        return date_range_constraint
