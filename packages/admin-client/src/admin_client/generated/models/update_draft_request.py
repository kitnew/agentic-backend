from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.update_draft_request_config_type_0 import (
        UpdateDraftRequestConfigType0,
    )


T = TypeVar("T", bound="UpdateDraftRequest")


@_attrs_define
class UpdateDraftRequest:
    """
    Attributes:
        comment (None | str | Unset):
        config (None | Unset | UpdateDraftRequestConfigType0):
        schema_version (int | None | Unset):
    """

    comment: None | str | Unset = UNSET
    config: None | Unset | UpdateDraftRequestConfigType0 = UNSET
    schema_version: int | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.update_draft_request_config_type_0 import (
            UpdateDraftRequestConfigType0,
        )

        comment: None | str | Unset
        if isinstance(self.comment, Unset):
            comment = UNSET
        else:
            comment = self.comment

        config: dict[str, Any] | None | Unset
        if isinstance(self.config, Unset):
            config = UNSET
        elif isinstance(self.config, UpdateDraftRequestConfigType0):
            config = self.config.to_dict()
        else:
            config = self.config

        schema_version: int | None | Unset
        if isinstance(self.schema_version, Unset):
            schema_version = UNSET
        else:
            schema_version = self.schema_version

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if comment is not UNSET:
            field_dict["comment"] = comment
        if config is not UNSET:
            field_dict["config"] = config
        if schema_version is not UNSET:
            field_dict["schema_version"] = schema_version

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.update_draft_request_config_type_0 import (
            UpdateDraftRequestConfigType0,
        )

        d = dict(src_dict)

        def _parse_comment(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        comment = _parse_comment(d.pop("comment", UNSET))

        def _parse_config(data: object) -> None | Unset | UpdateDraftRequestConfigType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                config_type_0 = UpdateDraftRequestConfigType0.from_dict(data)

                return config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UpdateDraftRequestConfigType0, data)

        config = _parse_config(d.pop("config", UNSET))

        def _parse_schema_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        schema_version = _parse_schema_version(d.pop("schema_version", UNSET))

        update_draft_request = cls(
            comment=comment,
            config=config,
            schema_version=schema_version,
        )

        return update_draft_request
