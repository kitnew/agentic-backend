from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend_core.modules.tenants.models import TenantStatus

Slug = Annotated[
    str,
    Field(
        min_length=3,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
BusinessType = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]


class TenantCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    slug: Slug
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    business_type: BusinessType
    status: TenantStatus = TenantStatus.ACTIVE


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    display_name: str
    business_type: str
    status: TenantStatus
    created_at: datetime
    updated_at: datetime
