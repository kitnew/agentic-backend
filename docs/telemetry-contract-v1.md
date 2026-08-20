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

Voice-local tool executions use the same capability metric names at their
execution boundary. Canonical identities are `reservation.check_availability@1`
from the Backend semantic definition, `calculator.calculate@1` for the native
deterministic calculator, and `call.end@1` for the native `end_call` tool.
Arguments and results are never metric or span attributes.

Voice histogram views use bounded explicit buckets: fast pipeline metrics use
`0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2, 3, 5` seconds; turn/component
durations use `0.1, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 7.5, 10, 15, 30` seconds.

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

## Development telemetry storage

`docker-compose.dev.yml` adds a development-only telemetry stack:

```text
Applications
     |
OpenTelemetry Collector
   /              \\
Prometheus       Tempo
   \\              /
       Grafana
```

Applications send OTLP/HTTP only to the Collector on 4318. The Collector exposes
converted metrics internally on 8889 for Prometheus to scrape and exports traces
over internal OTLP/gRPC to Tempo. Applications never connect to Prometheus or
Tempo directly.

Prometheus (`prom/prometheus:v3.5.0`) persists its TSDB in `prometheus-data` and
uses the configurable `PROMETHEUS_RETENTION_TIME` (15d by default). Tempo
(`grafana/tempo:3.0.0`) uses local WAL/block storage in `tempo-data` with
configurable `TEMPO_RETENTION` (168h by default). These named volumes survive
container restart; they are single-node local storage, not off-host backups.

Only `service.name` and `deployment.environment.name` are copied into Prometheus
metric labels (`service_name`, `deployment_environment_name`). The metrics
pipeline drops other resource attributes before exposition, so build revisions and
domain identifiers such as `call.id` are not Prometheus labels. Tempo retains the
trace resource/span attributes and SpanLinks, including the trace-only `call.id`.

Grafana OSS (`grafana/grafana:12.4.3`) is the development query and
visualization UI. Its persistent state is in `grafana-data`; the provisioned
connections remain Git-managed source of truth in
`infrastructure/grafana/provisioning/datasources/datasources.yml` and
are recreated after a fresh Grafana volume. Do not edit these datasource
connections in the UI. The fixed datasource identities are:

| Name | UID | Internal URL |
| --- | --- | --- |
| Prometheus | `prometheus` (default) | `http://prometheus:9090` |
| Tempo | `tempo` | `http://tempo:3200` |

Grafana binds only to `http://127.0.0.1:${GRAFANA_PORT:-3001}`. Set
`GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` in the uncommitted
`infrastructure/compose/.env.dev`; `.env.dev.example` supplies development-only
bootstrap placeholders. Grafana is a consumer only: its outage does not block
applications, Collector, Prometheus, or Tempo.

Prometheus HTTP (9090) and Tempo HTTP/query (3200) bind to loopback solely for
local diagnostics and smoke verification. Collector OTLP (4318) and health
(13133) also bind to loopback. Tempo OTLP and Collector's Prometheus exposition
endpoint are internal-only. Prometheus and Tempo remain their respective metrics
and trace stores; Grafana adds no storage layer. Dashboards, alerts, logs
ingestion, and logs storage are not part of this stack. The existing deploy-only
MinIO deployment remains the available S3-compatible option for a future storage
migration; Tempo intentionally stays on local dev storage in this iteration.

Start it with the normal development Compose command, then run the opt-in smoke:

```bash
docker compose --env-file infrastructure/compose/.env.dev \
  -f infrastructure/compose/docker-compose.yml \
  -f infrastructure/compose/docker-compose.dev.yml up -d

OTEL_STORAGE_SMOKE=1 pytest tests/test_observability_collector_smoke.py

OTEL_GRAFANA_SMOKE=1 pytest tests/test_observability_collector_smoke.py
```

## Observability UX v1

Grafana starts at `http://127.0.0.1:${GRAFANA_PORT:-3001}`. Its entry point is
**Agentic Backend — Overview** (`agentic-backend-overview`), which links to the
three specialist dashboards. All four are provisioned from Git and are restored
when `grafana-data` is recreated; do not import or edit canonical copies in the
UI.

