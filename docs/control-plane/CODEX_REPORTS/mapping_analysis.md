# 1. Executive summary

The frozen target can be defined confidently for:

- `LLMDefaults`
- `STTDefaults`
- `TTSDefaults`
- `RealtimeDefaults`
- `AgentPersonality`
- `BusinessInfo`
- `Architecture`
- `ProfileReference`
- `ActionsAvailability`
- most of `ActionsDefinition`

The following remain unresolved:

1. `Policies` has no current semantic consumer or implementation.
2. Whether tenant runtime overrides may select deployments, or only override request/pipeline options.
3. Whether `agent_profile` is an identity key or an accidental duplicate of profile selection.
4. Whether realtime interruption settings are intended to affect runtime behavior; they are currently validated/materialized but not passed to `AgentSession`.
5. Exact target representation of knowledge artifacts versus current inline knowledge.
6. Whether generic HTTP actions and managed webhook actions should remain separate semantic execution kinds.

Target architecture evidence: system runtime defaults are live structured components; tenant semantic content is versioned; tenant selections and overrides are live; references must resolve during materialization; snapshots contain no secrets ([ARCHITECTURE.md](/home/nikitachernysh/Storage/Projects/agentic-backend/docs/control-plane/ARCHITECTURE.md:250), [ARCHITECTURE.md](/home/nikitachernysh/Storage/Projects/agentic-backend/docs/control-plane/ARCHITECTURE.md:302), [INVARIANTS.md](/home/nikitachernysh/Storage/Projects/agentic-backend/docs/control-plane/INVARIANTS.md:295), [INVARIANTS.md](/home/nikitachernysh/Storage/Projects/agentic-backend/docs/control-plane/INVARIANTS.md:487)).

Current runtime selection already uses deployment references and validates deployment capability compatibility ([runtime_components.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/runtime_components.py:26), [runtime_components.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/runtime_components.py:181), [runtime_resolver.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/application/runtime_resolver.py:188)).

The main migration problem is not missing runtime behavior. It is that current semantic ownership is split across:

- `agent.tenant`
- `runtime.*`
- `capabilities.tenant`
- `post_call.tenant`
- managed-resource references
- Backend-derived provider/model projections

Those must be collapsed into the frozen inventory without carrying provider/resource choreography into tenant runtime configuration.

---

# 2. Current-field inventory

