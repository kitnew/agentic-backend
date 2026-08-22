from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.component_draft_expectation import ComponentDraftExpectation


T = TypeVar("T", bound="PublishAllRequest")


@_attrs_define
class PublishAllRequest:
    """
    Attributes:
        drafts (list[ComponentDraftExpectation]):
        comment (None | str | Unset):
    """

    drafts: list[ComponentDraftExpectation]
    comment: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        drafts = []
        for drafts_item_data in self.drafts:
            drafts_item = drafts_item_data.to_dict()
            drafts.append(drafts_item)

        comment: None | str | Unset
        if isinstance(self.comment, Unset):
            comment = UNSET
        else:
            comment = self.comment

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "drafts": drafts,
            }
        )
        if comment is not UNSET:
            field_dict["comment"] = comment

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.component_draft_expectation import ComponentDraftExpectation

        d = dict(src_dict)
        drafts = []
        _drafts = d.pop("drafts")
        for drafts_item_data in _drafts:
            drafts_item = ComponentDraftExpectation.from_dict(drafts_item_data)

            drafts.append(drafts_item)

        def _parse_comment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        comment = _parse_comment(d.pop("comment", UNSET))

        publish_all_request = cls(
            drafts=drafts,
            comment=comment,
        )

        return publish_all_request
