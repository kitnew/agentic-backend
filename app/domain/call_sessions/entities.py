from datetime import datetime

from pydantic import BaseModel

from app.domain.call_sessions.enums import CallFinalizationStatus, CallSessionStatus


class CallSession(BaseModel):
    id: str
    tenant_id: str
    conversation_id: str
    livekit_room_name: str
    livekit_job_id: str | None = None
    recording_egress_id: str | None = None
    post_call_transcription_sent: bool = False
    post_call_audio_sent: bool = False
    caller_phone: str | None = None
    called_phone: str | None = None
    sip_call_key: str | None = None
    sip_call_id: str | None = None
    sip_call_id_full: str | None = None
    sip_participant_identity: str | None = None
    sip_trunk_id: str | None = None
    sip_rule_id: str | None = None
    status: CallSessionStatus = CallSessionStatus.ACTIVE
    finalization_status: CallFinalizationStatus = CallFinalizationStatus.PENDING
    started_at: datetime
    ended_at: datetime | None = None
    terminal_reason: str | None = None
    terminal_error: str | None = None
    finalization_error: str | None = None
    finalization_command_id: str | None = None
    finalization_enqueued_at: datetime | None = None
    transcript: str | None = None
    summary: str | None = None
    transcript_sheet_range: str | None = None
    updated_at: datetime