| Current path | Defined in | Read by | Runtime effect | Required? | Notes |
|---|---|---|---|---|---|
| `runtime.llm.defaults.deployment_ref` | `runtime_components.py:26-30` | `runtime_resolver.py:188-235` | Selects LLM `ModelDeployment` | Yes | Consumed semantic field |
| `runtime.llm.defaults.temperature` | `runtime_components.py:28` | resolver, Backend projection, Voice Agent | LLM temperature when supported | Optional | Null means provider default |
| `runtime.llm.defaults.reasoning_effort` | `runtime_components.py:29` | resolver, Voice Agent | Reasoning request option | Optional | Capability-validated |
| `runtime.llm.defaults.max_completion_tokens` | `runtime_components.py:30` | Backend, Voice Agent | LLM output limit | Yes | Currently required |
| `runtime.stt.defaults.deployment_ref` | `runtime_components.py:33-34` | resolver | Selects cascade STT deployment | Yes | Capability-validated |
| `runtime.tts.defaults.deployment_ref` | `runtime_components.py:134-137` | resolver | Selects cascade TTS deployment | Yes | Capability-validated |
| `runtime.tts.defaults.default_voice_id` | same | resolver | Default cascade voice | Yes | Tenant voice can override it |
| `runtime.tts.defaults.min_sentence_chars` | same | Backend, Voice Agent | Sentence/tokenizer gating | Yes | Passed to Blingfire tokenizer ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:112)) |
| `runtime.cascade.execution.defaults.speech_activity.*` | `runtime_components.py:41-44,93-98` | Backend, Voice Agent | Local VAD speech activation | Yes | `min_speech_seconds`, `min_silence_seconds`, `activation_threshold` |
| `runtime.cascade.execution.defaults.stt_commit.strategy` | `runtime_components.py:47-66` | Backend, Voice Agent | Selects local-VAD versus provider-VAD commit | Yes | Discriminated union |
| `provider_vad.*` | `runtime_components.py:51-60` | Backend, Voice Agent | ElevenLabs server VAD parameters | Required for `provider_vad` | Provider compatibility checked |
| `endpointing.min_delay_seconds` | `runtime_components.py:69-77` | Backend, Voice Agent | Minimum endpointing delay | Yes | Ordered against maximum |
| `endpointing.max_delay_seconds` | same | Backend, Voice Agent | Maximum endpointing delay | Yes | Ordered against minimum |
| `interruption.*` | `runtime_components.py:80-85` | Voice Agent cascade session | Interruption thresholds and recovery | Yes | Fully consumed for cascade |
| `response_scheduling.*` | `runtime_components.py:88-90` | Voice Agent cascade session | Preemptive generation and TTS | Yes | Fully consumed for cascade |
| `runtime.realtime.execution.defaults.deployment_ref` | `runtime_components.py:126-131` | realtime resolver | Selects realtime deployment | Yes | Capability-validated |
| `input_transcription.deployment_ref` | same | realtime resolver, Voice Agent | Selects realtime transcription deployment | Yes | Separate deployment reference |
| `default_voice` | same | realtime resolver, Voice Agent | Realtime voice | Yes/defaulted | Current default is `marin` |
| `turn_completion.strategy` | same | resolver only in current Voice Agent path | Selects `server_vad` or `semantic_vad` | Yes | Voice Agent realtime construction currently does not apply it |
| `server_vad.activation_threshold` | `runtime_components.py:105-109` | resolver validation/materialization | Intended realtime server VAD tuning | Optional/default | Not passed by `create_realtime_session` |
| `server_vad.silence_duration_ms` | same | resolver validation/materialization | Intended realtime server VAD tuning | Optional/default | Same issue |
| `semantic_vad.eagerness` | `runtime_components.py:111-114` | resolver validation/materialization | Intended realtime semantic VAD tuning | Optional/default | Same issue |
| `realtime.interruption.enabled` | `runtime_components.py:122-124` | resolver | Intended realtime interruption policy | Optional/default | Not applied by Voice Agent |
| `runtime.architecture.policy.architectures` | `runtime_components.py:143-155` | resolver | Ordered architecture fallback selection | Yes | Current semantics are ordered preference, not a single scalar |
| `runtime.speech.overrides.language` | `runtime_components.py:163-169` | resolver, Backend | Provider language and runtime locale | Yes | Current tenant component is required |
| `runtime.speech.overrides.stt.keyterms` | `voice_runtime.py:89-95,164-168` | Backend, Voice Agent | STT keyterms | Optional | Canonicalized and sorted |
| `runtime.speech.overrides.voices.cascade` | `runtime_components.py:158-160` | resolver | Tenant cascade voice override | Nullable | Null currently falls back to TTS default |
| `runtime.speech.overrides.voices.realtime` | same | resolver | Tenant realtime voice override | Nullable | Null currently falls back to realtime default |
| `agent.tenant.display_name` | `agent_components.py:15-25` | Backend, Voice Agent, finalization | Assistant display name and finalization identity | Yes | Consumed |
| `agent.tenant.agent_profile` | same | Backend, finalization | Runtime agent identifier / finalization label | Yes | Not profile selection; semantic meaning is ambiguous |
| `agent.tenant.greeting` | same | Voice Agent | Initial greeting | Yes | Consumed |
| `agent.tenant.conversation_scope` | same | Voice Agent prompt context | Conversation policy text | Yes | Current enum only contains `property_only` |
| `agent.tenant.locale` | same | Backend, Voice Agent | Provider language and locale | Yes | Hidden required runtime field |
| `agent.tenant.timezone` | same | Backend capability constraints, Voice Agent | Date constraints and local-time prompt context | Yes | Hidden required runtime field |
| `prompt.profile.selection.profile_key` | `prompt_components.py:26-32` | execution resolver | Selects platform profile prompt | Yes | Must become `ProfileReference` |
| `prompt.*.content` | `prompt_components.py:13-23` | execution resolver, Voice Agent | Prompt text | Yes | `TenantPrompt` and platform prompt material |
| `knowledge.tenant.content` | `knowledge_components.py:13-25` | execution resolver, Voice Agent | Knowledge context | Yes currently | Current implementation is inline text |
| `capabilities.tenant.capabilities[*].enabled` | `capabilities.py:76-93` | execution resolver | Determines whether tool is exposed | No | Must move to `ActionsAvailability` |
| `capabilities.*.description` | same | Voice Agent tool construction | Tool description | Yes for enabled runtime action | Consumed |
| `capabilities.*.announcement` | same | Voice Agent | User-facing action announcement | Yes | Consumed |
| `capabilities.*.agent_input_schema` | same | Voice Agent, Backend validation | Tool input schema | Yes | Runtime-critical |
| `capabilities.*.bindings` | same | Backend normalization | Canonical field mapping | Optional | Required when canonical normalization is needed |
| `capabilities.*.input_constraints` | same | Backend | Date/business input constraints | Optional | Current supported constraint is `date_range` |
| `capabilities.*.business_policy` | same | Backend | Confirmation, caller phone, availability policy | Optional | Availability proof currently rejected |
| `capabilities.*.execution` | same | Backend, Worker | Builds execution plan | Yes | Current CP supports HTTP execution |
| `capabilities.*.result_schema` | same | Backend/Worker | Validates semantic result | Optional | Runtime-critical when present |
| `post_call.actions[*].action_id` | `post_call.py:64-85` | Backend finalization | Stable action identity | Yes | Unique per tenant |
| `post_call.actions[*].inputs` | `tenant_components.py:144-157` | Backend finalization | Artifact selection and representation | Optional | Transcript, recording, summary |
| `post_call.actions[*].execution.request.mapping` | finalization service | Backend | Builds HTTP payload | Required when request codec is not `none` | JSONata/template evaluation |
| `post_call.actions[*].execution.response` | same | Worker | Decodes/maps provider response | Optional | Result behavior |
| `post_call.actions[*].execution.result_schema` | same | Worker | Validates mapped result | Optional | Semantic result validation |
| `post_call.actions[*].execution.connection_id` | current contracts and resolver | Backend, Worker | Selects integration resource | Yes | Must become semantic `integration_key` |
| `handoff.destinations[*].description` | current tenant config and managed resource | Voice Agent | Tool description | Yes | Managed resource field |
| `handoff.destinations[*].phone_number` | current tenant config / managed resource | Control Plane late-bound material | Destination number | Yes | Must not remain tenant config |
| `handoff.destinations[*].enabled` | managed resource | handoff materialization | Destination usability | Yes | Live resource state |
| `handoff.destinations[*].generation` | managed resource | snapshot/runtime validation | Stale-resource detection | Internal | Not tenant semantic payload |
| provider connection `provider_kind` | managed resource | resolver, Backend | Provider construction and compatibility | Yes | Not runtime component field |
| provider connection `connection_config.endpoint` | provider schema | Voice Agent / late-bound material | Azure endpoint | Yes for Azure | Managed resource |
| provider connection `connection_config.api_version` | provider schema | Voice Agent | Provider request API version | Optional | Late-bound resource material |
| deployment `deployment_kind` | managed resource | resolver | Selects LLM/STT/TTS/realtime capability class | Yes | Managed resource |
| deployment `deployment_config.model` | provider deployment config | Voice Agent | Logical model request name | Provider-specific | Must not be duplicated in runtime config |
| deployment `deployment_config.deployment_name` | provider deployment config | Voice Agent | Azure deployment name | Provider-specific | Managed resource |
| deployment `deployment_config.model_id` | provider deployment config | Voice Agent | ElevenLabs model ID | Provider-specific | Managed resource |
| deployment capabilities | managed resource | resolver | Validates supported options | Yes | `supports_temperature`, reasoning, VAD, etc. |
| `execution_snapshot_id` | Backend call/session model | Backend, Voice Agent, Worker | Pins immutable runtime state | Yes for runtime execution | Opaque execution handle in target |
| `integration_id` / `connection_id` | execution plans | Worker | Fetches integration material | Yes internally | Semantic authoring should use `integration_key` |
| `operation_id` | Worker contracts | Worker/result processing | Idempotency and result correlation | Yes for execution plan | Internal execution field |
| `job_id`, `attempt`, `expires_at` | `IntegrationJob` | Worker | Queue execution and retry semantics | Yes in worker job | Not `ActionsDefinition` fields |
| `result_type`, `status`, `reference`, `data`, `deduplicated` | result contracts | Backend | Technical and semantic result processing | Yes in result contracts | Action definition only specifies expected result behavior |

