from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.set_integration_secret_request_secret import (
        SetIntegrationSecretRequestSecret,
    )


T = TypeVar("T", bound="SetIntegrationSecretRequest")


@_attrs_define
class SetIntegrationSecretRequest:
    """
    Attributes:
        secret (SetIntegrationSecretRequestSecret):
    """

    secret: SetIntegrationSecretRequestSecret

    def to_dict(self) -> dict[str, Any]:
        secret = self.secret.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "secret": secret,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.set_integration_secret_request_secret import (
            SetIntegrationSecretRequestSecret,
        )

        d = dict(src_dict)
        secret = SetIntegrationSecretRequestSecret.from_dict(d.pop("secret"))

        set_integration_secret_request = cls(
            secret=secret,
        )

        return set_integration_secret_request
