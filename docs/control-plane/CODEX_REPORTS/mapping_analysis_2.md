# A. Cascade Policies

The target override places all cascade pipeline behavior in system `Policies`. The smallest complete schema is the union of the current `CascadeExecutionDefaults` and tokenizer gate.

Current scalar types and constraints:

| Field | Current type/constraint | Voice Agent consumer |
|---|---|---|
| `speech_activity.min_speech_seconds` | `float`, `0 < x <= 60` | `inference.VAD(min_speech_duration=...)` |
| `speech_activity.min_silence_seconds` | `float`, `0 < x <= 60` | `inference.VAD(min_silence_duration=...)` |
| `speech_activity.activation_threshold` | `float`, `0 <= x <= 1` | `inference.VAD(activation_threshold=...)` |
| `stt_commit.strategy` | `"local_vad"` or `"provider_vad"` | Chooses local wrapper versus provider VAD |
| `provider_vad.threshold` | `float`, `0 <= x <= 1` | ElevenLabs `vad_threshold` |
| `provider_vad.silence_threshold_seconds` | `float`, `0 < x <= 60` | ElevenLabs `vad_silence_threshold_secs` |
| `provider_vad.min_speech_ms` | integer, `1..60000` | ElevenLabs `min_speech_duration_ms` |
| `provider_vad.min_silence_ms` | integer, `1..60000` | ElevenLabs `min_silence_duration_ms` |
| `endpointing.min_delay_seconds` | `float`, `0 < x <= 60` | `AgentSession.turn_handling.endpointing.min_delay` |
| `endpointing.max_delay_seconds` | `float`, `0 < x <= 60` | `AgentSession.turn_handling.endpointing.max_delay` |
| `interruption.enabled` | boolean | `allow_interruptions` |
| `interruption.min_duration_seconds` | `float`, `0..60` | `min_duration` |
| `interruption.min_words` | integer, `>=0` | `min_words` |
| `interruption.false_interruption_timeout_seconds` | `float`, `0..60` | `false_interruption_timeout` |
| `interruption.resume_after_false_interruption` | boolean | `resume_false_interruption` |
| `response_scheduling.preemptive_generation` | boolean | `preemptive_generation.enabled` |
| `response_scheduling.preemptive_tts` | boolean | `preemptive_generation.preemptive_tts` |
| `tokenizer.min_sentence_chars` | integer, `3..200` | Blingfire `SentenceTokenizer(min_sentence_len=...)` |

Definitions and constraints are in [runtime_components.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/runtime_components.py:37) and [runtime_components.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/runtime_components.py:47).

The exact cascade consumers are in [providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:66) and [providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:112).

Hard-coded settings that should not become `Policies` fields:

- cascade `turn_detection: "stt"` ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:133));
- provider language conversion `sk-SK -> slk/sk` ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:20));
- provider type gates requiring Azure LLM and ElevenLabs STT/TTS ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:55));
- provider connection timeout/retry settings, which come from `VoiceAgentSettings`;
- `tools=[]` and other session-construction choices;
- deployment/model identity, which belongs to `ModelDeployment`.

# B. Realtime runtime wiring

The installed environment is LiveKit Agents 1.7.1 and OpenAI plugin 1.7.1, as declared in [apps/voice-agent/pyproject.toml](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/pyproject.toml:13).

The installed realtime API supports:

