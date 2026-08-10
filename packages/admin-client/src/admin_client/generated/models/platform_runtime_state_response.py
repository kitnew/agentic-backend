from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.platform_runtime_revision_response import (
        PlatformRuntimeRevisionResponse,
    )


T = TypeVar("T", bound="PlatformRuntimeStateResponse")


@_attrs_define
class PlatformRuntimeStateResponse:
    """
    Attributes:
        draft_revision (None | PlatformRuntimeRevisionResponse):
        latest_published_revision (None | PlatformRuntimeRevisionResponse):
    """

    draft_revision: None | PlatformRuntimeRevisionResponse
    latest_published_revision: None | PlatformRuntimeRevisionResponse
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_runtime_revision_response import (
            PlatformRuntimeRevisionResponse,
        )

        draft_revision: dict[str, Any] | None
        if isinstance(self.draft_revision, PlatformRuntimeRevisionResponse):
            draft_revision = self.draft_revision.to_dict()
        else:
            draft_revision = self.draft_revision

        latest_published_revision: dict[str, Any] | None
        if isinstance(self.latest_published_revision, PlatformRuntimeRevisionResponse):
            latest_published_revision = self.latest_published_revision.to_dict()
        else:
            latest_published_revision = self.latest_published_revision

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "draft_revision": draft_revision,
                "latest_published_revision": latest_published_revision,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_runtime_revision_response import (
            PlatformRuntimeRevisionResponse,
        )

        d = dict(src_dict)

        def _parse_draft_revision(
            data: object,
        ) -> None | PlatformRuntimeRevisionResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_revision_type_0 = PlatformRuntimeRevisionResponse.from_dict(data)

                return draft_revision_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PlatformRuntimeRevisionResponse, data)

        draft_revision = _parse_draft_revision(d.pop("draft_revision"))

        def _parse_latest_published_revision(
            data: object,
        ) -> None | PlatformRuntimeRevisionResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                latest_published_revision_type_0 = (
                    PlatformRuntimeRevisionResponse.from_dict(data)
                )

                return latest_published_revision_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PlatformRuntimeRevisionResponse, data)

        latest_published_revision = _parse_latest_published_revision(
            d.pop("latest_published_revision")
        )

        platform_runtime_state_response = cls(
            draft_revision=draft_revision,
            latest_published_revision=latest_published_revision,
        )

        platform_runtime_state_response.additional_properties = d
        return platform_runtime_state_response

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
