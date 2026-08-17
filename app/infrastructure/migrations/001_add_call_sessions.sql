CREATE TABLE IF NOT EXISTS call_sessions (
    id VARCHAR PRIMARY KEY,
    tenant_id VARCHAR NOT NULL,
    conversation_id VARCHAR NOT NULL,
    livekit_room_name VARCHAR NOT NULL UNIQUE,
    livekit_job_id VARCHAR UNIQUE,
    caller_phone VARCHAR,
    status VARCHAR NOT NULL CHECK (status IN ('active', 'completed', 'failed')),
    finalization_status VARCHAR NOT NULL CHECK (finalization_status IN ('pending', 'processing', 'completed', 'failed')),
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    terminal_reason VARCHAR,
    terminal_error VARCHAR,
    finalization_error VARCHAR,
    finalization_command_id VARCHAR UNIQUE,
    finalization_enqueued_at TIMESTAMP,
    transcript VARCHAR,
    summary VARCHAR,
    transcript_sheet_range VARCHAR,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_call_sessions_tenant_id ON call_sessions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_call_sessions_conversation_id ON call_sessions (conversation_id);
CREATE INDEX IF NOT EXISTS ix_call_sessions_status ON call_sessions (status);
CREATE INDEX IF NOT EXISTS ix_call_sessions_finalization_status ON call_sessions (finalization_status);
