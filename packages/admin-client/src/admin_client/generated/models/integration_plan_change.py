from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.integration_plan_change_operation import IntegrationPlanChangeOperation
from ..types import UNSET, Unset

T = TypeVar("T", bound="IntegrationPlanChange")


@_attrs_define
class IntegrationPlanChange:
    """
    Attributes:
        operation (IntegrationPlanChangeOperation):
        path (str):
        after (Any | None | Unset):
        before (Any | None | Unset):
    """

    operation: IntegrationPlanChangeOperation
    path: str
    after: Any | None | Unset = UNSET
    before: Any | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        operation = self.operation.value

        path = self.path

        after: Any | None | Unset
        if isinstance(self.after, Unset):
            after = UNSET
        else:
            after = self.after

        before: Any | None | Unset
        if isinstance(self.before, Unset):
            before = UNSET
        else:
            before = self.before

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "operation": operation,
                "path": path,
            }
        )
        if after is not UNSET:
            field_dict["after"] = after
        if before is not UNSET:
            field_dict["before"] = before

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        operation = IntegrationPlanChangeOperation(d.pop("operation"))

        path = d.pop("path")

        def _parse_after(data: object) -> Any | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Any | None | Unset, data)

        after = _parse_after(d.pop("after", UNSET))

        def _parse_before(data: object) -> Any | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Any | None | Unset, data)

        before = _parse_before(d.pop("before", UNSET))

        integration_plan_change = cls(
            operation=operation,
            path=path,
            after=after,
            before=before,
        )

        integration_plan_change.additional_properties = d
        return integration_plan_change

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