- `RealtimeModel(..., turn_detection=...)` ([realtime_model.py](/home/nikitachernysh/Storage/Projects/agentic-backend/.venv/lib64/python3.14/site-packages/livekit/plugins/openai/realtime/realtime_model.py:385));
- `ServerVad` with `threshold`, `silence_duration_ms`, and `interrupt_response` ([realtime_audio_input_turn_detection.py](/home/nikitachernysh/Storage/Projects/agentic-backend/.venv/lib64/python3.14/site-packages/openai/types/realtime/realtime_audio_input_turn_detection.py:12));
- `SemanticVad` with `eagerness` and `interrupt_response` ([realtime_audio_input_turn_detection.py](/home/nikitachernsh/Storage/Projects/agentic-backend/.venv/lib64/python3.14/site-packages/openai/types/realtime/realtime_audio_input_turn_detection.py:82));
- AgentSession interruption controls, although the flat arguments are deprecated in favor of `turn_handling` ([agent_session.py](/home/nikitachernysh/Storage/Projects/agentic-backend/.venv/lib64/python3.14/site-packages/livekit/agents/voice/agent_session.py:372)).

Current repository wiring is incomplete: `create_realtime_session` passes neither `turn_detection` nor interruption settings and constructs `AgentSession(..., vad=None, turn_detection=None)` ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:176), [providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:193)).

Therefore the fields can remain in the target because they have a real installed-API mapping, but they are not currently effective.

Exact target mappings:

| Target field | Runtime mapping |
|---|---|
| `deployment_ref` | Resolve `ModelDeployment`; pass provider deployment material |
| `input_transcription.deployment_ref` | Resolve STT `ModelDeployment`; pass `input_audio_transcription.model` |
| `default_voice` | `RealtimeModel.voice` |
| `turn_completion.strategy=server_vad` | `RealtimeModel.turn_detection = ServerVad(type="server_vad", ...)` |
| `server_vad.activation_threshold` | `ServerVad.threshold` |
| `server_vad.silence_duration_ms` | `ServerVad.silence_duration_ms` |
| `turn_completion.strategy=semantic_vad` | `RealtimeModel.turn_detection = SemanticVad(type="semantic_vad", ...)` |
| `semantic_vad.eagerness` | `SemanticVad.eagerness` |
| `interruption.enabled` | `ServerVad/SemanticVad.interrupt_response` and AgentSession interruption handling |

No other realtime behavior field has evidence of an effective mapping. `create_response` and `idle_timeout_ms` are supported by the provider API but are not current repository semantics and should not be introduced.

The `model` fallback `"gpt-realtime"` in [providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:177) is provider implementation fallback, not a `RealtimeDefaults` field.

# C. `agent_profile`

Every current read:

| Location | Use | Classification |
|---|---|---|
| `ExecutionResolver` | Copies `agent.value.agent_profile` into resolved execution state | Snapshot data |
| `runtime_execution_snapshot.py` | Persists it into snapshot agent data | Persisted execution material |
| Backend `ExecutionContextReader` | Exposes it as `VoiceAgentRuntimeContext.agent_profile` | External Backend→Voice Agent contract |
| Backend `FinalizationService` | Maps it to post-call `agent.id` | Behavioral post-call mapping input |
| agentctl tests | Keeps it separate from `profile_key` | Authoring evidence only |
| Admin Web | Displays/edits it | Management evidence only |
| tests | Validates its format and propagation | Test evidence |

Exact reads are visible at [execution_resolver.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/application/execution_resolver.py:161), [execution_context.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/execution_context.py:73), and [service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/finalization/service.py:764).

`agent_profile` is not used to select the platform profile. `profile_key` performs that selection ([execution_resolver.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/application/execution_resolver.py:82)).

Repository evidence proves an independent stable identity value is currently required: post-call mapping exposes both `agent.id` and `agent.name`, with `agent.id` sourced from `agent_profile` and `agent.name` from `display_name` ([service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/finalization/service.py:773)).

Conclusion:

- an independent identity field is semantically necessary if the current post-call mapping context remains;
- the name `agent_key` is not independently required;
- the smallest target name is `identity`, avoiding confusion with `ProfileReference`.

# D. Actions technical semantics

## Per-action version

A per-action `semantic_version` is currently used in:

- confirmation payload hashes ([service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/service.py:121));
- invocation metadata/logging ([service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/service.py:320));
- runtime capability contracts ([runtime_execution.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/runtime_execution.py:66)).

