from sqlalchemy.orm import Session

from app.domain.tool_calls.entities import ToolCall
from app.infrastructure.models import ToolCallModel


class ToolCallRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, tool_call: ToolCall) -> ToolCall:
        db_tool_call = ToolCallModel(
            id=tool_call.id,
            tenant_id=tool_call.tenant_id,
            message_id=tool_call.message_id,
            conversation_id=tool_call.conversation_id,
            capability_name=tool_call.capability_name,
            provider=tool_call.provider,
            input=tool_call.input,
            output=tool_call.output,
            status=tool_call.status,
            error=tool_call.error,
            latency_ms=tool_call.latency_ms,
            created_at=tool_call.created_at,
        )
        self.db.add(db_tool_call)
        self.db.commit()
        return tool_call

    def get_by_id(self, tool_call_id: str) -> ToolCall | None:
        db_tool_call = self.db.query(ToolCallModel).filter(ToolCallModel.id == tool_call_id).first()
        if not db_tool_call:
            return None

        return self._to_domain(db_tool_call)

    def list_by_message_id(self, message_id: str) -> list[ToolCall]:
        db_tool_calls = (
            self.db.query(ToolCallModel)
            .filter(ToolCallModel.message_id == message_id)
            .order_by(ToolCallModel.created_at.asc())
            .all()
        )
        return [self._to_domain(db_tool_call) for db_tool_call in db_tool_calls]

    def list_by_tenant_id(self, tenant_id: str) -> list[ToolCall]:
        db_tool_calls = (
            self.db.query(ToolCallModel)
            .filter(ToolCallModel.tenant_id == tenant_id)
            .order_by(ToolCallModel.created_at.asc())
            .all()
        )
        return [self._to_domain(db_tool_call) for db_tool_call in db_tool_calls]

    def _to_domain(self, db_tool_call: ToolCallModel) -> ToolCall:
        return ToolCall(
            id=db_tool_call.id,
            tenant_id=db_tool_call.tenant_id,
            message_id=db_tool_call.message_id,
            conversation_id=db_tool_call.conversation_id,
            capability_name=db_tool_call.capability_name,
            provider=db_tool_call.provider,
            input=db_tool_call.input,
            output=db_tool_call.output,
            status=db_tool_call.status,
            error=db_tool_call.error,
            latency_ms=db_tool_call.latency_ms,
            created_at=db_tool_call.created_at,
        )
