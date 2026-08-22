from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.platform_publish_request_profile_prompt_versions import (
        PlatformPublishRequestProfilePromptVersions,
    )


T = TypeVar("T", bound="PlatformPublishRequest")


@_attrs_define
class PlatformPublishRequest:
    """
    Attributes:
        profile_prompt_versions (PlatformPublishRequestProfilePromptVersions | Unset):
        runtime_version (int | None | Unset):
        system_prompt_version (int | None | Unset):
    """

    profile_prompt_versions: PlatformPublishRequestProfilePromptVersions | Unset = UNSET
    runtime_version: int | None | Unset = UNSET
    system_prompt_version: int | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        profile_prompt_versions: dict[str, Any] | Unset = UNSET
        if not isinstance(self.profile_prompt_versions, Unset):
            profile_prompt_versions = self.profile_prompt_versions.to_dict()

        runtime_version: int | None | Unset
        if isinstance(self.runtime_version, Unset):
            runtime_version = UNSET
        else:
            runtime_version = self.runtime_version

        system_prompt_version: int | None | Unset
        if isinstance(self.system_prompt_version, Unset):
            system_prompt_version = UNSET
        else:
            system_prompt_version = self.system_prompt_version

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if profile_prompt_versions is not UNSET:
            field_dict["profile_prompt_versions"] = profile_prompt_versions
        if runtime_version is not UNSET:
            field_dict["runtime_version"] = runtime_version
        if system_prompt_version is not UNSET:
            field_dict["system_prompt_version"] = system_prompt_version

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_publish_request_profile_prompt_versions import (
            PlatformPublishRequestProfilePromptVersions,
        )

        d = dict(src_dict)
        _profile_prompt_versions = d.pop("profile_prompt_versions", UNSET)
        profile_prompt_versions: PlatformPublishRequestProfilePromptVersions | Unset
        if isinstance(_profile_prompt_versions, Unset):
            profile_prompt_versions = UNSET
        else:
            profile_prompt_versions = (
                PlatformPublishRequestProfilePromptVersions.from_dict(
                    _profile_prompt_versions
                )
            )

        def _parse_runtime_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        runtime_version = _parse_runtime_version(d.pop("runtime_version", UNSET))

        def _parse_system_prompt_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        system_prompt_version = _parse_system_prompt_version(
            d.pop("system_prompt_version", UNSET)
        )

        platform_publish_request = cls(
            profile_prompt_versions=profile_prompt_versions,
            runtime_version=runtime_version,
            system_prompt_version=system_prompt_version,
        )

        return platform_publish_request
