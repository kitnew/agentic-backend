from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CANONICAL_FIELDS = {
    "guest.name": "string",
    "guest.phone": "string",
    "guest.email": "string",
    "stay.check_in": "string",
    "stay.check_out": "string",
    "allocation.room_type": "integer",
    "allocation.room_count": "integer",
    "notes": "string",
}

CANONICAL_FIELD_DESCRIPTIONS = {
    "guest.name": "Guest name",
    "guest.phone": "Guest phone number",
    "guest.email": "Guest email address",
    "stay.check_in": "Reservation check-in date",
    "stay.check_out": "Reservation check-out date",
    "allocation.room_type": "Requested room type",
    "allocation.room_count": "Requested room count",
    "notes": "Conversation notes",
}

CANONICAL_FIELD_NORMALIZERS = {
    "guest.name": "trim",
    "guest.phone": "e164",
    "guest.email": "trim",
}


class CatalogDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    type: str
    description: str
    category: str


class CapabilitySemanticDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    version: int = Field(gt=0)
    description: str
    kind: str
    tool_name: str


class PostCallArtifactDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact: Literal["transcript", "call_recording", "call_summary"]
    representations: list[str]
    description: str


class CapabilityDiscoveryResponse(BaseModel):
    semantics: list[CapabilitySemanticDescriptor]
    domain_fields: list[CatalogDescriptor]
    mapping_context: list[CatalogDescriptor]


class PostCallDiscoveryResponse(BaseModel):
    artifacts: list[PostCallArtifactDescriptor]
    mapping_context: list[CatalogDescriptor]