Management-only evidence includes Admin Web field descriptors and agentctl resource names; these are not proof of target requirements ([control-plane.tsx](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/admin-web/src/core/configuration/control-plane.tsx:410), [main.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/agentctl/src/agentctl/main.py:154)).

---

# 3. Target field mapping

| Current field | Target type | Target field | Keep/Rename/Transform/Drop | Evidence | Reason |
|---|---|---|---|---|---|
| `runtime.llm.defaults.deployment_ref` | `LLMDefaults` | `deployment_ref` | Keep | resolver selects LLM deployment | Deployment identity belongs to `ModelDeployment` |
| `runtime.llm.defaults.temperature` | `LLMDefaults` | `temperature` | Keep | Voice Agent LLM options | Request option, not deployment identity |
| `runtime.llm.defaults.reasoning_effort` | `LLMDefaults` | `reasoning_effort` | Keep | Voice Agent LLM options | Capability-validated |
| `runtime.llm.defaults.max_completion_tokens` | `LLMDefaults` | `max_completion_tokens` | Keep | Voice Agent LLM construction | Runtime request option |
| `runtime.stt.defaults.deployment_ref` | `STTDefaults` | `deployment_ref` | Keep | resolver | STT deployment selection |
| `runtime.tts.defaults.*` | `TTSDefaults` | same names | Keep | Voice Agent provider construction | TTS request/pipeline defaults |
| `runtime.cascade.execution.defaults.*` | `STTDefaults` / `Policies` | `cascade` nested policy fields | Transform | Voice Agent uses these for VAD/turn/interruption/scheduling | They are pipeline behavior, not provider identity |
| `runtime.realtime.execution.defaults.*` | `RealtimeDefaults` | same semantic fields | Keep/transform | realtime resolver and provider construction | Realtime-specific behavior |
| `runtime.architecture.policy.architectures` | `Architecture` | `architectures` | Rename | resolver iterates in priority order | Tenant live selection/fallback |
| `runtime.speech.overrides.language` | `BusinessInfo` | `locale` or `language` | Transform | Provider language and tenant context | Current duplicate location is runtime-specific |
| `runtime.speech.overrides.stt.keyterms` | `RuntimeOverrides` | `stt.keyterms` | Keep | Voice Agent STT | Tenant override |
| `runtime.speech.overrides.voices.cascade` | `RuntimeOverrides` | `voices.cascade` | Keep | resolver | Tenant override |
| `runtime.speech.overrides.voices.realtime` | `RuntimeOverrides` | `voices.realtime` | Keep | resolver | Tenant override |
| `agent.tenant.display_name` | `AgentPersonality` | `display_name` | Keep | Voice Agent/finalization | Assistant identity |
| `agent.tenant.agent_profile` | `AgentPersonality` | `agent_key` | Rename | finalization reads it as agent identity | Must not own profile selection |
| `agent.tenant.greeting` | `AgentPersonality` | `greeting` | Keep | Voice Agent | Assistant behavior |
| `agent.tenant.conversation_scope` | `AgentPersonality` | `conversation_scope` | Keep | Voice Agent | Semantic identity/policy |
| `agent.tenant.locale` | `BusinessInfo` | `locale` | Move | Backend/Voice Agent | Tenant business/runtime context |
| `agent.tenant.timezone` | `BusinessInfo` | `timezone` | Move | capability date validation | Tenant business/runtime context |
| `prompt.profile.selection.profile_key` | `ProfileReference` | `profile_key` | Move | resolver selects `ProfileScope(profile_key)` | Explicit target decision |
| `prompt.tenant.content` | `TenantPrompt` | `content` | Keep | Voice Agent | Versioned semantic content |
| `knowledge.tenant.content` | `Knowledge` | `content` | Keep for current implementation | Voice Agent | Future artifact reference remains open |
| `capabilities[*].enabled` | `ActionsAvailability` | `enabled[action_key]` | Move | resolver filters enabled capabilities | Enablement is not definition |
| `capabilities[*].description` | `ActionsDefinition` | runtime `description` | Keep | Voice Agent | Action semantics |
| `capabilities[*].announcement` | `ActionsDefinition` | runtime `announcement` | Keep | Voice Agent | Action semantics |
| `capabilities[*].agent_input_schema` | `ActionsDefinition` | runtime `agent_input_schema` | Rename | Voice Agent/Backend | Exact requested target terminology |
| `capabilities[*].bindings` | `ActionsDefinition` | `bindings` | Keep | Backend normalization | Canonical mapping |
| `capabilities[*].input_constraints` | `ActionsDefinition` | `constraints` | Rename | Backend | Typed input constraints |
| `capabilities[*].business_policy` | `ActionsDefinition` | `business_policy` | Keep | Backend | Confirmation and policy |
| `capabilities[*].execution.connection_id` | `ActionsDefinition` | `execution.integration_key` | Transform | target requires semantic integration key | Hide resource identity/choreography |
| `capabilities[*].result_schema` | `ActionsDefinition` | `result.schema` | Transform | Worker/Backend | Result contract |
| `post_call.actions[*]` | `ActionsDefinition` | `post_call[]` | Merge | Backend finalization | One versioned action model |
| `post_call.inputs` | `ActionsDefinition` | `artifact_inputs` | Rename | finalization service | Post-call phase-specific field |
| `handoff.destinations` | `HandoffDestination` | resource fields | Move | target decision | Not tenant configuration |
| provider/model strings in effective runtime | `ModelDeployment` | deployment config | Drop from semantic runtime | Backend currently derives them from resources | Prevent duplicated identity |
| `type: http` | `ActionsDefinition` | none | Drop from semantic definition | Integration kind already identifies HTTP | Keep internal plan discriminator only |
| `plan_type` | internal execution plan | `plan_type` | Keep internally | Worker dispatch | Not authoring schema |
| `connection_id` | internal materialization DTO | resource ID | Keep internally | Worker/CP materialization | Not exposed to runtime authoring consumers |
| `enabled` on action definition | none | none | Drop | target invariant | Availability owns it |

