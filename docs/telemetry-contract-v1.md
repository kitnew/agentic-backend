# Telemetry Contract v1

This contract is source-side privacy policy for the opt-in Backend Core, Job
Worker, and Voice Agent integrations. Providers are application-owned; nothing
installs a process-global OpenTelemetry provider.

## Resource identity

- `service.namespace` is always `agentic-backend`.
- `service.name` is exactly one of `backend-core`, `job-worker`, or `voice-agent`.
- `service.version`, `deployment.environment.name`, and `vcs.ref.head.revision`
  are required resource attributes.
- Do not emit deprecated `deployment.environment`.
- No generic `build.id` is allowed. If a real build ID becomes available, use only
  `agentic_backend.build.id`.

`OTEL_ENABLED` defaults to `false` in code. The development environment template
is the only supplied template that enables it. Use `OTEL_SERVICE_NAME` and
`OTEL_RESOURCE_ATTRIBUTES` for identity. Example:

```text
OTEL_SERVICE_NAME=backend-core
OTEL_RESOURCE_ATTRIBUTES=service.version=1.2.3,deployment.environment.name=development,vcs.ref.head.revision=abc123
```

## Signals and privacy

Domain attributes are `tenant.id`, `call.id`, `conversation.id`, `agent.id`,
`agent.revision`, `operation.id`, `capability.name`, `capability.version`,
`command.id`, `action.id`, and `artifact.type`. Opaque identifiers are trace-only
and may also appear in fields validated by `safe_log_fields`; they are never metric
dimensions.

Metric attributes are limited to `capability.name`, `capability.version`,
`artifact.type`, `operation.type`, `status`, `outcome`, `error.type`, and the
bounded Voice Agent component metadata `voice.component`, `voice.provider`, and
`voice.model`. Identifiers, revisions, URLs, provider request IDs, and arbitrary
strings are rejected by the helper.

Never emit transcripts, prompts, user or assistant content, audio or recordings,
phone/SIP identities, tool arguments/results/payloads, HTTP bodies, credentials, or
external error bodies. GenAI content attributes are off by default.

## Propagation and configuration

Use W3C Trace Context only: `traceparent` and `tracestate`; do not propagate
baggage. A domain `correlation_id` is not a trace ID. `MessageEnvelope` stays
unchanged; W3C context is stored in the generic
`outbox_messages.transport_metadata` carrier and forwarded as Redis stream
fields.

`OTEL_SDK_DISABLED` follows the SDK rule: only `true` disables the SDK. Use
`OTEL_EXPORTER_OTLP_ENDPOINT` (development expects
`http://otel-collector:4318`) and `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`.
Use standard exporter timeout, batch, and metric interval variables—there are no
project-specific duplicates. Set `OTEL_PROPAGATORS=tracecontext`. Only
transactional-outbox creation and dispatch create messaging spans; direct Redis
sends remain uninstrumented.

Exporter failures are diagnostic only. The reusable provider owner bounds
`force_flush` and `shutdown` at ten seconds.

## Domain traces

Standard FastAPI, SQLAlchemy, Redis, HTTP client, and LiveKit instrumentation is
used for transport/runtime operations. Manual spans are limited to application
boundaries:

- `call.prepare` records creation/reuse of a CallSession.
- `call.reconcile` records a stale LiveKit runtime recovery attempt.
- `capability.prepare` records Backend validation and durable dispatch setup;
  `capability.execute` records one Worker provider execution attempt.
- `post_call.process` records finalization scheduling.
- `post_call.summary.generate`, `integration.execute`, and `artifact.materialize`
  record the corresponding Worker command execution. Their HTTP spans remain
  transport children.

Domain spans may contain known trace correlation attributes such as `tenant.id`,
`call.id`, `conversation.id`, `operation.id`, and capability identity. They never
contain payloads, summary text, artifacts, message bodies, or exception text.
Expected or unexpected failures set only bounded `status=error` and `error.type`.

Redis delayed processing starts a new trace and uses a Span Link to the original
outbox creation context. It is not converted into a long-running parent-child
trace.

## Core metrics

All durations use seconds. `call.started`, `call.completed`, `call.failed`,
`call.active` (UpDownCounter), and `call.duration` are recorded only at the
authoritative CallSession state transition. Active calls are seeded once from the
database at Backend startup; terminal/replayed transitions do not alter counters.
`call.duration` is the interval from `started_at` to terminal `ended_at`.

`capability.executions`, `capability.failures`, and
`capability.execution.duration` are logical terminal results, recorded only when
Backend first changes an invocation to succeeded or failed. Worker physical
attempts are separately represented by `worker.capability.execution_attempts`
and `worker.capability.execution_attempt.duration`.

`worker.command.attempts`, `worker.command.failures`, `worker.command.duration`,
`worker.command.retries`, and `worker.command.dlq` cover post-call command
processing. `post_call.executions`, `post_call.failures`, and `post_call.duration`
use bounded operation types `summary_generation`, `post_call_action`, and
`artifact_materialization`; `integration.*` applies only to post-call action
execution. Retry attempts use `status=retry`, terminal failures use
`status=failed`, and completed-message replay records no second execution.

Voice Agent metrics use its explicit meter and current LiveKit per-turn and
component surfaces: turn latency, LLM/STT/TTS requests, durations, token/audio
usage, TTS characters, and bounded component errors. Deprecated session-level
`metrics_collected`, `UsageCollector`, and cumulative session usage are not used.
VAD/interruption/playback measurements are intentionally absent because the
configured LiveKit runtime has no unambiguous authoritative per-operation source.

Outbox pending-count and oldest-age gauges are intentionally absent: obtaining a
global current state would require an additional recurring database query. The
dispatcher does not add such a hot-path poll solely for telemetry.

## Voice Agent native telemetry

Voice Agent bootstraps an explicit provider in the LiveKit job process and passes
it through the supported LiveKit dynamic tracer registration API. Its native
session/turn/STT/LLM/TTS/tool spans therefore use the same OTLP pipeline. LiveKit
Cloud recording is disabled for the session; before export, the processor removes
native `lk.*`/`gen_ai.*` attributes, events, and exception status descriptions.
This keeps prompts, chat content, transcripts, tool data, and recordings out of
telemetry. Voice correlation adds `call.id` only where that identifier is
available; it does not force a call-long shared trace.

## Development Collector

`docker-compose.dev.yml` adds a development-only Collector with OTLP/HTTP on 4318,
health on 13133, traces and metrics pipelines, and a detailed debug exporter. Its
ports bind only to loopback and its config mount is read-only. It has no logs
pipeline, storage, persistent volume, or production/vendor backend.
