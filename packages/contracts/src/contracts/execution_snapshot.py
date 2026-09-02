from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExecutionSnapshot(BaseModel):
    """Secret-free wire representation of an immutable Control Plane snapshot."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    schema_version: int = Field(ge=1)
    tenant_id: str = Field(min_length=1)
    architecture: str = Field(min_length=1)
    created_at: datetime
    execution: dict[str, Any]
    runtime: dict[str, Any]
    agent: dict[str, Any] | None = None
    resolution: dict[str, Any]
    content_hash: str = Field(min_length=1)