---

# 4. Proposed exact target schemas

The following are JSON-schema-like payloads. `DeploymentRef` is a semantic reference to a `ModelDeployment`; it is not a provider/model string.

## Common types

```yaml
DeploymentRef:
  type: string
  format: uuid
  description: ModelDeployment reference

ArchitectureKind:
  type: string
  enum: [cascade, realtime]

Locale:
  type: string
  pattern: "^[a-z]{2,3}(?:-[A-Z]{2})?$"

Timezone:
  type: string
  description: IANA timezone

ReasoningEffort:
  type: string
  enum: [none, low, medium, high, xhigh, max]
```

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

This is confidently defined. STT provider/model identity remains in `ModelDeployment`.

## LLMDefaults

```yaml
LLMDefaults:
  type: object
  additionalProperties: false
  required: [deployment_ref, max_completion_tokens]
  properties:
    deployment_ref:
      $ref: DeploymentRef
    temperature:
      type: [number, "null"]
      minimum: 0
      maximum: 2
      default: null
      description: Null means omit temperature and use provider/model behavior
    reasoning_effort:
      oneOf:
        - $ref: ReasoningEffort
        - type: "null"
      default: null
    max_completion_tokens:
      type: integer
      exclusiveMinimum: 0
```

Provider capability validation must reject incompatible `temperature` or `reasoning_effort` ([runtime_components.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/runtime_components.py:181)).

