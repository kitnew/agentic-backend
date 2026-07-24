from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.domain.tool_calls.entities import ToolCall
from app.domain.tool_calls.enums import ToolCallStatus
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
            call_session_id=tool_call.call_session_id,
            external_tool_call_id=tool_call.external_tool_call_id,
            request_fingerprint=tool_call.request_fingerprint,
            capability_name=tool_call.capability_name,
            provider=tool_call.provider,
            input=tool_call.input,
            output=tool_call.output,
            status=tool_call.status.value,
            error=tool_call.error,
            response=tool_call.response,
            latency_ms=tool_call.latency_ms,
            created_at=tool_call.created_at,
            updated_at=tool_call.updated_at,
        )
        self.db.add(db_tool_call)
        self.db.commit()
        return tool_call

    def reserve_livekit(self, tool_call: ToolCall) -> tuple[ToolCall, bool]:
        try:
            self.create(tool_call)
            return tool_call, True
        except IntegrityError:
            self.db.rollback()
            existing = self.get_by_livekit_identity(
                tool_call.tenant_id,
                tool_call.call_session_id or "",
                tool_call.external_tool_call_id or "",
            )
            if existing is None:
                raise
            return existing, False

    def get_by_livekit_identity(
        self, tenant_id: str, call_session_id: str, external_tool_call_id: str
    ) -> ToolCall | None:
        row = (
            self.db.query(ToolCallModel)
            .filter(
                ToolCallModel.tenant_id == tenant_id,
                ToolCallModel.call_session_id == call_session_id,
                ToolCallModel.external_tool_call_id == external_tool_call_id,
            )
            .first()
        )
        return self._to_domain(row) if row else None

    def latest_livekit_capability(
        self, tenant_id: str, call_session_id: str, capability_name: str
    ) -> ToolCall | None:
        row = (
            self.db.query(ToolCallModel)
            .filter(
                ToolCallModel.tenant_id == tenant_id,
                ToolCallModel.call_session_id == call_session_id,
                ToolCallModel.capability_name == capability_name,
            )
            .order_by(ToolCallModel.updated_at.desc(), ToolCallModel.created_at.desc())
            .first()
        )
        return self._to_domain(row) if row else None

    def complete_livekit(
        self,
        tool_call_id: str,
        *,
        status: ToolCallStatus,
        provider: str,
        output: dict | None,
        error: str | None,
        response: dict,
        latency_ms: int,
        updated_at,
    ) -> ToolCall:
        row = self.db.query(ToolCallModel).filter(ToolCallModel.id == tool_call_id).one()
        row.status = status.value
        row.provider = provider
        row.output = output
        row.error = error
        row.response = response
        row.latency_ms = latency_ms
        row.updated_at = updated_at
        self.db.commit()
        return self._to_domain(row)

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
            call_session_id=db_tool_call.call_session_id,
            external_tool_call_id=db_tool_call.external_tool_call_id,
            request_fingerprint=db_tool_call.request_fingerprint,
            capability_name=db_tool_call.capability_name,
            provider=db_tool_call.provider,
            input=db_tool_call.input,
            output=db_tool_call.output,
            status=ToolCallStatus(db_tool_call.status),
            error=db_tool_call.error,
            response=db_tool_call.response,
            latency_ms=db_tool_call.latency_ms,
            created_at=db_tool_call.created_at,
            updated_at=db_tool_call.updated_at,
        )
