from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.authoring_change_operation import AuthoringChangeOperation
from ..types import UNSET, Unset

T = TypeVar("T", bound="AuthoringChange")


@_attrs_define
class AuthoringChange:
    """
    Attributes:
        operation (AuthoringChangeOperation):
        path (str):
        after (Any | None | Unset):
        before (Any | None | Unset):
    """

    operation: AuthoringChangeOperation
    path: str
    after: Any | None | Unset = UNSET
    before: Any | None | Unset = UNSET

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
        operation = AuthoringChangeOperation(d.pop("operation"))

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

        authoring_change = cls(
            operation=operation,
            path=path,
            after=after,
            before=before,
        )

        return authoring_change
