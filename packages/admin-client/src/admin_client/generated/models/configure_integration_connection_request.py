from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.http_connection_configuration import HttpConnectionConfiguration
    from ..models.integration_credential_write import IntegrationCredentialWrite


T = TypeVar("T", bound="ConfigureIntegrationConnectionRequest")


@_attrs_define
class ConfigureIntegrationConnectionRequest:
    """
    Attributes:
        configuration (HttpConnectionConfiguration):
        credential (IntegrationCredentialWrite | None | Unset):
    """

    configuration: HttpConnectionConfiguration
    credential: IntegrationCredentialWrite | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.integration_credential_write import IntegrationCredentialWrite

        configuration = self.configuration.to_dict()

        credential: dict[str, Any] | None | Unset
        if isinstance(self.credential, Unset):
            credential = UNSET
        elif isinstance(self.credential, IntegrationCredentialWrite):
            credential = self.credential.to_dict()
        else:
            credential = self.credential

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "configuration": configuration,
            }
        )
        if credential is not UNSET:
            field_dict["credential"] = credential

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.http_connection_configuration import HttpConnectionConfiguration
        from ..models.integration_credential_write import IntegrationCredentialWrite

        d = dict(src_dict)
        configuration = HttpConnectionConfiguration.from_dict(d.pop("configuration"))

        def _parse_credential(
            data: object,
        ) -> IntegrationCredentialWrite | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                credential_type_0 = IntegrationCredentialWrite.from_dict(data)

                return credential_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(IntegrationCredentialWrite | None | Unset, data)

        credential = _parse_credential(d.pop("credential", UNSET))

        configure_integration_connection_request = cls(
            configuration=configuration,
            credential=credential,
        )

        return configure_integration_connection_request