## TTSDefaults

```yaml
TTSDefaults:
  type: object
  additionalProperties: false
  required: [deployment_ref, default_voice_id, min_sentence_chars]
  properties:
    deployment_ref:
      $ref: DeploymentRef
    default_voice_id:
      type: string
      minLength: 1
      maxLength: 255
    min_sentence_chars:
      type: integer
      minimum: 3
      maximum: 200
```

`min_sentence_chars` is directly passed into sentence tokenization ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:112)).

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
      default: marin
    turn_completion:
      oneOf:
        - type: object
          required: [strategy]
          properties:
            strategy: { const: server_vad }
            activation_threshold: { type: number, minimum: 0, maximum: 1, default: 0.5 }
            silence_duration_ms: { type: integer, exclusiveMinimum: 0, default: 200 }
        - type: object
          required: [strategy]
          properties:
            strategy: { const: semantic_vad }
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

Current schemas validate all these fields, but the current realtime Voice Agent constructor only consumes model, voice, endpoint, API version, transcription, and secrets ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:166)). The behavior fields therefore require an explicit migration decision before being declared operationally authoritative.

## Policies

No current semantic consumer was found.

The only safe exact schema supported by repository evidence is:

```yaml
Policies:
  type: object
  additionalProperties: false
  properties: {}
```

This should remain empty until a real policy consumer exists. Do not carry `ArchitecturePolicy` here; it is tenant-specific and belongs to `Architecture`.

## AgentPersonality

```yaml
AgentPersonality:
  type: object
  additionalProperties: false
  required:
    - agent_key
    - display_name
    - greeting
    - conversation_scope
  properties:
    agent_key:
      type: string
      minLength: 1
      maxLength: 100
      pattern: "^[a-z][a-z0-9_]*$"
      description: Stable runtime/finalization identity; not profile selection
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

The `agent_key` name is an inference from current `agent_profile` usage. The current field is consumed as an identity value by finalization, but its name conflicts with `ProfileReference`.

## BusinessInfo

```yaml
BusinessInfo:
  type: object
  additionalProperties: false
  required: [name, type, locale, timezone]
  properties:
    name:
      type: string
      minLength: 1
      maxLength: 255
    type:
      type: string
      minLength: 1
      maxLength: 64
    locale:
      $ref: Locale
    timezone:
      $ref: Timezone
    contact:
      type: object
      additionalProperties: false
      properties:
        address: { type: [string, "null"], maxLength: 1000 }
        phones:
          type: array
          maxItems: 20
          items: { type: string }
        emails:
          type: array
          maxItems: 20
          items: { type: string, format: email }
        website:
          type: [string, "null"]
          maxLength: 2048
```

`locale` and `timezone` are required because providers and date constraints consume them ([execution_context.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/execution_context.py:40), [domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:415)).

## Architecture

```yaml
Architecture:
  type: object
  additionalProperties: false
  required: [architectures]
  properties:
    architectures:
      type: array
      minItems: 1
      maxItems: 2
      uniqueItems: true
      items:
        $ref: ArchitectureKind
      description: Ordered preference/fallback list
```

A scalar `architecture` would lose current fallback semantics. The resolver iterates the list in order and selects the first compatible architecture ([runtime_resolver.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/application/runtime_resolver.py:121)).

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

This directly matches the current profile selection resolver ([execution_resolver.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/application/execution_resolver.py:82)).

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
            maxLength: 20
    voices:
      type: object
      additionalProperties: false
      properties:
        cascade:
          type: [string, "null"]
          maxLength: 255
        realtime:
          type: [string, "null"]
          maxLength: 255
```

Current evidence supports only language/keyterms/voice overrides. Deployment overrides, tenant LLM overrides, and tenant TTS model overrides have definitions in shared contracts but no current Control Plane runtime consumer.

