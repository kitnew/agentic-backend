ALTER TABLE call_sessions
    ADD COLUMN IF NOT EXISTS post_call_transcription_sent BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE call_sessions
    ADD COLUMN IF NOT EXISTS post_call_audio_sent BOOLEAN NOT NULL DEFAULT FALSE;
