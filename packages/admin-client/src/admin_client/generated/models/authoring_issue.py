from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

T = TypeVar("T", bound="AuthoringIssue")


@_attrs_define
class AuthoringIssue:
    """
    Attributes:
        code (str):
        message (str):
        path (str | Unset):  Default: ''.
    """

    code: str
    message: str
    path: str | Unset = ""

    def to_dict(self) -> dict[str, Any]:
        code = self.code

        message = self.message

        path = self.path

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "code": code,
                "message": message,
            }
        )
        if path is not UNSET:
            field_dict["path"] = path

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        d = dict(src_dict)
        code = d.pop("code")

        message = d.pop("message")

        path = d.pop("path", UNSET)

        authoring_issue = cls(
            code=code,
            message=message,
            path=path,
        )

        return authoring_issue
