from datetime import datetime

from pydantic import BaseModel


class Conversation(BaseModel):
    id: str
    tenant_id: str
    channel: str
    external_user_id: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