It does not select a separate mutable action revision. The entire `ActionsDefinition` is versioned and execution snapshots are immutable.

Conclusion: do not keep semantic `version` in the target action map. Derive identity from the published `ActionsDefinition` revision plus `action_key`; generate a technical version only if an internal legacy contract still requires it.

## Input constraints

Only one variant is implemented:

```text
kind: "date_range"
start: canonical field path
end: canonical field path
start_not_in_past: boolean
```

Validation requires both fields to be:

- canonical fields;
- bound through `bindings`;
- required in the input schema;
- strings with `format: date`.

Evidence: [domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:120) and [domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend_core/runtime/capabilities/domain.py:415).

## Effective business-policy fields

Keep only:

- `requires_final_confirmation`;
- `requires_caller_phone`.

`requires_final_confirmation` changes the Voice Agent confirmation flow ([service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/service.py:112), [main.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/main.py:317)).

`requires_caller_phone` rejects execution when caller identity is unavailable ([service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/service.py:100)).

Drop:

- `requires_availability_proof`;
- `availability_proof_ttl_seconds`.

The former is explicitly rejected as unsupported ([capabilities.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/capabilities.py:119)); the latter has no effective consumer.

## HTTP codecs

Both request and response codecs support exactly:

```text
none | json | text
```

Evidence: [http_operation.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/http_operation.py:40) and [http_operation.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/http_operation.py:51).

Semantics:

- `none`: no body / no decoded response body; successful empty response becomes `null`;
- `json`: JSON encode/decode;
- `text`: UTF-8 text encode/decode;
- `text` request mappings must evaluate to a string ([domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:498)).

## Recursive `$expr` shape

The required mapping grammar is:

```text
MappingTemplate :=
    string | number | boolean | null
  | { "$expr": non-empty string }
  | { string: MappingTemplate }
  | [ MappingTemplate, ... ]
```

An expression object must contain exactly `$expr`; expressions are recursively supported in:

- HTTP path;
- query values;
- request mapping;
- response mapping.

Evidence: [http_operation.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/http_operation.py:20), [mapping.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/mapping.py:6), and [capabilities.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/capabilities.py:220).

Runtime contexts:

- capability request mapping: `business` plus `metadata` ([domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:487));
- response mapping: `response.status_code`, `response.content_type`, `response.body` ([worker.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/job-worker/src/job_worker/worker.py:466));
- post-call mapping: `call`, `agent`, and `inputs` ([service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/finalization/service.py:764)).

## Result-schema semantics

`result_schema` is optional Draft 2020-12 JSON Schema.

The flow is:

1. validate schema during action validation;
2. Worker decodes/mappings the provider response;
3. Backend validates `result.data` against `result_schema`;
4. Backend exposes only object, string, or null semantic results.

Evidence: [domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:211), [domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend_core/runtime/capabilities/domain.py:602), and [domain.py](/home/nikitachernsh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:616).

Worker execution-plan fields such as `plan_type`, `operation_id`, `integration_id`, `job_id`, `attempt`, and `expires_at` are generated technical fields, not `ActionsDefinition` authoring fields ([capability.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/capability.py:141), [domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:522)).

## Post-call artifacts

Supported artifact enums:

```text
artifact:
  transcript | call_recording | call_summary

representation:
  transcript: raw_json | plain_text
  call_recording: original | base64_text
  call_summary: plain_text
```

The compatibility matrix is enforced in [tenant_components.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/tenant_components.py:144).

# Final proposed schemas

## Policies

