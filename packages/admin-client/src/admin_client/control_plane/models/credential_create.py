from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from typing_extensions import Self

if TYPE_CHECKING:
    from ..models.platform_credential_scope_write import PlatformCredentialScopeWrite
    from ..models.tenant_credential_scope_write import TenantCredentialScopeWrite


T = TypeVar("T", bound="CredentialCreate")


@_attrs_define
class CredentialCreate:
    """
    Attributes:
        name (str):
        scope (PlatformCredentialScopeWrite | TenantCredentialScopeWrite):
        secret (str):
    """

    name: str
    scope: PlatformCredentialScopeWrite | TenantCredentialScopeWrite
    secret: str

    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_credential_scope_write import (
            PlatformCredentialScopeWrite,
        )

        name = self.name

        scope: dict[str, Any]
        if isinstance(self.scope, PlatformCredentialScopeWrite):
            scope = self.scope.to_dict()
        else:
            scope = self.scope.to_dict()

        secret = self.secret

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "name": name,
                "scope": scope,
                "secret": secret,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls, src_dict: Mapping[str, Any]) -> Self:
        from ..models.platform_credential_scope_write import (
            PlatformCredentialScopeWrite,
        )
        from ..models.tenant_credential_scope_write import TenantCredentialScopeWrite

        d = dict(src_dict)
        name = d.pop("name")

        def _parse_scope(
            data: object,
        ) -> PlatformCredentialScopeWrite | TenantCredentialScopeWrite:
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                scope_type_0 = PlatformCredentialScopeWrite.from_dict(data)

                return scope_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            scope_type_1 = TenantCredentialScopeWrite.from_dict(data)

            return scope_type_1

        scope = _parse_scope(d.pop("scope"))

        secret = d.pop("secret")

        credential_create = cls(
            name=name,
            scope=scope,
            secret=secret,
        )

        return credential_create
