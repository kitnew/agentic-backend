from sqlalchemy.orm import Session

from app.domain.call_sessions.entities import CallSession
from app.infrastructure.models import CallSessionModel


class CallSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, call: CallSession) -> CallSession:
        self.db.add(CallSessionModel(**call.model_dump(mode="python")))
        self.db.commit()
        return call

    def get(self, call_session_id: str, *, for_update: bool = False) -> CallSession | None:
        query = self.db.query(CallSessionModel).filter(CallSessionModel.id == call_session_id)
        row = query.with_for_update().first() if for_update else query.first()
        return CallSession.model_validate(row, from_attributes=True) if row else None

    def save(self, call: CallSession) -> CallSession:
        row = self.db.query(CallSessionModel).filter(CallSessionModel.id == call.id).one()
        for field, value in call.model_dump(mode="python").items():
            setattr(row, field, value)
        self.db.commit()
        return call
