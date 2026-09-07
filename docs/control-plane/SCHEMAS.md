# Control Plane Semantic Schemas

> Status: **frozen target semantic schemas**
>
> This document defines the canonical payload schemas for Control Plane
> configuration components, catalogs, registries, and managed resources.
>
> It complements:
>
> - [`ARCHITECTURE.md`](./ARCHITECTURE.md) — domains, building blocks, repositories,
>   application services, and execution model.
> - [`CONTRACTS.md`](./CONTRACTS.md) — HTTP interfaces, DTOs, concurrency,
>   idempotency, authorization, errors, and transactional guarantees.
> - [`INVARIANTS.md`](./INVARIANTS.md) — non-negotiable architectural rules.
>
> These schemas define **semantic ownership**. They are not persistence schemas and
> they must not be reshaped merely to match the current/legacy implementation.

---

## Table of Contents

- [1. Schema conventions](#1-schema-conventions)
- [2. Common semantic types](#2-common-semantic-types)
- [3. Platform versioned components](#3-platform-versioned-components)
- [4. System live components](#4-system-live-components)
- [5. Tenant versioned components](#5-tenant-versioned-components)
- [6. Tenant live components](#6-tenant-live-components)
- [7. Action schemas](#7-action-schemas)
- [8. Catalog schemas](#8-catalog-schemas)
- [9. Registry schemas](#9-registry-schemas)
- [10. Managed resource schemas](#10-managed-resource-schemas)
- [11. Cross-schema semantic rules](#11-cross-schema-semantic-rules)
- [12. Migration mapping from legacy schemas](#12-migration-mapping-from-legacy-schemas)

---

# 1. Schema conventions

Unless otherwise stated:

```yaml
type: object
additionalProperties: false
```

Unknown fields are rejected.

## Optionality

A field not listed in `required` is optional.

- omitted field = not provided;
- `null` is valid only where explicitly declared;
- do not use `null` when omission already has the same semantic meaning.

## Runtime override semantics

```text
field absent      → inherit effective system value
field present     → override effective system value
empty list        → explicit empty list
unknown field     → invalid
```

## References

References are semantic references. Validation must verify target existence,
compatible scope/ownership, and usable state where required.

## Provider/model identity

Provider/model identity belongs to `ProviderConnection` and `ModelDeployment`.

Runtime configuration must not duplicate arbitrary provider/model/deployment
strings or credential graph data.

## Schema version
Unless otherwise stated, every component schema defined in this document
is schema_version = 1.

---

# 2. Common semantic types

```yaml
DeploymentRef:
  type: string
  format: uuid
  description: Reference to a ModelDeployment

CredentialRef:
  type: string
  format: uuid

ProviderConnectionRef:
  type: string
  format: uuid

Locale:
  type: string
  pattern: "^[a-z]{2,3}(?:-[A-Z]{2})?$"

Timezone:
  type: string
  description: IANA timezone identifier

SemanticKey:
  type: string
  minLength: 1
  maxLength: 128
  pattern: "^[a-z][a-z0-9_.-]*$"

ReasoningEffort:
  type: string
  enum: [none, low, medium, high, xhigh, max]
```

---

# 3. Platform versioned components

All platform prompt values share one semantic shape.

## SystemPrompt

```yaml
SystemPrompt:
  type: object
  additionalProperties: false
  required: [content]
  properties:
    content:
      type: string
      minLength: 1
```

Scope: `PlatformScope`.

## ProfilePrompt

```yaml
ProfilePrompt:
  type: object
  additionalProperties: false
  required: [content]
  properties:
    content:
      type: string
      minLength: 1
```

Scope: `ProfileScope(profile_key)`.

`profile_key` must exist in `ProfileCatalog`.

## InteractionPrompt

```yaml
InteractionPrompt:
  type: object
  additionalProperties: false
  required: [content]
  properties:
    content:
      type: string
      minLength: 1
```

Scope: `InteractionModeScope(mode_key)`.

`mode_key` must exist in `InteractionModeCatalog`.

---

# 4. System live components

## STTDefaults

```yaml
STTDefaults:
  type: object
  additionalProperties: false
  required: [deployment_ref]
  properties:
    deployment_ref:
      $ref: DeploymentRef
```

Validation:

- referenced deployment exists;
- deployment kind is `stt`;
- deployment supports cascade STT where required.

Pipeline/VAD behavior does not belong here.

---

## LLMDefaults

```yaml
LLMDefaults:
  type: object
  additionalProperties: false
  required:
    - deployment_ref
    - max_completion_tokens
  properties:
    deployment_ref:
      $ref: DeploymentRef

    temperature:
      type: [number, "null"]
      minimum: 0
      maximum: 2
      default: null
      description: Null means omit the parameter and use provider/model behavior.

    reasoning_effort:
      oneOf:
        - $ref: ReasoningEffort
        - type: "null"
      default: null

    max_completion_tokens:
      type: integer
      exclusiveMinimum: 0
```

Validation:

- deployment kind is `llm`;
- `temperature` requires deployment capability support;
- `reasoning_effort` requires deployment capability support.

---

## TTSDefaults

```yaml
TTSDefaults:
  type: object
  additionalProperties: false
  required:
    - deployment_ref
    - default_voice_id
  properties:
    deployment_ref:
      $ref: DeploymentRef

    default_voice_id:
      type: string
      minLength: 1
      maxLength: 255
```

Tokenizer/pipeline behavior does not belong here.

---

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
      $ref: DeploymentRef

    input_transcription:
      type: object
      additionalProperties: false
      required: [deployment_ref]
      properties:
        deployment_ref:
          $ref: DeploymentRef

    default_voice:
      type: string
      minLength: 1
      maxLength: 255
      default: marin

    turn_completion:
      oneOf:
        - $ref: RealtimeServerVAD
        - $ref: RealtimeSemanticVAD

    interruption:
      type: object
      additionalProperties: false
      required: [enabled]
      properties:
        enabled:
          type: boolean
          default: true
```

### RealtimeServerVAD

```yaml
RealtimeServerVAD:
  type: object
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
```

### RealtimeSemanticVAD

```yaml
RealtimeSemanticVAD:
  type: object
  additionalProperties: false
  required: [strategy]
  properties:
    strategy:
      const: semantic_vad

    eagerness:
      type: string
      enum: [auto, low, medium, high]
      default: auto
```

Validation:

- `deployment_ref` resolves to realtime deployment;
- transcription ref resolves to STT deployment supporting realtime transcription;
- selected turn-completion strategy is supported by deployment capabilities;
- interruption/turn-completion fields must map to actual runtime behavior.

---

## Policies

`Policies` owns system-wide cascade pipeline behavior.

```yaml
Policies:
  type: object
  additionalProperties: false
  required: [cascade]
  properties:
    cascade:
      $ref: CascadePolicies
```

### CascadePolicies

```yaml
CascadePolicies:
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
      $ref: CascadeSpeechActivity
    stt_commit:
      $ref: CascadeSTTCommit
    endpointing:
      $ref: CascadeEndpointing
    interruption:
      $ref: CascadeInterruption
    response_scheduling:
      $ref: CascadeResponseScheduling
    tokenizer:
      $ref: CascadeTokenizer
```

### CascadeSpeechActivity

```yaml
CascadeSpeechActivity:
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
```

### CascadeSTTCommit

```yaml
CascadeSTTCommit:
  oneOf:
    - type: object
      additionalProperties: false
      required: [strategy]
      properties:
        strategy:
          const: local_vad

    - type: object
      additionalProperties: false
      required:
        - strategy
        - provider_vad
      properties:
        strategy:
          const: provider_vad
        provider_vad:
          $ref: ProviderVAD
```

### ProviderVAD

```yaml
ProviderVAD:
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
      minimum: 1
      maximum: 60000

    min_silence_ms:
      type: integer
      minimum: 1
      maximum: 60000
```

### CascadeEndpointing

```yaml
CascadeEndpointing:
  type: object
  additionalProperties: false
  required:
    - min_delay_seconds
    - max_delay_seconds
  properties:
    min_delay_seconds:
      type: number
      exclusiveMinimum: 0
      maximum: 60

    max_delay_seconds:
      type: number
      exclusiveMinimum: 0
      maximum: 60
```

Invariant:

```text
min_delay_seconds <= max_delay_seconds
```

### CascadeInterruption

```yaml
CascadeInterruption:
  type: object
  additionalProperties: false
  required:
    - enabled
    - min_duration_seconds
    - min_words
    - false_interruption_timeout_seconds
    - resume_after_false_interruption
  properties:
    enabled:
      type: boolean

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
```

### CascadeResponseScheduling

```yaml
CascadeResponseScheduling:
  type: object
  additionalProperties: false
  required:
    - preemptive_generation
    - preemptive_tts
  properties:
    preemptive_generation:
      type: boolean
    preemptive_tts:
      type: boolean
```

### CascadeTokenizer

```yaml
CascadeTokenizer:
  type: object
  additionalProperties: false
  required: [min_sentence_chars]
  properties:
    min_sentence_chars:
      type: integer
      minimum: 3
      maximum: 200
```

The following are implementation choices, not policy fields:

- cascade `turn_detection = stt`;
- provider locale conversion;
- transport timeout/retry settings;
- provider kind gates;
- provider/model identity.

---

# 5. Tenant versioned components

## TenantPrompt

```yaml
TenantPrompt:
  type: object
  additionalProperties: false
  required: [content]
  properties:
    content:
      type: string
      minLength: 1
```

---

## Knowledge

Knowledge v1 is inline only.

```yaml
Knowledge:
  type: object
  additionalProperties: false
  required: [content]
  properties:
    content:
      type: string
```

Future RAG/artifact semantics require a new schema version.

---

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
      description: Stable semantic agent identity, distinct from ProfileReference.

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

---

## BusinessInfo

```yaml
BusinessInfo:
  type: object
  additionalProperties: false
  required:
    - business
    - contact
    - localization
  properties:
    business:
      type: object
      additionalProperties: false
      required:
        - name
        - type
      properties:
        name:
          type: string
          minLength: 1
          maxLength: 255

        type:
          type: string
          minLength: 1
          maxLength: 64

    contact:
      type: object
      additionalProperties: false
      required:
        - phones
        - emails
      properties:
        address:
          type: [string, "null"]
          maxLength: 1000

        phones:
          type: array
          maxItems: 20
          items:
            type: string

        emails:
          type: array
          maxItems: 20
          items:
            type: string
            format: email

        website:
          type: [string, "null"]
          maxLength: 2048

    localization:
      type: object
      additionalProperties: false
      required:
        - default_locale
        - timezone
      properties:
        default_locale:
          $ref: Locale

        timezone:
          $ref: Timezone
```

---

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
```

The map key is the canonical `action_key`.

Action-key constraints:

```yaml
type: string
minLength: 1
maxLength: 128
pattern: "^[a-z][a-z0-9_.-]*$"
```

The key is not duplicated inside each action definition.

There is no per-action semantic version. Version identity is:

```text
published ActionsDefinition revision + action_key
```

---

# 6. Tenant live components

## Architecture

```yaml
Architecture:
  type: object
  additionalProperties: false
  required: [architecture_key]
  properties:
    architecture_key:
      type: string
      minLength: 1
      maxLength: 64
```

Validation:

```text
architecture_key → ArchitectureRegistry
```

There is no ordered fallback list.

If the selected architecture cannot be materialized, execution creation fails.

---

## ProfileReference

```yaml
ProfileReference:
  type: object
  additionalProperties: false
  required: [profile_key]
  properties:
    profile_key:
      type: string
      minLength: 1
      maxLength: 255
```

Validation:

- profile exists;
- profile is enabled/usable;
- associated profile prompt satisfies platform invariants.

---

## RuntimeOverrides

```yaml
RuntimeOverrides:
  type: object
  additionalProperties: false
  properties:
    stt:
      type: object
      additionalProperties: false
      properties:
        keyterms:
          type: array
          maxItems: 50
          items:
            type: string
            minLength: 1
            maxLength: 64

    tts:
      type: object
      additionalProperties: false
      properties:
        voice_id:
          type: string
          minLength: 1
          maxLength: 255

    realtime:
      type: object
      additionalProperties: false
      properties:
        voice:
          type: string
          minLength: 1
          maxLength: 255
```

Semantics:

```text
field absent              → inherit
stt.keyterms = []         → explicit empty keyterm set
tts.voice_id present      → override cascade voice
realtime.voice present    → override realtime voice
```

Not supported:

- tenant deployment overrides;
- tenant LLM overrides;
- tenant temperature/reasoning overrides.

---

## ActionsAvailability

```yaml
ActionsAvailability:
  type: object
  additionalProperties: false
  required: [actions]
  properties:
    actions:
      type: object
      additionalProperties:
        type: boolean
```

Semantics:

```text
present + true   → enabled
present + false  → disabled
missing key      → disabled
unknown key      → invalid
```

Every key must exist in effective `ActionsDefinition`.

---

# 7. Action schemas

## RuntimeActionDefinition

```yaml
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
      description: Closed local JSON Schema Draft 2020-12 object.

    bindings:
      type: object
      description: >
        Maps agent-facing input field names from agent_input_schema to canonical
        business field paths. Binding values do not include the `business.` prefix.
      additionalProperties:
        type: string

    input_constraints:
      type: array
      items:
        $ref: DateRangeConstraint

    business_policy:
      $ref: RuntimeBusinessPolicy

    execution:
      $ref: HttpSemanticExecution

    result_schema:
      oneOf:
        - type: object
        - type: "null"
```

## Runtime action input semantics

Runtime action input processing follows this sequence:

```text
agent tool arguments
→ agent_input_schema validation
→ canonical binding + normalization
→ input constraints
→ business policy
→ execution mapping
```

### Binding direction

`bindings` maps an **agent-facing input field name** to a **canonical business field
path**.

Example:

```yaml
agent_input_schema:
  type: object
  required:
    - check_in
    - check_out
    - room_type
  properties:
    check_in:
      type: string
      format: date
    check_out:
      type: string
      format: date
    room_type:
      type: integer

bindings:
  check_in: stay.check_in
  check_out: stay.check_out
  room_type: allocation.room_type
```

Direction:

```text
agent input field → canonical business path
```

Binding targets do not include the `business.` prefix.

For example:

```text
stay.check_in
```

is exposed to runtime mapping expressions as:

```text
business.stay.check_in
```

Rules:

- every binding key must name a field in `agent_input_schema.properties`;
- every binding target must be a valid canonical field reference;
- one canonical target may be bound by at most one agent input field;
- bindings may cover only a subset of agent input fields;
- unbound agent input fields remain valid action inputs but are not projected into
  the canonical `business` object.

### Validated and normalized inputs

After `agent_input_schema` validation, bound fields are normalized according to the
semantic rules of their canonical target.

The normalized value:

1. replaces the corresponding value in the action `inputs` object; and
2. is written to the canonical `business` projection at the binding target path.

Unbound fields remain in `inputs` unchanged unless another explicitly documented
normalization rule applies to them.

Example:

```text
raw tool arguments:
{
  "phone": "0900 123 456",
  "note": "Window seat"
}

bindings:
  phone: guest.phone
```

after normalization:

```text
inputs.phone
→ normalized phone value

business.guest.phone
→ the same normalized phone value

inputs.note
→ "Window seat"

business.note
→ does not exist
```

There is no separate raw-input expression namespace.

### Runtime expression context

Runtime action request `MappingTemplate` expressions receive:

```text
inputs
business
metadata
```

Where:

- `inputs` is the complete validated and normalized tool-argument object using
  agent-facing field names;
- `business` is the canonical projection created from `bindings`;
- `metadata` contains execution/runtime metadata supplied by Backend.

Example:

```yaml
request:
  codec: json
  mapping:
    start_date:
      $expr: business.stay.check_in
    room_type:
      $expr: inputs.room_type
```

Both expressions operate on validated/normalized values.

### Constraint references

Input constraints operate on canonical business references, not agent-facing field
names.

Example:

```yaml
input_constraints:
  - kind: date_range
    start: stay.check_in
    end: stay.check_out
    start_not_in_past: true
```

Therefore every canonical field referenced by a constraint must be reachable through
`bindings`.

For `DateRangeConstraint`:

- `start` and `end` must be valid canonical references;
- both references must be targets of `bindings`;
- their source fields must be required by `agent_input_schema`;
- their source field schemas must be `string` with `format: date`.

## PostCallActionDefinition

```yaml
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
      additionalProperties:
        $ref: PostCallArtifactInput

    execution:
      $ref: HttpSemanticExecution

    result_schema:
      oneOf:
        - type: object
        - type: "null"
```

## PostCallArtifactInput

```yaml
PostCallArtifactInput:
  oneOf:
    - type: object
      additionalProperties: false
      required: [artifact, representation]
      properties:
        artifact:
          const: transcript
        representation:
          enum: [raw_json, plain_text]

    - type: object
      additionalProperties: false
      required: [artifact, representation]
      properties:
        artifact:
          const: call_recording
        representation:
          enum: [original, base64_text]

    - type: object
      additionalProperties: false
      required: [artifact, representation]
      properties:
        artifact:
          const: call_summary
        representation:
          const: plain_text
```

## DateRangeConstraint

```yaml
DateRangeConstraint:
  type: object
  additionalProperties: false
  required:
    - kind
    - start
    - end
  properties:
    kind:
      const: date_range

    start:
      type: string
      minLength: 1

    end:
      type: string
      minLength: 1

    start_not_in_past:
      type: boolean
      default: false
```

Validation:

- `start` and `end` are canonical field references;
- both are bound through `bindings`;
- both are required in `agent_input_schema`;
- both are strings with `format: date`.

## RuntimeBusinessPolicy

```yaml
RuntimeBusinessPolicy:
  type: object
  additionalProperties: false
  properties:
    requires_final_confirmation:
      type: boolean
      default: false

    requires_caller_phone:
      type: boolean
      default: false
```

Not included:

- `requires_availability_proof`;
- `availability_proof_ttl_seconds`.

## HttpSemanticExecution

```yaml
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
      maxLength: 255

    method:
      enum: [GET, POST, PUT, PATCH, DELETE]

    path:
      oneOf:
        - type: string
        - $ref: ExprNode
        - type: "null"

    query:
      oneOf:
        - type: "null"
        - type: object
          additionalProperties:
            $ref: MappingTemplate

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
      oneOf:
        - type: "null"
        - type: array
          maxItems: 20
          items:
            type: integer
            minimum: 100
            maximum: 599
```

Semantic `execution.type: http` is intentionally absent.

Technical Worker execution plans may still use an internal `plan_type`.

## HttpRequestSpec

```yaml
HttpRequestSpec:
  type: object
  additionalProperties: false
  required: [codec]
  properties:
    codec:
      enum: [none, json, text]

    mapping:
      $ref: MappingTemplate

    content_type:
      type: [string, "null"]
```

Semantics:

```text
none → no request body
json → JSON encode mapping result
text → mapping result must be string
```

## HttpResponseSpec

```yaml
HttpResponseSpec:
  type: object
  additionalProperties: false
  required: [codec]
  properties:
    codec:
      enum: [none, json, text]

    mapping:
      $ref: MappingTemplate
```

Semantics:

```text
none → no decoded body / semantic null
json → JSON decode
text → UTF-8 text decode
```

## MappingTemplate

```text
MappingTemplate :=
    string
  | number
  | boolean
  | null
  | ExprNode
  | object<string, MappingTemplate>
  | array<MappingTemplate>
```

```yaml
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

Expression contexts:

```text
runtime request:
  inputs
  business
  metadata

response mapping:
  response.status_code
  response.content_type
  response.body

post-call:
  call
  agent
  inputs
```

Secrets are not available to mapping expressions.

## Result schema semantics

`result_schema` is optional JSON Schema Draft 2020-12.

Flow:

```text
validate definition
→ execute request
→ decode/map response
→ validate semantic result
→ expose semantic result
```

Allowed semantic result forms:

```text
object
string
null
```

Worker technical fields such as `plan_type`, `operation_id`, `integration_id`,
`job_id`, `attempt`, and `expires_at` are not authoring fields.

---

# 8. Catalog schemas

## Profile

```yaml
Profile:
  type: object
  additionalProperties: false
  required:
    - key
    - name
    - description
    - status
  properties:
    key:
      type: string
      minLength: 1
      maxLength: 255

    name:
      type: string
      minLength: 1
      maxLength: 255

    description:
      type: string
      maxLength: 2000

    status:
      enum: [enabled, disabled]
```

`ProfilePrompt` remains a separate versioned component.

## InteractionMode

```yaml
InteractionMode:
  type: object
  additionalProperties: false
  required:
    - key
    - name
    - description
    - status
  properties:
    key:
      type: string
      minLength: 1
      maxLength: 255

    name:
      type: string
      minLength: 1
      maxLength: 255

    description:
      type: string
      maxLength: 2000

    status:
      enum: [enabled, disabled]
```

`InteractionPrompt` remains a separate versioned component.

---

# 9. Registry schemas

Registries are code-defined and read-only.

## RegistryEntry

```yaml
RegistryEntry:
  type: object
  additionalProperties: false
  required:
    - key
    - name
    - description
    - metadata
  properties:
    key:
      type: string
    name:
      type: string
    description:
      type: string
    metadata:
      type: object
```

## ComponentDefinition

```yaml
ComponentDefinition:
  type: object
  additionalProperties: false
  required:
    - key
    - schema_version
    - allowed_scopes
    - value_schema
    - metadata
  properties:
    key:
      type: string

    schema_version:
      type: integer
      minimum: 1

    allowed_scopes:
      type: array
      minItems: 1
      uniqueItems: true
      items:
        type: string

    value_schema:
      type: object

    metadata:
      type: object
```

---

# 10. Managed resource schemas

These are semantic resource shapes. HTTP DTO details belong to `CONTRACTS.md`.

## Credential

```yaml
Credential:
  type: object
  additionalProperties: false
  required:
    - id
    - scope
    - name
    - status
    - active_secret_version
  properties:
    id:
      type: string
      format: uuid

    scope:
      oneOf:
        - type: object
          additionalProperties: false
          required: [type]
          properties:
            type:
              const: platform

        - type: object
          additionalProperties: false
          required: [type, tenant_id]
          properties:
            type:
              const: tenant
            tenant_id:
              type: string

    name:
      type: string
      minLength: 1
      maxLength: 255

    status:
      enum: [active, revoked]

    active_secret_version:
      type: integer
      minimum: 1
```

Secret material is never part of normal reads.

---

## ProviderConnection

```yaml
ProviderConnection:
  type: object
  additionalProperties: false
  required:
    - id
    - key
    - provider_kind
    - credential_ref
    - connection_config
    - enabled
  properties:
    id:
      type: string
      format: uuid

    key:
      type: string
      minLength: 1
      maxLength: 255

    provider_kind:
      type: string
      minLength: 1
      maxLength: 64

    credential_ref:
      $ref: CredentialRef

    connection_config:
      type: object

    enabled:
      type: boolean
```

Validation:

- `provider_kind` exists in `ProviderKindRegistry`;
- `credential_ref` resolves to an existing `Credential`;
- referenced credential must have `scope.type = platform`;
- referenced credential must not be revoked when the connection is required to be
  usable;
- enabled connection requires a usable credential;
- `connection_config` is provider-kind validated.

Credential ownership rule:

```text
ProviderConnection.credential_ref
→ Credential(scope.type = platform)
```

---

## ModelDeployment

```yaml
ModelDeployment:
  type: object
  additionalProperties: false
  required:
    - id
    - key
    - connection_ref
    - deployment_kind
    - deployment_config
    - capabilities
    - enabled
  properties:
    id:
      type: string
      format: uuid

    key:
      type: string
      minLength: 1
      maxLength: 255

    connection_ref:
      $ref: ProviderConnectionRef

    deployment_kind:
      enum: [llm, realtime, stt, tts]

    deployment_config:
      type: object

    capabilities:
      oneOf:
        - $ref: LLMDeploymentCapabilities
        - $ref: RealtimeDeploymentCapabilities
        - $ref: STTDeploymentCapabilities
        - $ref: TTSDeploymentCapabilities

    enabled:
      type: boolean
```

### LLMDeploymentCapabilities

```yaml
LLMDeploymentCapabilities:
  type: object
  additionalProperties: false
  required:
    - kind
    - supports_temperature
    - supports_reasoning_effort
  properties:
    kind:
      const: llm
    supports_temperature:
      type: boolean
    supports_reasoning_effort:
      type: boolean
```

### RealtimeDeploymentCapabilities

```yaml
RealtimeDeploymentCapabilities:
  type: object
  additionalProperties: false
  required:
    - kind
    - supports_server_vad
    - supports_semantic_vad
  properties:
    kind:
      const: realtime
    supports_server_vad:
      type: boolean
    supports_semantic_vad:
      type: boolean
```

### STTDeploymentCapabilities

```yaml
STTDeploymentCapabilities:
  type: object
  additionalProperties: false
  required:
    - kind
    - supports_cascade
    - supports_realtime_input_transcription
  properties:
    kind:
      const: stt
    supports_cascade:
      type: boolean
    supports_realtime_input_transcription:
      type: boolean
```

### TTSDeploymentCapabilities

```yaml
TTSDeploymentCapabilities:
  type: object
  additionalProperties: false
  required: [kind]
  properties:
    kind:
      const: tts
```

Provider-specific model/deployment identity belongs to `deployment_config`.

---

## PhoneNumberAssignment

```yaml
PhoneNumberAssignment:
  type: object
  additionalProperties: false
  required:
    - id
    - tenant_id
    - phone_number
    - enabled
  properties:
    id:
      type: string
      format: uuid
    tenant_id:
      type: string
    phone_number:
      type: string
      description: Normalized E.164 phone number
    enabled:
      type: boolean
```

---

## HandoffDestination

```yaml
HandoffDestination:
  type: object
  additionalProperties: false
  required:
    - id
    - tenant_id
    - key
    - description
    - phone_number
    - enabled
  properties:
    id:
      type: string
      format: uuid

    tenant_id:
      type: string

    key:
      type: string
      minLength: 1
      maxLength: 64
      pattern: "^[a-z][a-z0-9_]*$"

    description:
      type: string
      minLength: 1
      maxLength: 1000

    phone_number:
      type: string
      description: Normalized E.164 phone number

    enabled:
      type: boolean
```

---

## IntegrationConnection

```yaml
IntegrationConnection:
  type: object
  additionalProperties: false
  required:
    - id
    - tenant_id
    - key
    - integration_kind
    - config
    - enabled
  properties:
    id:
      type: string
      format: uuid

    tenant_id:
      type: string

    key:
      type: string
      minLength: 1
      maxLength: 255

    integration_kind:
      type: string
      minLength: 1
      maxLength: 64

    config:
      type: object

    credential_ref:
      oneOf:
        - $ref: CredentialRef
        - type: "null"

    enabled:
      type: boolean
```

Validation:

- `integration_kind` exists in `IntegrationKindRegistry`;
- if `credential_ref` is present, it resolves to an existing `Credential`;
- referenced credential must have `scope.type = tenant`;
- referenced credential `tenant_id` must equal `IntegrationConnection.tenant_id`;
- referenced credential must not be revoked when the integration is required to be
  usable;
- key is unique within the tenant;
- `config` is validated by the integration-kind-specific schema.

Credential ownership rule:

```text
IntegrationConnection.credential_ref
→ Credential(
    scope.type = tenant,
    scope.tenant_id = IntegrationConnection.tenant_id
  )
```

Action authoring references integrations by semantic `integration_key`, not resource
UUID.

---

# 11. Cross-schema semantic rules

## Architecture

```text
Architecture.architecture_key
→ ArchitectureRegistry
```

No silent fallback.

## Profiles

```text
ProfileReference.profile_key
→ ProfileCatalog.Profile.key
→ ProfilePrompt(ProfileScope(profile_key))
```

## Runtime deployments

```text
STTDefaults.deployment_ref
→ ModelDeployment(kind = stt)

LLMDefaults.deployment_ref
→ ModelDeployment(kind = llm)

TTSDefaults.deployment_ref
→ ModelDeployment(kind = tts)

RealtimeDefaults.deployment_ref
→ ModelDeployment(kind = realtime)

RealtimeDefaults.input_transcription.deployment_ref
→ ModelDeployment(kind = stt, realtime-transcription capable)
```

## Credential ownership

```text
ProviderConnection.credential_ref
→ Credential(scope.type = platform)

IntegrationConnection.credential_ref
→ Credential(
    scope.type = tenant,
    scope.tenant_id = IntegrationConnection.tenant_id
  )
```

References do not transfer ownership and do not imply cascade deletion.

## Actions

```text
ActionsDefinition.actions[action_key]
+
ActionsAvailability.actions[action_key]
→ effective action
```

Missing availability key = disabled.

Unknown availability key = invalid.

## Integrations

```text
ActionsDefinition.execution.integration_key
→ IntegrationConnection.key within same tenant
```

Resource IDs are resolved internally.

## Agent identity

`AgentPersonality.identity` is distinct from:

- `ProfileReference.profile_key`;
- `display_name`;
- `tenant_id`.

## Localization

Runtime locale/timezone come from:

```text
BusinessInfo.localization.default_locale
BusinessInfo.localization.timezone
```

## Secrets

No semantic schema in this document embeds runtime secrets.

Secrets remain protected and late-bound.

---

# 12. Migration mapping from legacy schemas

```text
OLD                                         TARGET

platform llm provider/model               → ModelDeployment / ProviderConnection
platform llm request options              → LLMDefaults

platform stt provider/model               → ModelDeployment
platform VAD/endpointing/interruption     → Policies.cascade

platform tts provider/model               → ModelDeployment
platform tts voice                        → TTSDefaults.default_voice_id
platform min_sentence_chars               → Policies.cascade.tokenizer

realtime deployment                       → RealtimeDefaults.deployment_ref
realtime transcription deployment         → RealtimeDefaults.input_transcription
realtime voice                            → RealtimeDefaults.default_voice
realtime VAD/interruption                 → RealtimeDefaults

tenant business/contact/localization      → BusinessInfo
tenant agent display/greeting/scope       → AgentPersonality
tenant agent_profile                      → AgentPersonality.identity
tenant profile selection                  → ProfileReference

tenant language                           → BusinessInfo.localization.default_locale
tenant timezone                           → BusinessInfo.localization.timezone
tenant STT keyterms                       → RuntimeOverrides.stt.keyterms
tenant cascade voice                      → RuntimeOverrides.tts.voice_id
tenant realtime voice                     → RuntimeOverrides.realtime.voice

tenant handoff destinations               → HandoffDestination ManagedResources

capabilities definitions                  ┐
                                           ├→ ActionsDefinition
post-call definitions                     ┘

capability/post-call enabled              → ActionsAvailability

capability connection/resource ID         → execution.integration_key
semantic execution.type=http              → removed

provider credentials                      → Credential
provider endpoint/config                  → ProviderConnection.connection_config
provider deployment identity              → ModelDeployment.deployment_config
```

Do not migrate into target semantic schemas:

```text
duplicated runtime provider/model strings
action enabled inside ActionsDefinition
semantic execution.type=http
semantic integration UUIDs
handoff phone numbers inside TenantConfiguration
handoff enabled/generation inside TenantConfiguration
per-action semantic version
requires_availability_proof
availability_proof_ttl_seconds
Worker job_id / attempt / expires_at / operation_id
raw ExecutionSnapshot internals
legacy revision/generation fields used only for client concurrency
```

---

## Final frozen inventory

### Platform VersionedComponents

```text
SystemPrompt
ProfilePrompt
InteractionPrompt
```

### System LiveComponents

```text
STTDefaults
LLMDefaults
TTSDefaults
RealtimeDefaults
Policies
```

### Tenant VersionedComponents

```text
TenantPrompt
Knowledge
AgentPersonality
BusinessInfo
ActionsDefinition
```

### Tenant LiveComponents

```text
Architecture
ProfileReference
RuntimeOverrides
ActionsAvailability
```

### Catalogs

```text
ProfileCatalog
InteractionModeCatalog
```

### Registries

```text
ArchitectureRegistry
ComponentDefinitionRegistry
ProviderKindRegistry
DeploymentKindRegistry
IntegrationKindRegistry
```

### ManagedResources

```text
Credential
ProviderConnection
ModelDeployment
PhoneNumberAssignment
HandoffDestination
IntegrationConnection
```

This inventory and the semantic ownership defined above are the frozen target for
the current Control Plane refactor.
