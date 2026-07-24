ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS called_phone VARCHAR;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS sip_call_key VARCHAR;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS sip_call_id VARCHAR;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS sip_call_id_full VARCHAR;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS sip_participant_identity VARCHAR;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS sip_trunk_id VARCHAR;
ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS sip_rule_id VARCHAR;

CREATE UNIQUE INDEX IF NOT EXISTS uq_call_sessions_sip_call_key
    ON call_sessions (sip_call_key)
    WHERE sip_call_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_call_sessions_sip_call_id ON call_sessions (sip_call_id);
CREATE INDEX IF NOT EXISTS ix_call_sessions_sip_call_id_full ON call_sessions (sip_call_id_full);
