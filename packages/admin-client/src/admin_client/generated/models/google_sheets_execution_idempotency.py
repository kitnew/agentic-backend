from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

T = TypeVar("T", bound="GoogleSheetsExecutionIdempotency")


@_attrs_define
class GoogleSheetsExecutionIdempotency:
    """
    Attributes:
        lookup_range (str):
        operation_id_column_index (int):
    """

    lookup_range: str
    operation_id_column_index: int

    def to_dict(self) -> dict[str, Any]:
        lookup_range = self.lookup_range

        operation_id_column_index = self.operation_id_column_index

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "lookup_range": lookup_range,
                "operation_id_column_index": operation_id_column_index,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        lookup_range = d.pop("lookup_range")

        operation_id_column_index = d.pop("operation_id_column_index")

        google_sheets_execution_idempotency = cls(
            lookup_range=lookup_range,
            operation_id_column_index=operation_id_column_index,
        )

        return google_sheets_execution_idempotency