Recommended semantics:

- field absent: inherit system/platform effective value;
- field present with `null`: clear the override and inherit;
- nested object present: recursively partial-merge;
- deployment override: not supported unless a real consumer is added;
- unknown fields: reject;
- empty `keyterms`: explicit empty list, disabling inherited keyterms;
- voice `null`: inherit the corresponding default voice.

The current implementation does not implement this merge model: `SpeechOverrides` is required as a complete tenant component and `language` is mandatory ([runtime_resolver.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/application/runtime_resolver.py:124), [runtime_components.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/runtime_components.py:163)). This is an implementation ambiguity, not a target-architecture fact.

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
      description: action_key -> enabled
```

Validation must require every referenced action key to exist in `ActionsDefinition`, as required by the target invariant ([INVARIANTS.md](/home/nikitachernysh/Storage/Projects/agentic-backend/docs/control-plane/INVARIANTS.md:240)).

---

# 5. ActionsDefinition audit

## RuntimeActionDefinition

```yaml
RuntimeActionDefinition:
  type: object
  additionalProperties: false
  required:
    - phase
    - action_key
    - version
    - description
    - announcement
    - agent_input_schema
    - execution
  properties:
    phase:
      const: runtime
    action_key:
      type: string
      pattern: "^[a-z][a-z0-9_.-]{0,127}$"
    version:
      type: integer
      minimum: 1
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
          additionalProperties: { type: string }
    agent_input_schema:
      type: object
      description: Closed Draft 2020-12 JSON Schema object
    bindings:
      type: object
      additionalProperties:
        type: string
    constraints:
      type: array
      items:
        $ref: CapabilityInputConstraint
    business_policy:
      type: object
      properties:
        requires_final_confirmation: { type: boolean, default: false }
        requires_caller_phone: { type: boolean, default: false }
        requires_availability_proof: { type: boolean, default: false }
        availability_proof_ttl_seconds:
          type: [integer, "null"]
          minimum: 1
          maximum: 86400
    execution:
      type: object
      additionalProperties: false
      required:
        - integration_key
        - method
        - timeout_seconds
      properties:
        integration_key:
          type: string
          description: Semantic IntegrationConnection key
        method:
          type: string
          enum: [GET, POST, PUT, PATCH, DELETE]
        path:
          type: [string, "null"]
        query:
          type: [object, "null"]
        headers:
          type: object
        request:
          type: object
        response:
          type: object
        timeout_seconds:
          type: number
          exclusiveMinimum: 0
          maximum: 60
        success_statuses:
          type: [array, "null"]
          maxItems: 20
    result:
      type: object
      properties:
        schema:
          type: [object, "null"]
        processing:
          type: [object, "null"]
```

Current runtime result processing requires a result schema when configured, validates it as Draft 2020-12, and applies JSONata response mapping ([domain.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/capabilities/domain.py:335), [worker.py](/home/nikitachernsh/Storage/Projects/agentic-backend/apps/job-worker/src/job_worker/worker.py:565)).

## PostCallActionDefinition

```yaml
PostCallActionDefinition:
  type: object
  additionalProperties: false
  required:
    - phase
    - action_key
    - artifact_inputs
    - execution
  properties:
    phase:
      const: post_call
    action_key:
      type: string
      pattern: "^[a-z][a-z0-9_.-]{0,127}$"
    artifact_inputs:
      type: object
      additionalProperties: false
      additionalProperties:
        type: object
        required: [artifact, representation]
        properties:
          artifact:
            type: string
            enum: [transcript, call_recording, call_summary]
          representation:
            type: string
            enum: [raw_json, plain_text, original, base64_text]
    execution:
      type: object
      additionalProperties: false
      required:
        - integration_key
        - method
        - timeout_seconds
      properties:
        integration_key:
          type: string
        method:
          type: string
          enum: [GET, POST, PUT, PATCH, DELETE]
        path:
          type: [string, "null"]
        query:
          type: [object, "null"]
        headers:
          type: object
        request:
          type: object
        response:
          type: object
        timeout_seconds:
          type: number
          exclusiveMinimum: 0
          maximum: 60
        success_statuses:
          type: [array, "null"]
          maxItems: 20
    result:
      type: object
      properties:
        schema:
          type: [object, "null"]
        processing:
          type: [object, "null"]
