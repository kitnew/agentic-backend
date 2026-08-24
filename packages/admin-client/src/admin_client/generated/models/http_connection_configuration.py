from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.http_api_key_header_authentication import (
        HttpApiKeyHeaderAuthentication,
    )
    from ..models.http_authentication_none import HttpAuthenticationNone
    from ..models.http_connection_configuration_headers import (
        HttpConnectionConfigurationHeaders,
    )
    from ..models.http_connection_security import HttpConnectionSecurity


T = TypeVar("T", bound="HttpConnectionConfiguration")


@_attrs_define
class HttpConnectionConfiguration:
    """
    Attributes:
        authentication (HttpApiKeyHeaderAuthentication | HttpAuthenticationNone):
        endpoint (str):
        headers (HttpConnectionConfigurationHeaders | Unset):
        security (HttpConnectionSecurity | Unset):
    """

    authentication: HttpApiKeyHeaderAuthentication | HttpAuthenticationNone
    endpoint: str
    headers: HttpConnectionConfigurationHeaders | Unset = UNSET
    security: HttpConnectionSecurity | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.http_authentication_none import HttpAuthenticationNone

        authentication: dict[str, Any]
        if isinstance(self.authentication, HttpAuthenticationNone):
            authentication = self.authentication.to_dict()
        else:
            authentication = self.authentication.to_dict()

        endpoint = self.endpoint

        headers: dict[str, Any] | Unset = UNSET
        if not isinstance(self.headers, Unset):
            headers = self.headers.to_dict()

        security: dict[str, Any] | Unset = UNSET
        if not isinstance(self.security, Unset):
            security = self.security.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "authentication": authentication,
                "endpoint": endpoint,
            }
        )
        if headers is not UNSET:
            field_dict["headers"] = headers
        if security is not UNSET:
            field_dict["security"] = security

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.http_api_key_header_authentication import (
            HttpApiKeyHeaderAuthentication,
        )
        from ..models.http_authentication_none import HttpAuthenticationNone
        from ..models.http_connection_configuration_headers import (
            HttpConnectionConfigurationHeaders,
        )
        from ..models.http_connection_security import HttpConnectionSecurity

        d = dict(src_dict)

        def _parse_authentication(
            data: object,
        ) -> HttpApiKeyHeaderAuthentication | HttpAuthenticationNone:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                authentication_type_0 = HttpAuthenticationNone.from_dict(data)

                return authentication_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            authentication_type_1 = HttpApiKeyHeaderAuthentication.from_dict(data)

            return authentication_type_1

        authentication = _parse_authentication(d.pop("authentication"))

        endpoint = d.pop("endpoint")

        _headers = d.pop("headers", UNSET)
        headers: HttpConnectionConfigurationHeaders | Unset
        if isinstance(_headers, Unset):
            headers = UNSET
        else:
            headers = HttpConnectionConfigurationHeaders.from_dict(_headers)

        _security = d.pop("security", UNSET)
        security: HttpConnectionSecurity | Unset
        if isinstance(_security, Unset):
            security = UNSET
        else:
            security = HttpConnectionSecurity.from_dict(_security)

        http_connection_configuration = cls(
            authentication=authentication,
            endpoint=endpoint,
            headers=headers,
            security=security,
        )

        return http_connection_configuration
