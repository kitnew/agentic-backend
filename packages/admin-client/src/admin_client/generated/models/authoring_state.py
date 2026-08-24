from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.authoring_state_source import AuthoringStateSource
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.authoring_draft_metadata import AuthoringDraftMetadata
    from ..models.authoring_published_metadata import AuthoringPublishedMetadata


T = TypeVar("T", bound="AuthoringState")


@_attrs_define
class AuthoringState:
    """
    Attributes:
        source (AuthoringStateSource):
        draft (AuthoringDraftMetadata | None | Unset):
        etag (None | str | Unset):
        published (AuthoringPublishedMetadata | None | Unset):
        published_value (Any | None | Unset):
        value (Any | None | Unset):
    """

    source: AuthoringStateSource
    draft: AuthoringDraftMetadata | None | Unset = UNSET
    etag: None | str | Unset = UNSET
    published: AuthoringPublishedMetadata | None | Unset = UNSET
    published_value: Any | None | Unset = UNSET
    value: Any | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.authoring_draft_metadata import AuthoringDraftMetadata
        from ..models.authoring_published_metadata import AuthoringPublishedMetadata

        source = self.source.value

        draft: dict[str, Any] | None | Unset
        if isinstance(self.draft, Unset):
            draft = UNSET
        elif isinstance(self.draft, AuthoringDraftMetadata):
            draft = self.draft.to_dict()
        else:
            draft = self.draft

        etag: None | str | Unset
        if isinstance(self.etag, Unset):
            etag = UNSET
        else:
            etag = self.etag

        published: dict[str, Any] | None | Unset
        if isinstance(self.published, Unset):
            published = UNSET
        elif isinstance(self.published, AuthoringPublishedMetadata):
            published = self.published.to_dict()
        else:
            published = self.published

        published_value: Any | None | Unset
        if isinstance(self.published_value, Unset):
            published_value = UNSET
        else:
            published_value = self.published_value

        value: Any | None | Unset
        if isinstance(self.value, Unset):
            value = UNSET
        else:
            value = self.value

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "source": source,
            }
        )
        if draft is not UNSET:
            field_dict["draft"] = draft
        if etag is not UNSET:
            field_dict["etag"] = etag
        if published is not UNSET:
            field_dict["published"] = published
        if published_value is not UNSET:
            field_dict["published_value"] = published_value
        if value is not UNSET:
            field_dict["value"] = value

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.authoring_draft_metadata import AuthoringDraftMetadata
        from ..models.authoring_published_metadata import AuthoringPublishedMetadata

        d = dict(src_dict)
        source = AuthoringStateSource(d.pop("source"))

        def _parse_draft(data: object) -> AuthoringDraftMetadata | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                draft_type_0 = AuthoringDraftMetadata.from_dict(data)

                return draft_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AuthoringDraftMetadata | None | Unset, data)

        draft = _parse_draft(d.pop("draft", UNSET))

        def _parse_etag(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        etag = _parse_etag(d.pop("etag", UNSET))

        def _parse_published(data: object) -> AuthoringPublishedMetadata | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                published_type_0 = AuthoringPublishedMetadata.from_dict(data)

                return published_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AuthoringPublishedMetadata | None | Unset, data)

        published = _parse_published(d.pop("published", UNSET))

        def _parse_published_value(data: object) -> Any | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Any | None | Unset, data)

        published_value = _parse_published_value(d.pop("published_value", UNSET))

        def _parse_value(data: object) -> Any | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(Any | None | Unset, data)

        value = _parse_value(d.pop("value", UNSET))

        authoring_state = cls(
            source=source,
            draft=draft,
            etag=etag,
            published=published,
            published_value=published_value,
            value=value,
        )

        return authoring_state