```yaml
Policies:
  type: object
  additionalProperties: false
  required: [cascade]
  properties:
    cascade:
      type: object
      additionalProperties: false
      required:
        - speech_activity
        - stt_commit
        - endpointing
        - interruption
        - response_scheduling
        - tokenizer
      properties:
        speech_activity:
          type: object
          additionalProperties: false
          required:
            - min_speech_seconds
            - min_silence_seconds
            - activation_threshold
          properties:
            min_speech_seconds:
              type: number
              exclusiveMinimum: 0
              maximum: 60
            min_silence_seconds:
              type: number
              exclusiveMinimum: 0
              maximum: 60
            activation_threshold:
              type: number
              minimum: 0
              maximum: 1

        stt_commit:
          oneOf:
            - type: object
              additionalProperties: false
              required: [strategy]
              properties:
                strategy:
                  const: local_vad
            - type: object
              additionalProperties: false
              required: [strategy, provider_vad]
              properties:
                strategy:
                  const: provider_vad
                provider_vad:
                  type: object
                  additionalProperties: false
                  required:
                    - threshold
                    - silence_threshold_seconds
                    - min_speech_ms
                    - min_silence_ms
                  properties:
                    threshold:
                      type: number
                      minimum: 0
                      maximum: 1
                    silence_threshold_seconds:
                      type: number
                      exclusiveMinimum: 0
                      maximum: 60
                    min_speech_ms:
                      type: integer
                      exclusiveMinimum: 0
                      maximum: 60000
                    min_silence_ms:
                      type: integer
                      exclusiveMinimum: 0
                      maximum: 60000

        endpointing:
          type: object
          additionalProperties: false
          required: [min_delay_seconds, max_delay_seconds]
          properties:
            min_delay_seconds:
              type: number
              exclusiveMinimum: 0
              maximum: 60
            max_delay_seconds:
              type: number
              exclusiveMinimum: 0
              maximum: 60

        interruption:
          type: object
          additionalProperties: false
          required:
            - enabled
            - min_duration_seconds
            - min_words
            - false_interruption_timeout_seconds
            - resume_after_false_interruption
          properties:
            enabled: { type: boolean }
            min_duration_seconds:
              type: number
              minimum: 0
              maximum: 60
            min_words:
              type: integer
              minimum: 0
            false_interruption_timeout_seconds:
              type: number
              minimum: 0
              maximum: 60
            resume_after_false_interruption:
              type: boolean

        response_scheduling:
          type: object
          additionalProperties: false
          required: [preemptive_generation, preemptive_tts]
          properties:
            preemptive_generation: { type: boolean }
            preemptive_tts: { type: boolean }

        tokenizer:
          type: object
          additionalProperties: false
          required: [min_sentence_chars]
          properties:
            min_sentence_chars:
              type: integer
              minimum: 3
              maximum: 200
```

## RealtimeDefaults

```yaml
RealtimeDefaults:
  type: object
  additionalProperties: false
  required:
    - deployment_ref
    - input_transcription
    - default_voice
    - turn_completion
    - interruption
  properties:
    deployment_ref:
      type: string
      format: uuid

    input_transcription:
      type: object
      additionalProperties: false
      required: [deployment_ref]
      properties:
        deployment_ref:
          type: string
          format: uuid

    default_voice:
      type: string
      minLength: 1
      default: marin

    turn_completion:
      oneOf:
        - type: object
          additionalProperties: false
          required: [strategy]
          properties:
            strategy:
              const: server_vad
            activation_threshold:
              type: number
              minimum: 0
              maximum: 1
              default: 0.5
            silence_duration_ms:
              type: integer
              exclusiveMinimum: 0
              default: 200
        - type: object
          additionalProperties: false
          required: [strategy]
          properties:
            strategy:
              const: semantic_vad
            eagerness:
              type: string
              enum: [auto, low, medium, high]
              default: auto

    interruption:
      type: object
      additionalProperties: false
      required: [enabled]
      properties:
        enabled:
          type: boolean
          default: true
```

## AgentPersonality

```yaml
AgentPersonality:
  type: object
  additionalProperties: false
  required:
    - identity
    - display_name
    - greeting
    - conversation_scope
  properties:
    identity:
      type: string
      minLength: 1
      maxLength: 100
      pattern: "^[a-z][a-z0-9_]*$"
      description: Stable semantic agent identifier exposed as post-call agent.id

    display_name:
      type: string
      minLength: 1
      maxLength: 100

    greeting:
      type: string
      minLength: 1
      maxLength: 1000

    conversation_scope:
      type: string
      enum: [property_only]
```

