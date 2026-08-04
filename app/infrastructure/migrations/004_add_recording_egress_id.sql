ALTER TABLE call_sessions ADD COLUMN IF NOT EXISTS recording_egress_id VARCHAR UNIQUE;
