from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.versioned_component_draft_response import (
        VersionedComponentDraftResponse,
    )
    from ..models.versioned_component_response_scope import (
        VersionedComponentResponseScope,
    )
    from ..models.versioned_component_revision_response import (
        VersionedComponentRevisionResponse,
    )


T = TypeVar("T", bound="VersionedComponentResponse")


@_attrs_define
class VersionedComponentResponse:
    """
    Attributes:
        active (None | VersionedComponentRevisionResponse):
        draft (None | VersionedComponentDraftResponse):
        kind (str):
        scope (VersionedComponentResponseScope):
    """

    active: None | VersionedComponentRevisionResponse
    draft: None | VersionedComponentDraftResponse
    kind: str
    scope: VersionedComponentResponseScope

    def to_dict(self) -> dict[str, Any]:
        from ..models.versioned_component_draft_response import (
            VersionedComponentDraftResponse,
        )
        from ..models.versioned_component_revision_response import (
            VersionedComponentRevisionResponse,
        )

        active: dict[str, Any] | None
        if isinstance(self.active, VersionedComponentRevisionResponse):
            active = self.active.to_dict()
        else:
            active = self.active

        draft: dict[str, Any] | None
        if isinstance(self.draft, VersionedComponentDraftResponse):
            draft = self.draft.to_dict()
        else:
            draft = self.draft

        kind = self.kind

        scope = self.scope.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "active": active,
                "draft": draft,
                "kind": kind,
                "scope": scope,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.versioned_component_draft_response import (
            VersionedComponentDraftResponse,
        )
        from ..models.versioned_component_response_scope import (
            VersionedComponentResponseScope,
        )
        from ..models.versioned_component_revision_response import (
            VersionedComponentRevisionResponse,
        )

        d = dict(src_dict)

        def _parse_active(data: object) -> None | VersionedComponentRevisionResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_type_0 = VersionedComponentRevisionResponse.from_dict(data)

                return active_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | VersionedComponentRevisionResponse, data)

        active = _parse_active(d.pop("active"))

        def _parse_draft(data: object) -> None | VersionedComponentDraftResponse:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = VersionedComponentDraftResponse.from_dict(data)

                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | VersionedComponentDraftResponse, data)

        draft = _parse_draft(d.pop("draft"))

        kind = d.pop("kind")

        scope = VersionedComponentResponseScope.from_dict(d.pop("scope"))

        versioned_component_response = cls(
            active=active,
            draft=draft,
            kind=kind,
            scope=scope,
        )

        return versioned_component_response
