from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.error_response_details_type_0 import ErrorResponseDetailsType0
    from ..models.validation_issue import ValidationIssue


T = TypeVar("T", bound="ErrorResponse")


@_attrs_define
class ErrorResponse:
    """
    Attributes:
        code (str):
        message (str):
        request_id (str):
        details (ErrorResponseDetailsType0 | None | Unset):
        issues (list[ValidationIssue] | None | Unset):
    """

    code: str
    message: str
    request_id: str
    details: ErrorResponseDetailsType0 | None | Unset = UNSET
    issues: list[ValidationIssue] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.error_response_details_type_0 import ErrorResponseDetailsType0

        code = self.code

        message = self.message

        request_id = self.request_id

        details: dict[str, Any] | None | Unset
        if isinstance(self.details, Unset):
            details = UNSET
        elif isinstance(self.details, ErrorResponseDetailsType0):
            details = self.details.to_dict()
        else:
            details = self.details

        issues: list[dict[str, Any]] | None | Unset
        if isinstance(self.issues, Unset):
            issues = UNSET
        elif isinstance(self.issues, list):
            issues = []
            for issues_type_0_item_data in self.issues:
                issues_type_0_item = issues_type_0_item_data.to_dict()
                issues.append(issues_type_0_item)

        else:
            issues = self.issues

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "code": code,
                "message": message,
                "request_id": request_id,
            }
        )
        if details is not UNSET:
            field_dict["details"] = details
        if issues is not UNSET:
            field_dict["issues"] = issues

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.error_response_details_type_0 import ErrorResponseDetailsType0
        from ..models.validation_issue import ValidationIssue

        d = dict(src_dict)
        code = d.pop("code")

        message = d.pop("message")

        request_id = d.pop("request_id")

        def _parse_details(data: object) -> ErrorResponseDetailsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                details_type_0 = ErrorResponseDetailsType0.from_dict(data)

                return details_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ErrorResponseDetailsType0 | None | Unset, data)

        details = _parse_details(d.pop("details", UNSET))

        def _parse_issues(data: object) -> list[ValidationIssue] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                issues_type_0 = []
                _issues_type_0 = data
                for issues_type_0_item_data in _issues_type_0:
                    issues_type_0_item = ValidationIssue.from_dict(
                        issues_type_0_item_data
                    )

                    issues_type_0.append(issues_type_0_item)

                return issues_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ValidationIssue] | None | Unset, data)

        issues = _parse_issues(d.pop("issues", UNSET))

        error_response = cls(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
            issues=issues,
        )

        return error_response
