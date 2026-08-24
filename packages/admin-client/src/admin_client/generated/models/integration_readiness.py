from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

from ..models.integration_readiness_configuration import (
    IntegrationReadinessConfiguration,
)
from ..models.integration_readiness_credentials import IntegrationReadinessCredentials
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.integration_issue import IntegrationIssue


T = TypeVar("T", bound="IntegrationReadiness")


@_attrs_define
class IntegrationReadiness:
    """
    Attributes:
        configuration (IntegrationReadinessConfiguration):
        credentials (IntegrationReadinessCredentials):
        ready (bool):
        usable (bool):
        issues (list[IntegrationIssue] | Unset):
    """

    configuration: IntegrationReadinessConfiguration
    credentials: IntegrationReadinessCredentials
    ready: bool
    usable: bool
    issues: list[IntegrationIssue] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        configuration = self.configuration.value

        credentials = self.credentials.value

        ready = self.ready

        usable = self.usable

        issues: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.issues, Unset):
            issues = []
            for issues_item_data in self.issues:
                issues_item = issues_item_data.to_dict()
                issues.append(issues_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "configuration": configuration,
                "credentials": credentials,
                "ready": ready,
                "usable": usable,
            }
        )
        if issues is not UNSET:
            field_dict["issues"] = issues

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.integration_issue import IntegrationIssue

        d = dict(src_dict)
        configuration = IntegrationReadinessConfiguration(d.pop("configuration"))

        credentials = IntegrationReadinessCredentials(d.pop("credentials"))

        ready = d.pop("ready")

        usable = d.pop("usable")

        _issues = d.pop("issues", UNSET)
        issues: list[IntegrationIssue] | Unset = UNSET
        if _issues is not UNSET:
            issues = []
            for issues_item_data in _issues:
                issues_item = IntegrationIssue.from_dict(issues_item_data)

                issues.append(issues_item)

        integration_readiness = cls(
            configuration=configuration,
            credentials=credentials,
            ready=ready,
            usable=usable,
            issues=issues,
        )

        integration_readiness.additional_properties = d
        return integration_readiness

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
