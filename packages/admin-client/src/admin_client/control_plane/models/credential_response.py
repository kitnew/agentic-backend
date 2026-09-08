from __future__ import annotations

import datetime
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast
from uuid import UUID

from attrs import define as _attrs_define
from typing_extensions import Self

from ..models.credential_response_status import CredentialResponseStatus

if TYPE_CHECKING:
    from ..models.platform_credential_scope_write import PlatformCredentialScopeWrite
    from ..models.tenant_credential_scope_write import TenantCredentialScopeWrite


T = TypeVar("T", bound="CredentialResponse")


@_attrs_define
class CredentialResponse:
    """
    Attributes:
        active_secret_version (int):
        created_at (datetime.datetime):
        id (UUID):
        name (str):
        revoked_at (datetime.datetime | None):
        scope (PlatformCredentialScopeWrite | TenantCredentialScopeWrite):
        status (CredentialResponseStatus):
        updated_at (datetime.datetime):
    """

    active_secret_version: int
    created_at: datetime.datetime
    id: UUID
    name: str
    revoked_at: datetime.datetime | None
    scope: PlatformCredentialScopeWrite | TenantCredentialScopeWrite
    status: CredentialResponseStatus
    updated_at: datetime.datetime

    def to_dict(self) -> dict[str, Any]:
        from ..models.platform_credential_scope_write import (
            PlatformCredentialScopeWrite,
        )

        active_secret_version = self.active_secret_version

        created_at = self.created_at.isoformat()

        id = str(self.id)

        name = self.name

        revoked_at: None | str
        if isinstance(self.revoked_at, datetime.datetime):
            revoked_at = self.revoked_at.isoformat()
        else:
            revoked_at = self.revoked_at

        scope: dict[str, Any]
        if isinstance(self.scope, PlatformCredentialScopeWrite):
            scope = self.scope.to_dict()
        else:
            scope = self.scope.to_dict()

        status = self.status.value

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "active_secret_version": active_secret_version,
                "created_at": created_at,
                "id": id,
                "name": name,
                "revoked_at": revoked_at,
                "scope": scope,
                "status": status,
                "updated_at": updated_at,
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
        active_secret_version = d.pop("active_secret_version")

        created_at = datetime.datetime.fromisoformat(d.pop("created_at"))

        id = UUID(d.pop("id"))

        name = d.pop("name")

        def _parse_revoked_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                revoked_at_type_0 = datetime.datetime.fromisoformat(data)

                return revoked_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        revoked_at = _parse_revoked_at(d.pop("revoked_at"))

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

        status = CredentialResponseStatus(d.pop("status"))

        updated_at = datetime.datetime.fromisoformat(d.pop("updated_at"))

        credential_response = cls(
            active_secret_version=active_secret_version,
            created_at=created_at,
            id=id,
            name=name,
            revoked_at=revoked_at,
            scope=scope,
            status=status,
            updated_at=updated_at,
        )

        return credential_response
