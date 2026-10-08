# LiveKit call recording

## Data flow

```text
session_started -> call.started (call lifecycle only)
participant_connected -> backend.activate() (before greeting)
non-interruptible opening greeting -> wait_for_playout()
Voice Agent -> POST /internal/v1/calls/{call_id}/recording
            -> RecordingCoordinator.ensure() -> LiveKit RoomComposite Egress
            -> MP3 -> private MinIO call-recordings bucket
confirmed handoff COMPLETED -> RecordingCoordinator.stop() -> LiveKit StopEgress
  -> close AI session and persist final transcript/usage
  -> agent_relinquished -> idempotent recording stop
  -> call.agent_relinquished -> post-call finalization
call termination (including SIP caller disconnect without handoff)
  -> normal finalization -> RecordingCoordinator.stop() -> LiveKit StopEgress
LiveKit signed webhook -> Backend recording.ready/recording.failed
                       -> existing post-call scheduler -> Job Worker
Job Worker -> MinIO read -> streaming base64 -> configured external action
```

The Backend owns one canonical `CallRecording` per `CallSession`. LiveKit Egress
owns mixing, MP3 encoding, and upload. MinIO owns only the object bytes. The
Voice Agent waits for the non-interruptible opening greeting to finish playing,
then requests recording from the Backend; it does not manage Egress or hold
storage credentials.

`session_started` emits `call.started` for call lifecycle only and does not start
recording. `backend.activate()` reports `participant_connected` before the
greeting. Once `wait_for_playout()` completes, the Voice Agent calls
`POST /internal/v1/calls/{call_id}/recording`; the Backend uses
`RecordingCoordinator.ensure()` to start Egress idempotently, after the recording
intent transaction commits. Failure marks only the recording as failed; it never
fails the live call.

Confirmed successful handoff stops recording when the AI conversation is
relinquished, while the caller and destination remain bridged in the LiveKit
room. Calls without successful handoff stop recording on normal termination.
Room deletion remains cleanup and a safety net, not the primary recording-stop
trigger. Post-call work waits for the final Egress result when it needs audio.

The canonical object key is:

```text
recordings/<tenant_id>/<call_session_id>/<recording_id>.mp3
```

The Backend request contains the room, this key, audio-only mode, MP3, and no
storage credentials. `livekit-egress` receives the private MinIO endpoint,
bucket, and write credentials from deployment configuration. The Job Worker has
separate read credentials and streams base64 directly into the existing
managed-webhook body binding. PostgreSQL contains neither MP3 nor base64 bytes.

## LiveKit server webhook

Configure the LiveKit server that shares Redis with Egress to deliver signed
webhooks to:

```yaml
webhook:
  api_key: <same LIVEKIT_API_KEY>
  urls:
    - https://<backend-host>/webhooks/livekit
```

Local Compose supplies `http://backend:8000/webhooks/livekit` automatically.
The Backend verifies the raw body and `Authorization` token with the LiveKit SDK
before accepting `egress_started`, `egress_updated`, or `egress_ended`.

## Local verification

1. Copy `.env.dev.example` to the local environment file and replace API/provider
   placeholders as usual.
2. Run the normal base + development Compose topology.
3. Check `minio`, `minio-init`, and `livekit-egress`:

   ```bash
   docker compose ps
   docker compose logs minio-init livekit-egress
   docker compose run --rm minio-init mc ls local/call-recordings
   ```

4. Create/place a LiveKit call and confirm one `call_recordings` row is created
   with `pending`, then an `egress_id` and `recording`.
5. End the room/call. Confirm the signed `egress_ended` webhook changes the row
   to `ready`, with `audio/mpeg`, positive `byte_size`, and `duration_ms`.
6. Verify the object without making the bucket public:

   ```bash
   docker compose run --rm minio-init mc stat local/call-recordings/recordings/<tenant_id>/<call_id>/<recording_id>.mp3
   ```

7. Configure an existing `call_recording/base64_text` post-call input and verify
   the normal scheduler/action reaches its configured target.
8. Failure check: stop `minio`, create another call, and restart it after the
   Egress attempt. The call remains valid; the canonical recording converges to
   `failed`, and a recording-dependent finalization becomes terminal rather than
   waiting forever.

For SIP handoff the MP3 ends after confirmed transfer and AI-session closure.
The subsequent caller/destination conversation in the LiveKit room is not
recorded by this Egress.

## Operational notes

- Images are pinned: LiveKit Server `v1.13.1`, Egress `v1.13.0`, MinIO
  `RELEASE.2025-09-07T16-13-09Z`, and MinIO Client
  `RELEASE.2025-08-13T08-35-41Z`.
- Egress uses the same Redis address as LiveKit. A staging/production LiveKit
  server outside this Compose project must be configured against that same Redis.
- `call-recordings` is created idempotently and anonymous access is disabled.
- The checked-in Egress v1.13.0 seccomp profile and
  `enable_chrome_sandbox: true` retain Chrome sandboxing for RoomComposite.
- Webhooks are primary. Existing call-runtime reconciliation performs bounded
  recovery for stale, terminal-call recordings; MinIO is never polled.
- Migration `20260812_0026` refuses to discard legacy PostgreSQL recording bytes.
  Export/migrate any such rows before upgrading.

## Deferred production hardening

- Docker Secrets or another secret store instead of environment credentials.
- Bucket-scoped custom policies (the temporary Egress/Worker users use MinIO's
  built-in `readwrite`/`readonly` policies).
- MinIO TLS, external object storage, backups, lifecycle/retention, and deletion.
- Production monitoring/alerts, capacity planning, and Egress autoscaling.
- Consent policy, tenant enablement, playback/presigned APIs, video/per-track
  formats, recording retries/history, and post-cold-transfer PSTN recording.
