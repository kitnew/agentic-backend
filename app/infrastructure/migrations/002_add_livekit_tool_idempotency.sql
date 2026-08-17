ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS call_session_id VARCHAR;
ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS external_tool_call_id VARCHAR;
ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS request_fingerprint VARCHAR;
ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS response JSON;
ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS ix_tool_calls_call_session_id ON tool_calls (call_session_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tool_calls_livekit_identity
    ON tool_calls (tenant_id, call_session_id, external_tool_call_id)
    WHERE call_session_id IS NOT NULL AND external_tool_call_id IS NOT NULL;
