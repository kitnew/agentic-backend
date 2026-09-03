from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend_core.modules.tenants.models import TenantStatus

Slug = Annotated[
    str,
    Field(min_length=3, max_length=63, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$"),
]
BusinessType = Annotated[
    str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
]
E164Did = Annotated[
    str, Field(min_length=3, max_length=16, pattern=r"^\+[1-9][0-9]{1,14}$")
]


def normalize_e164(value: str) -> str | None:
    normalized = value.strip().replace(" ", "").replace("-", "")
    if (
        normalized.startswith("+")
        and 3 <= len(normalized) <= 16
        and normalized[1:].isdigit()
        and normalized[1] != "0"
    ):
        return normalized
    return None


class CreateTenantRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slug: Slug
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    business_type: BusinessType
    status: TenantStatus = TenantStatus.ACTIVE


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    display_name: str
    business_type: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime


class PlatformTelephonyResponse(BaseModel):
    provider: str
    inbound: str
    outbound: str
    dispatch: str
    overall: str
    last_error: str | None
    last_reconciled_at: datetime | None
    diagnostics: dict[str, str | None]


class TelephonyDidState(BaseModel):
    phone_number: str | None = None


class TelephonyClaimStatus(BaseModel):
    state: str
    phone_number: str | None = None


class TelephonyProvisioningStatusResponse(BaseModel):
    state: str
    last_error: str | None = None
    last_reconciled_at: datetime | None = None


class TenantTelephonyStatus(BaseModel):
    tenant_id: UUID
    draft: TelephonyDidState | None
    published: TelephonyDidState | None
    publication: str
    claim: TelephonyClaimStatus
    provisioning: TelephonyProvisioningStatusResponse
