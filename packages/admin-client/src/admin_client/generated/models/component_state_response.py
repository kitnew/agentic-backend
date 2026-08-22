from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.component_draft_response import ComponentDraftResponse
    from ..models.component_revision_response import ComponentRevisionResponse


T = TypeVar("T", bound="ComponentStateResponse")


@_attrs_define
class ComponentStateResponse:
    """
    Attributes:
        active_revision (ComponentRevisionResponse | None):
        component (str):
        draft (ComponentDraftResponse | None):
    """

    active_revision: ComponentRevisionResponse | None
    component: str
    draft: ComponentDraftResponse | None
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.component_draft_response import ComponentDraftResponse
        from ..models.component_revision_response import ComponentRevisionResponse

        active_revision: dict[str, Any] | None
        if isinstance(self.active_revision, ComponentRevisionResponse):
            active_revision = self.active_revision.to_dict()
        else:
            active_revision = self.active_revision

        component = self.component

        draft: dict[str, Any] | None
        if isinstance(self.draft, ComponentDraftResponse):
            draft = self.draft.to_dict()
        else:
            draft = self.draft

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "active_revision": active_revision,
                "component": component,
                "draft": draft,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.component_draft_response import ComponentDraftResponse
        from ..models.component_revision_response import ComponentRevisionResponse

        d = dict(src_dict)

        def _parse_active_revision(data: object) -> ComponentRevisionResponse | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_revision_type_0 = ComponentRevisionResponse.from_dict(data)

                return active_revision_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ComponentRevisionResponse | None, data)

        active_revision = _parse_active_revision(d.pop("active_revision"))

        component = d.pop("component")

        def _parse_draft(data: object) -> ComponentDraftResponse | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = ComponentDraftResponse.from_dict(data)

                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ComponentDraftResponse | None, data)

        draft = _parse_draft(d.pop("draft"))

        component_state_response = cls(
            active_revision=active_revision,
            component=component,
            draft=draft,
        )

        component_state_response.additional_properties = d
        return component_state_response

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