## ActionsDefinition

```yaml
ActionsDefinition:
  type: object
  additionalProperties: false
  required: [actions]
  properties:
    actions:
      type: object
      additionalProperties:
        oneOf:
          - $ref: RuntimeActionDefinition
          - $ref: PostCallActionDefinition

RuntimeActionDefinition:
  type: object
  additionalProperties: false
  required:
    - phase
    - description
    - announcement
    - agent_input_schema
    - execution
  properties:
    phase:
      const: runtime
    description:
      type: string
      minLength: 1
      maxLength: 1000
    announcement:
      oneOf:
        - type: string
          minLength: 1
          maxLength: 1000
        - type: object
          additionalProperties:
            type: string
    agent_input_schema:
      type: object
      description: Closed local Draft 2020-12 JSON Schema
    bindings:
      type: object
      additionalProperties:
        type: string
    input_constraints:
      type: array
      items:
        type: object
        additionalProperties: false
        required: [kind, start, end]
        properties:
          kind:
            const: date_range
          start:
            type: string
          end:
            type: string
          start_not_in_past:
            type: boolean
            default: false
    business_policy:
      type: object
      additionalProperties: false
      properties:
        requires_final_confirmation:
          type: boolean
          default: false
        requires_caller_phone:
          type: boolean
          default: false
    execution:
      $ref: HttpSemanticExecution
    result_schema:
      type: [object, "null"]

PostCallActionDefinition:
  type: object
  additionalProperties: false
  required:
    - phase
    - artifact_inputs
    - execution
  properties:
    phase:
      const: post_call
    artifact_inputs:
      type: object
      additionalProperties: false
      additionalProperties:
        type: object
        additionalProperties: false
        required: [artifact, representation]
        properties:
          artifact:
            type: string
            enum: [transcript, call_recording, call_summary]
          representation:
            type: string
            enum: [raw_json, plain_text, original, base64_text]
    execution:
      $ref: HttpSemanticExecution
    result_schema:
      type: [object, "null"]

HttpSemanticExecution:
  type: object
  additionalProperties: false
  required:
    - integration_key
    - method
    - timeout_seconds
    - request
    - response
  properties:
    integration_key:
      type: string
      minLength: 1
    method:
      type: string
      enum: [GET, POST, PUT, PATCH, DELETE]
    path:
      oneOf:
        - type: string
        - $ref: ExprNode
        - type: "null"
    query:
      type: [object, "null"]
    headers:
      type: object
      additionalProperties:
        type: string
    request:
      $ref: HttpRequestSpec
    response:
      $ref: HttpResponseSpec
    timeout_seconds:
      type: number
      exclusiveMinimum: 0
      maximum: 60
    success_statuses:
      type: [array, "null"]
      maxItems: 20

HttpRequestSpec:
  type: object
  additionalProperties: false
  required: [codec]
  properties:
    codec:
      type: string
      enum: [none, json, text]
    mapping:
      $ref: MappingTemplate
    content_type:
      type: [string, "null"]

HttpResponseSpec:
  type: object
  additionalProperties: false
  required: [codec]
  properties:
    codec:
      type: string
      enum: [none, json, text]
    mapping:
      $ref: MappingTemplate

MappingTemplate:
  oneOf:
    - type: string
    - type: number
    - type: boolean
    - type: "null"
    - $ref: ExprNode
    - type: object
      additionalProperties:
        $ref: MappingTemplate
    - type: array
      items:
        $ref: MappingTemplate

ExprNode:
  type: object
  additionalProperties: false
  required: [$expr]
  properties:
    $expr:
      type: string
      minLength: 1
      maxLength: 20000
```