```

The phase discriminator is sufficient for the semantic union, provided `action_key` is unique across the combined runtime/post-call action namespace or uniqueness is explicitly scoped by phase.

Current post-call execution consumes artifacts, builds a mapping context, evaluates request/path/query mappings, and carries response/result schema into the Worker plan ([service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/finalization/service.py:288), [service.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/finalization/service.py:309)).

## `$expr` and mapping audit

Actually required:

- JSONata expressions in `path`;
- JSONata expressions in query values;
- nested mapping templates in request bodies;
- nested mapping templates in response mappings;
- post-call artifact/input mapping;
- response mapping against `{response.status_code, response.content_type, response.body}`.

Validation supports local expression nodes with only `{"$expr": ...}` and rejects malformed expression nodes ([http_operation.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/http_operation.py:16), [capabilities.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/capabilities.py:220)).

Not required by current evidence:

- arbitrary expressions in action keys;
- expressions that access secrets;
- remote `$ref`;
- custom JSON Schema extensions;
- a typed JSONata AST.

The current validator explicitly restricts `$ref` to local references and rejects `x-*` extensions ([capabilities.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/capabilities.py:203)).

## `execution.type=http`

Recommendation:

- Drop `type: http` from semantic `ActionsDefinition`.
- Keep an internal execution-plan discriminator such as `plan_type: http.request.v1` because Worker dispatches among multiple execution plans ([worker.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/job-worker/src/job_worker/worker.py:1338)).
- `integration_key` should replace `connection_id` in semantic authoring.
- Materialization may resolve `integration_key` to an internal resource ID.

The current `HttpOperation.type` is redundant with the integration kind for the semantic authoring model, but the Worker still needs a technical plan discriminator.

---

# 6. Runtime configuration audit

## A. Deployment/provider selection

Belongs to `ModelDeployment`:

- provider kind;
- provider connection;
- provider endpoint;
- credential reference;
- provider API version;
- deployment kind;
- provider-specific deployment name/model/model ID;
- capability metadata.

`ModelDeployment` already owns deployment kind and deployment config ([managed_resources.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/managed_resources.py:124)). Provider-specific schemas confirm that model/deployment identity is provider-resource data ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/domain/providers.py:22)).

Belongs to runtime defaults:

- `deployment_ref`;
- separate realtime transcription `deployment_ref`.

## B. Provider/model request options

Belongs to:

- `LLMDefaults.temperature`;
- `LLMDefaults.reasoning_effort`;
- `LLMDefaults.max_completion_tokens`;
- `TTSDefaults.default_voice_id`;
- `RealtimeDefaults.default_voice`;
- STT keyterms as tenant runtime overrides.

Provider/model strings must not be duplicated in these components.

## C. Voice pipeline behavior

Belongs to `Policies` only if system-wide; current tenant/runtime-specific fields belong to `Architecture`, `RuntimeOverrides`, or the architecture-specific runtime policy projection:

- local VAD speech activity;
- provider VAD tuning;
- STT commit strategy;
- endpointing;
- interruption;
- preemptive generation/TTS;
- realtime turn completion.

Cascade runtime currently uses all of these in `AgentSession` construction ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:66), [providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:130)).

Important current behavior:

- cascade `turn_detection` is hard-coded to `"stt"` ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:133));
- local VAD controls whether provider VAD is omitted or configured;
- local VAD is always constructed for cascade;
- realtime currently constructs `AgentSession(llm=realtime_model, vad=None, turn_detection=None)` ([providers.py](/home/nikitachernsh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:193)).

## D. Tenant overrides

Current evidence supports only:

- STT keyterms;
- cascade voice;
- realtime voice;
- locale/language, although this should be owned by `BusinessInfo`.

Current shared contracts define tenant LLM/TTS overrides, but no current runtime resolver consumes them. They should not be included in target `RuntimeOverrides` without an explicit semantic consumer.

---

# 7. Override semantics

Recommended target semantics:

| State | Meaning |
|---|---|
| Field absent | Inherit the effective system/platform value |
| Field present with `null` | Clear the tenant override and inherit |
| Nested object absent | Inherit the whole nested object |
| Nested object present | Recursively partial-merge |
| Empty list | Explicitly replace inherited list with empty list |
| Deployment override absent | Use system default deployment |
| Deployment override present | Only valid if explicitly supported and reference-resolved |
| Unknown field | Reject |

Current ambiguity:

- `SpeechOverrides.language` is required rather than inherited.
- `stt.keyterms` defaults to an empty list, which is indistinguishable from “clear inherited keyterms” unless explicitly defined.
- `RuntimeResolver` requires the tenant override component and does not show a general deep-merge operation ([runtime_resolver.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/control-plane-service/src/control_plane/application/runtime_resolver.py:124)).
- `TenantLLMRuntimeOverride` and `TenantTTSRuntimeOverride` exist in shared contracts but are not part of the current Control Plane resolution path ([voice_runtime.py](/home/nikitachernysh/Storage/Projects/agentic-backend/packages/contracts/src/contracts/voice_runtime.py:149)).

Smallest target decision: keep deployment selection platform-owned, make `RuntimeOverrides` an explicit partial patch for voice/keyterm behavior only.

---

# 8. Hidden required fields

These are required by current consumers but are not represented in the supplied legacy runtime examples or are easy to miss:

1. `BusinessInfo.locale`
2. `BusinessInfo.timezone`
3. `AgentPersonality.display_name`
4. `AgentPersonality.greeting`
5. `AgentPersonality.conversation_scope`
6. Stable agent identity key currently named `agent_profile`
7. `ProfileReference.profile_key`
8. `ActionsDefinition.action_key`
9. action version/semantic version
10. derived runtime `tool_name`
11. action `agent_input_schema`
12. canonical bindings
13. input constraints
14. confirmation/business policy
15. action result schema and response processing
16. post-call artifact representation
17. `integration_key`
18. deployment-specific `deployment_name`, `model`, or `model_id`
19. provider endpoint/API version
20. realtime transcription deployment reference
21. handoff destination key, description, resource reference, and generation
22. immutable execution handle
23. Worker job ID, operation ID, expiry, attempt, and execution-plan discriminator

Evidence includes Backend context construction ([execution_context.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/backend/src/backend_core/runtime/execution_context.py:42)), Voice Agent provider construction ([providers.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/voice-agent/src/voice_agent/providers.py:96)), and Worker job validation/dispatch ([worker.py](/home/nikitachernysh/Storage/Projects/agentic-backend/apps/job-worker/src/job_worker/worker.py:1298)).

---

# 9. Fields safe to delete

These should not survive into target semantic configuration:

- arbitrary runtime `provider` strings;
- arbitrary runtime `model` strings;
- tenant `handoff.destinations[*].phone_number`;
- tenant `handoff.destinations[*].enabled`;
- tenant `handoff.destinations[*].generation`;
- action `enabled` inside `ActionsDefinition`;
- semantic `execution.type: http`;
- semantic `connection_id`;
- provider credential graph fields in runtime contexts;
- persistence revision IDs in consumer-facing configuration;
- Worker `job_id`, `attempt`, `expires_at`, and `operation_id` from `ActionsDefinition`;
- unused tenant LLM/TTS override models unless a runtime consumer is added;
- unused system `Policies` fields copied from legacy YAML;
- management-only Admin Web field descriptors;
- agentctl workspace resource names and file layout;
- compatibility aliases for old component names.

Internal execution plans may retain technical IDs and `plan_type`; those are not semantic configuration fields.

---

# 10. Open decisions

## 1. `Policies`

No current implementation or consumer defines its meaning.

Affected schema: `Policies`.

Alternatives:

1. Empty reserved object until a policy consumer exists.
2. Move current cascade pipeline policy into `Policies`.
3. Keep pipeline policy in architecture-specific runtime materialization and use `Policies` only for genuinely system-wide controls.

Smallest evidence-based choice: option 1.

## 2. Realtime behavior fields

`turn_completion` and realtime interruption are validated and materialized, but `create_realtime_session` currently ignores them.

Affected schema: `RealtimeDefaults`.

Alternatives:

1. Declare them target-required and migrate Voice Agent behavior later.
2. Remove them from the target schema.
3. Keep them but explicitly mark them non-effective until the Voice Agent consumer is migrated.

Smallest safe choice: option 3.

## 3. Agent profile identity

`agent_profile` is consumed as an agent identity/finalization value, while `profile_key` selects the platform profile prompt.

Affected schemas: `AgentPersonality`, `ProfileReference`.

Alternatives:

1. Rename `agent_profile` to `agent_key`.
2. Drop it and derive identity from tenant/profile.
3. Treat it as the same field as `ProfileReference.profile_key`.

Repository behavior rules out option 3. Option 1 preserves the current consumer with clear ownership.

## 4. Deployment overrides

No current resolver consumes tenant deployment overrides.

Affected schema: `RuntimeOverrides`.

Alternatives:

1. No deployment overrides; deployments remain system/platform defaults.
2. Add explicit `llm_deployment_ref`, `stt_deployment_ref`, `tts_deployment_ref`, and realtime refs.
3. Add one architecture-specific deployment selection object.

Evidence supports option 1 today.

## 5. Knowledge representation

Current runtime consumes inline knowledge content; the contracts also contain knowledge-base and artifact identifiers.

Affected schema: `Knowledge`.

Alternatives:

1. Inline `content` only.
2. `content` plus `knowledge_base_revision_id` / `artifact_id`.
3. Artifact reference only.

Current runtime proves option 1 is required now; future artifact semantics remain open.

## 6. Action execution union

Current semantic authoring supports HTTP and the Worker supports HTTP, managed webhook, and Google Sheets technical plans.

Affected schema: `ActionsDefinition`.

Alternatives:

1. One semantic integration execution shape with `integration_key`; materialization chooses the technical plan.
2. Separate semantic execution variants for HTTP, managed webhook, and Google Sheets.
3. Preserve current `type`/`plan_type` fields in authoring.

Target principles favor option 1. Technical `plan_type` remains internal to Worker execution.

Read-only audit complete. No code, migration, or schema files were modified.