| Dashboard | UID | Operational question |
| --- | --- | --- |
| Agentic Backend — Overview | `agentic-backend-overview` | Which subsystem is degrading? |
| Voice Agent | `voice-agent` | Is STT, endpointing, LLM, TTS, or E2E latency slow? |
| Capabilities & Worker | `capabilities-worker` | Are logical capabilities healthy, separately from Worker attempts? |
| Post-call & Integrations | `post-call-integrations` | Are downstream processing and integrations succeeding on time? |

The bounded shared variables are `environment` and `service`; the Capabilities
dashboard also has `capability`. There are intentionally no tenant, agent,
`call.id`, conversation, command, request, room, participant, or phone-number
variables. `call.id` remains a trace-only correlation key.

The dashboards use the actual Prometheus exporter schema, not conceptual OTel
names: for example `call.started` is `call_started_total`,
`call.duration` is `call_duration_seconds_bucket`,
`capability.executions` is `capability_executions_total`, and
`voice.turn.e2e_latency` is `voice_turn_e2e_latency_seconds_bucket`. Dots become
underscores, counters end in `_total`, and second-based histograms have
`_seconds_bucket`, `_sum`, and `_count` series.

Canonical queries use `rate()` for time-series counter throughput,
`increase()` for selected-range stats, and `histogram_quantile()` over summed
histogram buckets. For example:

```promql
sum(rate(call_started_total{service_name=~"$service", deployment_environment_name=~"$environment"}[$__rate_interval]))

histogram_quantile(0.95, sum by (le) (
  rate(call_duration_seconds_bucket{service_name=~"$service", deployment_environment_name=~"$environment"}[$__rate_interval])
))

(sum(increase(capability_executions_total{service_name=~"$service", deployment_environment_name=~"$environment", capability_name=~"$capability"}[$__range]))
  - sum(increase(capability_failures_total{service_name=~"$service", deployment_environment_name=~"$environment", capability_name=~"$capability"}[$__range])))
  / sum(increase(capability_executions_total{service_name=~"$service", deployment_environment_name=~"$environment", capability_name=~"$capability"}[$__range]))
```

### Operational workflows

* **Calls are failing:** start in Overview, inspect failed calls and subsystem
  failure rate, open the specialist dashboard, then investigate the trace in
  Tempo Explore.
* **The agent is slow:** open Voice Agent; follow the p50/p95 pipeline order
  STT → end-of-turn → LLM TTFT → TTS TTFB → E2E.
* **A capability is unhealthy:** use Capabilities & Worker. The first section is
  a logical business outcome; the second is physical Worker attempts/retries/DLQ
  and must not be read as additional logical executions.
* **Post-call or webhook work failed:** open Post-call & Integrations, inspect
  failure rate and latency by `operation_type`, then open the related trace.

For a known call, select Tempo in Grafana Explore and use TraceQL:

```traceql
{ span.call.id = "<call.id>" }
```

The result can contain multiple traces: Backend and Voice Agent traces may be
separate, and delayed Worker consumption starts a new trace with a SpanLink.
`call.id` connects that investigation; it does not turn them into one trace tree.
Use an optional service narrowing only after the broad lookup, for example:

```traceql
{ span.call.id = "<call.id>" && resource.service.name = "backend-core" }
```

Tempo trace-to-metrics is provisioned as **Backend call throughput** through
datasource UID `prometheus`. It intentionally uses the Backend lifecycle metric
`call_started_total{service_name="backend-core"}` without interpolating the
investigated span's service: that metric has no Voice Agent or Job Worker series.
It needs neither Tempo metrics-generator nor service graphs. Metrics-to-trace
exemplars are currently unavailable: the OTLP SDK/Collector/Prometheus exporter
path does not receive exemplar-bearing application measurements, so no
instrumentation was added just for this UI feature.

Current UX intentionally omits playback/VAD/interruption latency, dedicated
summary-generation and artifact-materialization durations, and tenant/agent
filters: they are not authoritative bounded Prometheus signals in this contract.
Post-call work is shown by its existing `operation_type` instead. Add any of
those signals only in a separate telemetry-contract change.
