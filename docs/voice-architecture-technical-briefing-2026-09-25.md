# Voice Architecture Technical Briefing

**Review date:** 2026-09-25. **Checkout inspected:** 2026-09-24. **Use:** searchable reference during the external architecture and performance call. Times are milliseconds unless stated. `median / p90` always describes successful measured runs, with N given separately.

**Evidence labels:** **MEASURED** = result artifact; **OBSERVED** = current repository implementation or project testing stated in this briefing; **INFERRED** = interpretation of those facts; **UNKNOWN / runtime-provided / not present in checkout** = cannot verify from this checkout; **NOT MEASURED** = outside the benchmark boundary. Benchmark artifacts were generated from a dirty checkout; their manifests record commit IDs and configuration, not a deployed tenant snapshot. The working tree already contains benchmark edits and result documents; this briefing does not change them.

## Table of contents

| Topic | Section | Topic | Section |
|---|---:|---|---:|
| Executive snapshot; system; comparison | 00–02 | CASCADE; REALTIME; HALF-CASCADE | 03–05 |
| Code map; runtime; prompts; tools | 06–09 | LIVEKIT; TELNYX / SIP | 10–11 |
| ElevenLabs STT; Azure/direct LLM; Realtime; TTS | 12–15 | Regions; network | 16–17 |
| Methodology; LLM; STT; TTS; pipelines; budget | 18–23 | Slovak/Czech; names; phones; turns; transcripts | 24–28 |
| Limitations; engineering questions; Viktor | 29–31 | Symbol index; search index | 32–33 |

## 00. Executive Snapshot

- **OBSERVED:** Three runtime architectures are selected by the published Control Plane `Architecture` state: `cascade`, `realtime`, `half-cascade`. Voice Agent dispatches on `VoiceExecutionContext.architecture` in `run_job`.
- **OBSERVED:** Cascade uses ElevenLabs Scribe STT → Azure or direct OpenAI LLM → ElevenLabs TTS. Realtime uses Azure OpenAI `RealtimeModel` for audio input and audio output. Half-cascade uses Azure OpenAI `RealtimeModel` for audio input and text output → ElevenLabs TTS. Current factories additionally attach standalone STT to both Realtime variants as an observer for finalized lexical transcripts.
- **MEASURED:** Synthetic first output audio: Azure cascade **3644 / 4534** (N=30); direct OpenAI Fast cascade **3181 / 4242** (N=30); Azure Realtime **2857 / 3973** (N=30); half-cascade **3096 / 4306** (N=29 successful, one timeout). Inputs are paced for cascade and burst-uploaded for Realtime paths; the numbers are directional.
- **INFERRED from measured stages:** Model inference/generation dominates the measured synthetic first-audio interval. In Azure cascade, LLM start → first text is **2925 / 3915**, versus post-speech STT **210 / 270** and TTS start → first audio **225 / 298**. Half-cascade Realtime first text is **2928 / 4085**, versus downstream TTS **167 / 215**. These are distinct median/p90 distributions; do not add percentile values as an exact budget.
- **OBSERVED project concern, not measured here:** Full Realtime Slovak pronunciation and transcript fidelity, especially names and surnames, motivated an external ElevenLabs TTS path and a standalone transcript sidecar. The current latency suite contains no human quality assessment and gives no Czech runtime proof.
- **NOT MEASURED:** Production end-to-end (E2E), production end-of-utterance (EOU), LiveKit playout, Telnyx/SIP/PSTN media transport, caller-audible timing, realistic tool execution, and published tenant prompt/tool context.

## 01. System Overview

```text
PSTN caller → Telnyx → LiveKit SIP → LiveKit room → Voice Agent AgentSession
    ├─ CASCADE: ElevenLabs STT → Azure/direct OpenAI LLM → ElevenLabs TTS
    ├─ REALTIME: Azure OpenAI Realtime audio in → audio out
    └─ HALF-CASCADE: Azure OpenAI Realtime audio in → text → ElevenLabs TTS
                              ↕ tools / call state
                         Backend Core ↔ Control Plane
                              ↕             ↕
                    PostgreSQL + Redis   immutable execution snapshot
                              ↕
                         Job Worker → configured integration
Voice Agent output → LiveKit room → LiveKit SIP → Telnyx → PSTN caller
```

Backend owns call and conversation state, capability invocation, outbox, telephony reconciliation and LiveKit dispatch. Control Plane resolves published semantic state and materializes one immutable execution snapshot, then projects Backend, Voice Agent, and Worker contexts; secrets are late-bound. PostgreSQL persists application state/snapshots; Redis supports LiveKit/SIP and the Worker stream. Job Worker executes configured HTTP integration jobs and reports results to Backend. Voice Agent sends observations and conversation items. Compose declares OpenTelemetry Collector, Prometheus, Tempo, and Grafana; `LatencyInstrumentedAgent` and `VoiceMetrics` emit production metrics. The synthetic benchmark runners run outside this call path.

## 02. Architecture Comparison

| Architecture | Causal speech-to-response path | Parallel/observer path | Output boundary in benchmark | Key configuration |
|---|---|---|---|---|
| CASCADE | ElevenLabs STT final → LLM text → sentence tokenization → ElevenLabs TTS | Local VAD can govern STT commit/onset | First TTS audio bytes | `STTDefaults`, `LLMDefaults`, `TTSDefaults`, `Policies.cascade` |
| REALTIME | Realtime server receives audio, detects turn, generates native audio | Standalone STT final → recent transcript buffer | First Realtime audio event | `RealtimeDefaults`, standalone `STTDefaults`, Realtime transcription deployment |
| HALF-CASCADE | Realtime server receives audio, generates text → ElevenLabs TTS | Standalone STT final → recent transcript buffer | First TTS audio bytes | `RealtimeDefaults`, `TTSDefaults`, standalone `STTDefaults` |

All three share LiveKit `AgentSession`, a pinned `VoiceExecutionContext`, Backend capability tools, transcript persistence, call lifecycle, and the same published prompt structure. No strict ranking follows from the current benchmark because input feeding differs.

## 03. CASCADE

**Purpose and actual runtime path.** Independent speech recognition, text model, and speech synthesis. `RuntimeResolver._cascade` resolves system defaults, deployment resources, tenant locale/voice/keyterms and cascade policy. `ExecutionMaterializationService._voice_runtime` freezes the consumer projection. `run_job` loads it and calls `create_agent_session`; that factory builds ElevenLabs `STT`, optionally wraps it in `LocalVadCommitSTT`, constructs local `inference.VAD`, selects `openai.LLM` or `openai.LLM.with_azure`, and builds ElevenLabs `TTS` with `SentenceTokenizer(min_sentence_len=runtime tokenizer threshold)`. `AgentSession(turn_detection="stt")` commits a caller turn, streams text into TTS, then outputs into the LiveKit room. `LatencyInstrumentedAgent` observes STT/LLM/TTS nodes.

```text
Telnyx SIP → LiveKit → local VAD / ElevenLabs Scribe STT (causal final)
  → Azure or direct OpenAI LLM → LiveKit sentence tokenizer
  → ElevenLabs TTS → LiveKit output
```

**Providers/settings.** Code accepts `azure_openai` or `openai` for LLM and requires ElevenLabs for STT/TTS. Exact production deployment/model/voice/endpoint/reasoning/tokenizer values are runtime-pinned and **UNKNOWN / runtime-provided / not present in checkout**. Current measured configuration was `scribe_v2_realtime`, `gpt-5.6-terra`, `eleven_v3_conversational`, sentence threshold 20, output cap 512. `llm_behavior_options` sends reasoning effort for GPT-5/o-series models when configured, otherwise temperature for other models; `prompt_cache_key` hashes system and profile text. `response_scheduling` controls preemptive generation/TTS; interruption and fixed endpointing come from policy.

**Latency/strength/weakness.** STT final is a causal gate, followed by model first speakable text and TTS first bytes; sentence threshold can delay TTS until a chunk is speakable. Independent STT/TTS makes provider choice and transcript/voice quality separately configurable. The additional causal stages and tokenizer wait are real; whether they hurt caller-audible latency in production is **NOT MEASURED**. **MEASURED:** Azure 3644 / 4534, N=30; direct OpenAI Fast 3181 / 4242, N=30. Azure LLM first text 2925 / 3915; direct Fast 2204 / 3121. TTS started before model completion in only 4/30 Azure and 3/30 direct runs; for this fixture it usually waited near completion. Source: `providers.py:create_agent_session`, `_create_stt`, `_create_tts`; `main.py:run_job`; `stt_endpointing.py:LocalVadCommitSTT`.

## 04. REALTIME

**Purpose and actual runtime path.** Realtime audio understanding and native voice output in one model session. `RuntimeResolver._realtime` resolves a Realtime model, input-transcription deployment, and standalone STT. `run_job` calls `create_realtime_session`; the factory attaches `realtime.RealtimeModel` as `llm`, a separate STT as `stt`, `vad=None`, `turn_detection="realtime_llm"`, and interruption from runtime. `_realtime_options` maps Azure deployment, endpoint/API version, voice, and server/semantic VAD turn completion. `_realtime_transcription` configures Realtime input transcript model/language. Realtime output audio goes through `AgentSession` to LiveKit. Standalone STT final events are consumed by `LatencyInstrumentedAgent.stt_node` for `RecentTranscriptBuffer` and are not yielded to the session's turn path (`StandaloneSTTRole.SIDECAR`).

```text
Telnyx SIP → LiveKit → Azure Realtime audio input → server turn detection
  → Realtime generation/native audio → LiveKit output
                ╲
                 ╲→ standalone STT final → recent transcript buffer [observer]
```

**Providers/settings.** Current `providers.py:_realtime_options` constructs Azure Realtime URL/deployment fields; model/voice/deployment are pinned, **UNKNOWN** for the actual published call. Synthetic run used Azure `gpt-realtime-2.1` in `francecentral`. `RuntimeResolver._realtime_transcription` currently requires a capable STT deployment and, for Azure Realtime, the same provider connection as the model. Separately, the sidecar STT has its own resolved deployment/credential. Current source passes `input_audio_transcription=_realtime_transcription(runtime)`; any claim that it is disabled is stale.

**Latency/strength/weakness.** Realtime turn completion and model output are causal; standalone STT is observer-only. The native audio path avoids an external TTS stage. **MEASURED synthetic:** input end → first audio 2857 / 3973, N=30; first text 2599 / 3719; `response.created` 148 / 340. Input was burst-uploaded and manually committed, so this is neither natural production streaming nor production EOU. **OBSERVED project testing concern:** Slovak pronunciation/transcript quality requires evaluation; the suite does not score quality. Source: `providers.py:create_realtime_session`, `_realtime_options`, `_realtime_turn_detection`; `observability.py:LatencyInstrumentedAgent.stt_node`.

## 05. HALF-CASCADE

**Purpose and actual runtime path.** Keep Realtime audio understanding/turn management while replacing native speech output with ElevenLabs voice. `RuntimeResolver._half_cascade` resolves Realtime model/input transcription, independent standalone STT, and TTS. `run_job` calls `create_half_cascade_session`: `RealtimeModel(modalities=["text"])`, `AgentSession(tts=ElevenLabs, vad=None, turn_detection="realtime_llm")`; `_create_tts` sets `auto_mode=False` for `eleven_v3*`. The installed LiveKit TTS path uses its default word-token boundary here; the synthetic runner models that boundary. The sidecar STT only fills `RecentTranscriptBuffer`.

```text
Telnyx SIP → LiveKit → Azure Realtime audio input → text output
  → LiveKit word-token boundary → ElevenLabs TTS → LiveKit output
                ╲→ standalone STT final → recent transcript buffer [observer]
```

**Latency/strength/weakness.** Realtime first text/word and external TTS gate audio. Independent TTS voice is configurable and was introduced for voice quality control; its actual quality benefit has no benchmark score here. **MEASURED synthetic:** input end → first TTS audio 3096 / 4306, N=29 successful of 30; first text 2928 / 4085; first word/speakable 2952 / 4114; TTS start → first audio 167 / 215. Realtime text generation dominates this measured interval. One run failed with provider `first_output_timeout`. The sidecar is omitted from this synthetic pipeline because its output is non-causal. Source: `providers.py:create_half_cascade_session`, `_create_tts`; `stt_role.py:role_for_architecture`.

## 06. Code Map

| Purpose | File | Class/function | Notes |
|---|---|---|---|
| LiveKit agent server/job entry | `apps/voice-agent/src/voice_agent/main.py` | `build_server`, `entrypoint`, `run_job`, `resolve_call_session_id` | SIP claim or metadata ID, runtime context, secrets, start/output/lifecycle |
| Architecture selection | same; `apps/control-plane-service/src/control_plane/application/runtime_resolver.py` | `run_job`; `RuntimeResolver.resolve_state`, `_resolve_candidate` | Published `Architecture` picks one of three |
| Cascade / Realtime / half-cascade factories | `apps/voice-agent/src/voice_agent/providers.py` | `create_agent_session`, `create_realtime_session`, `create_half_cascade_session` | Causal plugin composition |
| STT / Realtime / LLM / TTS adapters | same | `_create_stt`, `_realtime_options`, `_realtime_transcription`, `_realtime_turn_detection`, `llm_behavior_options`, `_create_tts` | Provider-specific values |
| Local VAD STT commit | `apps/voice-agent/src/voice_agent/stt_endpointing.py` | `LocalVadCommitController`, `LocalVadCommitSTT` | Cascade policy option |
| Prompts and tools | `apps/voice-agent/src/voice_agent/main.py` | `assemble_instructions`, `build_agent_tools`, `capability_tool`, `handoff_tool` | Agent-scoped instructions and function schemas |
| Transcript observer/instrumentation | `apps/voice-agent/src/voice_agent/observability.py`; `recent_transcript.py`; `stt_role.py` | `LatencyInstrumentedAgent`, `RecentTranscriptBuffer`, `recent_transcript_tool`, `role_for_architecture` | Sidecar is hidden from causal turn path |
| Transcript persistence | `apps/voice-agent/src/voice_agent/event_delivery.py` | `ConversationPersistence`, `message_from_event` | Backend append queue; only chat user/assistant items |
| Human handoff / call termination | `apps/voice-agent/src/voice_agent/handoff.py`; `main.py` | `HandoffController`, `SessionTerminalizer`, `close_failure_reason` | Answer must be active SIP status; terminalization drains persistence |
| Backend call and capability | `apps/backend/src/backend_core/modules/calls/service.py`; `runtime/capabilities/service.py` | `CallSessionService`, `CapabilityInvocationService` | Pinned context, SIP call, invocation/outbox |
| Control Plane runtime/materialization | `apps/control-plane-service/src/control_plane/application/runtime_resolver.py`; `execution_materialization.py` | `RuntimeResolver`, `ExecutionMaterializationService` | Resource validation, snapshot/projections, late secrets |
| Worker execution | `apps/job-worker/src/job_worker/worker.py` | `CapabilityWorker`, `_bind_input`, `HttpExecutionHandler` | Redis stream, validation/normalization, HTTP provider |
| Shared contracts / metrics | `packages/contracts/src/contracts/`; `packages/observability/src/agentic_observability/` | `VoiceExecutionContext`, `BackendExecutionContext`, `WorkerExecutionContext`; `CoreMetrics` | Consumer boundaries and telemetry |

## 07. Runtime Configuration and Control Plane

1. Published tenant `Architecture` and `RuntimeOverrides` plus system `STTDefaults`, `LLMDefaults`, `TTSDefaults`, `RealtimeDefaults`, `Policies` enter `RuntimeResolver.resolve_state`. `_resolve_candidate` selects `cascade`, `realtime`, or `half-cascade`; each path validates deployment kind, provider connection, credential, and relevant capability. This is current code, not an older `VoiceRuntimeRevision` environment-only model.
2. `ExecutionMaterializationService.create_execution` resolves a coherent effective state and persists an immutable `ExecutionSnapshot`. `_target_state` packages Backend/Voice/Worker material; `_voice_runtime` copies provider semantics and policy into the Voice projection. `voice_context` exposes `VoiceExecutionContext`; `worker_context` scopes a single action. The snapshot contains credential references, not secret values.
3. `run_job` obtains a call's pinned context from Backend (`BackendClient.runtime_context` → `CallSessionService.get_runtime_context` → `ExecutionContextReader`). It fetches architecture-specific secret slots through Backend (`BackendClient.runtime_secret` → Control Plane `ExecutionMaterializationService.runtime_secret`) and constructs a new `AgentSession`. Slots: cascade `stt,llm,tts`; Realtime `model,input_transcription,stt`; half-cascade adds `tts`.
4. The model deployment's `deployment_config` and provider connection's `connection_config` supply model ID/deployment, endpoint/API version, and optional service tier. Tenant/system live state supplies voice, locale, VAD/EOU, interruption, scheduling, tokenizer, and model parameters. `VoiceAgentSettings` supplies LiveKit/Backend URLs and local timeouts/retries; it does not hard-code the published model. **UNKNOWN / runtime-provided / not present in checkout:** effective tenant execution ID, actual production provider resource IDs, voice IDs, keyterms, prompt text, exact published tokenizer threshold, all active credentials, reasoning setting, output cap, service tier, and exact production region.
5. Control Plane target documentation (`docs/control-plane/README.md`, `ARCHITECTURE.md`, `SCHEMAS.md`, `CONTRACTS.md`, `INVARIANTS.md`) describes intended ownership; this section states the verified current runtime path.

## 08. Prompt Assembly and Instructions

`ExecutionMaterializationService._target_state` pins `system`, `profile`, `interaction`, `tenant`, and `knowledge` content into the Voice projection. `main.py:assemble_instructions` concatenates, in order: `[System instructions]`, `[Profile instructions]`, `[Interaction instructions]`, `[Tenant instructions]`, `[Agent context]` (display name, role, optional grammatical gender, conversation scope), `[Business context]` (name/type/contact fields and links), `[Localization]` (locale/timezone), `[Tenant knowledge]`, `[Dynamic context]` (local date/time and SIP caller number when present), and for Realtime/half-cascade `[Recent transcript]`. `session.start(agent=LatencyInstrumentedAgent(instructions=...))` supplies the effective prompt; tool schemas are attached separately. Cascade's LLM additionally receives a `prompt_cache_key` derived from system/profile text.

`docs/PROMPT_ARCHITECTURE.md` documents target ownership: system invariant behavior, profile scope, interaction speech behavior, tenant policy, identity/business facts, knowledge facts, dynamic facts, and separate tool definitions. The effective published text is **UNKNOWN / runtime-provided / not present in checkout**. Do not treat `benchmarks/llm/prompts/production.txt` or `benchmarks/realtime/prompts/production.txt` as the actual pinned tenant prompt; artifacts mention local prompt files/hashes but not the live execution projection. `provider_languages` accepts only Slovak `sk*` locale at the current adapter boundary; no Czech-specific instruction or deployed Czech locale was found. The recent-transcript instruction is a current code addition, even though the target prompt document discourages unnecessary tool-name coupling.

## 09. Tool / Action Execution

`build_agent_tools` installs calculator, LiveKit `EndCallTool` (`call.end`, room deletion), conditional `get_recent_transcript`, conditional semantic `transfer_to_human`, and each enabled runtime action from pinned `context.actions`. `capability_tool` converts dotted action keys to function names (for example `reservation.submit_request` → `reservation_submit_request`) and exposes the pinned `definition.agent_input_schema`/description as LiveKit raw schema. It sends `CapabilityInvocationRequest(tool_call_id, capability, agent_input)` to Backend; final-confirmation policy uses `prepare_confirmation` then `confirm_capability`; otherwise it invokes directly and polls `wait_for_capability` for a semantic result. Tool latency can delay a response waiting on the result, and may include Backend HTTP, Redis delivery, Worker execution, integration HTTP, and polling.

Backend `CapabilityInvocationService._validate_request` requires a connected call and a runtime-phase action, then persists invocation/outbox state; `CapabilityWorker._bind_input` validates Draft 2020-12 JSON Schema and canonical bindings, and `CapabilityWorker` executes the pinned HTTP plan through `HttpExecutionHandler`, reporting a typed result to Backend. `docs/reservation-submit-request.md` describes `reservation.submit_request@1`, and current sample schema includes `phone_number`, optional `phone_country`, guest name, dates, room type/count and confirmation policy. The actual enabled tenant action list and integration destination are **UNKNOWN / runtime-provided / not present in checkout**. **NOT MEASURED:** current provider microbenchmarks and synthetic pipelines do not execute realistic tools, Backend capability work, Redis Worker delivery, or integration calls.

## 10. LIVEKIT

`apps/voice-agent/pyproject.toml` pins `livekit-agents==1.8.2`, `livekit-plugins-elevenlabs==1.8.2`, and `livekit-plugins-openai==1.8.2`; Compose pins LiveKit server `v1.13.1`, SIP `v1.2.0`, and Egress `v1.13.0`. `build_server` registers `rtc_session`, `on_request` accepts validated metadata, and `run_job` waits for SIP or standard participant, starts an `AgentSession` in a room, speaks a greeting with TTS or Realtime generation, and waits for close. Cascade has `stt`, local `vad`, `llm`, `tts`; Realtime has sidecar `stt`, Realtime `llm`, no local VAD/TTS; half-cascade adds TTS. `LatencyInstrumentedAgent` wraps the standard agent nodes without changing the synthetic runners. `AgentSession.turn_handling` carries interruption and turn-detection settings; handoff uses the room's participant events. Audio leaves through LiveKit session output and the SIP participant. Actual caller playout and production EOU timing are **NOT MEASURED**.

Version-specific behavior relevant here: `providers.py:_create_tts` uses `auto_mode=False` for `eleven_v3*`; cascade passes a sentence tokenizer while half-cascade leaves the plugin's default word tokenizer. The installed LiveKit composition is exercised by `test_half_cascade_installed_livekit_pipeline_has_audio_input_text_output_and_tts`; the synthetic runner approximates provider/TTS boundaries, not the full installed playout path.

## 11. TELNYX / SIP / TELEPHONY

Inbound: Telnyx routes PSTN/SIP toward the provisioned LiveKit inbound trunk; LiveKit SIP creates a SIP participant/room and dispatches the agent. If job metadata lacks call ID, `resolve_call_session_id` requires SIP attributes `sip.callID`, `sip.phoneNumber`, `sip.trunkPhoneNumber`, `sip.trunkID`, `sip.ruleID`, then calls Backend `claim_inbound_sip`. Backend maps the called DID to tenant telephony state; the published execution is pinned before use. `infrastructure/livekit/sip/README.md` calls its JSON templates legacy diagnostics; normal provisioning is Backend Platform Telephony reconciliation, described in `docs/inbound-livekit-sip.md`. `sip.phoneNumber` is exposed to prompt dynamic context as caller number when available.

Outbound handoff: `transfer_to_human` sends a semantic destination to Backend; `CallSessionService.transfer_to_human` resolves the pinned destination/tenant caller ID and calls LiveKit `create_sip_participant` on the shared outbound trunk. `HandoffController` treats `participant_connected` as dialing evidence only and confirms answer when matching `sip.callStatus == "active"`; on success it completes Backend handoff and drains/shuts down the agent. Caller disconnect/cancel/failure/timeout are separate states. **UNKNOWN:** Telnyx media-region selection and actual per-call media route from this checkout. **NOT MEASURED by synthetic suites:** Telnyx media delivery, SIP transport, PSTN latency, and caller-audible time. The application can observe room/participant events and its own processing but cannot reconstruct the full carrier media path from the current artifacts.

## 12. ELEVENLABS STT

`_create_stt` maps Slovak `sk-SK` to ElevenLabs `slk`, passes a runtime model ID, keyterms, and optional provider VAD. The measured model is `scribe_v2_realtime`; the actual published model/keyterms are runtime-pinned **UNKNOWN**. In cascade its final transcript is **primary/causal** for model input. In Realtime/half-cascade it is a separate `AgentSession(stt=...)` stream whose final events are captured by `LatencyInstrumentedAgent.stt_node` and suppressed from the causal turn path. Realtime's own `input_audio_transcription` is a distinct configuration, not this sidecar credential. The sidecar supports lexical review of names and spelling through `get_recent_transcript`; effectiveness is not scored here.

**MEASURED standalone** (`benchmarks/stt/artifacts/2026-09-24T145535Z`, N=30, 9.5335-second mono 24 kHz PCM16 WAV, paced 50 ms chunks): first partial **2422 / 2847** from request start; request start → final **10114 / 10821** includes the entire streamed WAV; **logical audio end → final 194 / 253** is the useful post-speech provider interval. Connection time is separate, **205 / 470**. Synthetic cascade post-speech STT final: Azure **210 / 270**, direct Fast **214 / 286**. Neither value includes natural production EOU.

## 13. LLM — AZURE OPENAI AND DIRECT OPENAI

**AZURE OPENAI:** Cascade `create_agent_session` uses `openai.LLM.with_azure(azure_deployment, azure_endpoint, api_version, ...)` or `/openai/v1` `base_url` when configured. Runtime deployment provides logical model and optional tier; GPT-5/o-series receives configured reasoning effort, not an unsupported temperature. Standalone artifact model was `gpt-5.6-terra`, Azure deployment `gpt-5.6-terra`, configured `polandcentral`, max 128 output tokens; exact published runtime is **UNKNOWN**.

**DIRECT OPENAI:** Cascade code uses `openai.LLM(...)` for `provider_kind="openai"`; direct provider routing geography is **UNKNOWN**. Standalone `gpt-5.6-terra` artifacts compare requested `default` and `fast`; direct Fast responses reported actual service tier `priority` in the measured requests. This is an API response fact, not proof that Fast and Priority are universally equivalent.

**MEASURED standalone LLM**, same prompt scenarios within each 80-run suite, `TTFT = request → first text`, medians/p90:

| Provider / requested tier | TTFT | First speakable | Completion | Successful N | Artifact |
|---|---:|---:|---:|---:|---|
| Azure default | 1416 / 1749 | 1506 / 2108 | 1619 / 2131 | 80 | `benchmarks/llm/artifacts/2026-09-24T101145Z` |
| Azure priority | 1312 / 1733 | 1507 / 1865 | 1575 / 1906 | 80 | `.../2026-09-24T101416Z` |
| Direct OpenAI default | 818 / 1451 | 1325 / 1967 | 1689 / 2209 | 80 | `.../2026-09-24T101647Z` |
| Direct OpenAI fast (reported priority) | 703 / 916 | 952 / 1442 | 1219 / 1606 | 80 | `.../2026-09-24T101928Z` |

Each suite includes minimal/production-like and cold/warm prompt-cache scenarios; the local production prompt file is not a published call projection. Direct Fast has materially lower measured TTFT than Azure default in these standalone tests. **MEASURED synthetic cascade:** Azure LLM first text **2925 / 3915**, direct Fast **2204 / 3121**; output cap is 512 in both successful pipelines. Audio end → first TTS audio improves **463 ms median (12.7%)** and **292 ms p90**: 3644 → 3181 and 4534 → 4242. This experiment changed **Azure → direct OpenAI** and **default → requested fast** together, at a different time; the effect of Fast alone cannot be isolated. Why synthetic LLM TTFT is much higher than standalone TTFT remains an open question.

## 14. REALTIME — AZURE AND DIRECT OPENAI

Production Realtime/half-cascade factories in this checkout use LiveKit OpenAI `RealtimeModel` with Azure deployment/base URL options. The synthetic Azure runs use `gpt-realtime-2.1` with configured `francecentral`; published production deployment/voice/turn policy remain runtime-provided. Realtime native input transcription is configured through a separate capable STT deployment and same Azure provider connection. Full Realtime sends native audio; half-cascade requests text modality.

**MEASURED standalone Realtime** (`benchmarks/realtime/run.py`) burst-appends the same WAV, manually commits, and compares fresh/continued sessions and minimal/production-like prompts. Azure `2026-09-24T102340Z`: 80/80 successes, input end → first audio **1740 / 3387**, first text **1495 / 3136**. Direct OpenAI `2026-09-24T103150Z`: only **14 successes and one failure** despite manifest target of 80; first audio **1767 / 3316**, first text **1562 / 3051**. The incomplete direct sample is not a robust provider comparison. **MEASURED synthetic pipeline** Azure `2026-09-24T145329Z`: first audio **2857 / 3973**, N=30, first text **2599 / 3719**. These runs use burst-upload/manual commit and omit production server EOU, LiveKit, and caller playout. Full Realtime Slovak pronunciation/transcript concern is **OBSERVED project testing context**, not measured quality evidence in these artifacts.

## 15. ELEVENLABS TTS

`providers.py:_create_tts` receives model ID, voice ID and language from runtime; the measured model is `eleven_v3_conversational` and measured standalone voice ID is in the TTS manifest, but the actual published voice is **UNKNOWN / runtime-provided / not present in checkout**. It sets `auto_mode=False` only for `eleven_v3*`. Cascade supplies `SentenceTokenizer(min_sentence_len=runtime threshold)`; half-cascade does not override `word_tokenizer`, so the installed LiveKit plugin's default word boundary is relevant. Streaming text can enter TTS before model completion, though the measured cascade fixture usually produced its first tokenizer chunk near completion.

**MEASURED standalone** (`benchmarks/tts/artifacts/2026-09-24T145327Z`, MP3 stream, 30 per text):

| Text | First audio median / p90 | Completion median / p90 | N |
|---|---:|---:|---:|
| Short | 170 / 228 | 377 / 431 | 30 |
| Normal | 172 / 208 | 756 / 825 | 30 |
| Long | 161 / 176 | 1718 / 1825 | 30 |

First bytes stay near 160–170 ms across these lengths; completion grows with text length. Streamed MP3 probe did not determine audio duration/real-time factor or first caller-playable boundary. Pipeline TTS start → first audio: Azure cascade **225 / 298** (N=30), direct Fast cascade **233 / 330** (N=30), half-cascade **167 / 215** (N=29). These are provider-output boundaries, not audible playout.

## 16. Deployment and Region Map

The table separates configured benchmark geography from verified production placement. Network DNS/TCP/TLS is not geographic proof.

| Component | Provider/service/model | Deployment | Configured region / geography | Source and confidence |
|---|---|---|---|---|
| Voice Agent runtime | Self-hosted Compose service | `voice-agent` image built locally | **UNKNOWN** actual host; benchmark host `nikitapc` | Compose/config; production host not inspected |
| LiveKit media/room | LiveKit server `v1.13.1`, SIP `v1.2.0` | Compose `livekit`, `livekit-sip` | Benchmark network manifest labels **Warsaw**; live deployment **UNKNOWN** | Manifest/configured label only; no live route proof |
| Telnyx media/SIP | Telnyx → LiveKit trunk | Provisioned resource IDs runtime-owned | **UNKNOWN / runtime-provided / not present in checkout** | No media-region artifact |
| Azure cascade LLM | Azure OpenAI `gpt-5.6-terra` in benchmark | Benchmark deployment `gpt-5.6-terra` | Benchmark configured `polandcentral`; published runtime **UNKNOWN** | LLM manifest; runtime model resource is DB state |
| Direct OpenAI LLM | OpenAI `gpt-5.6-terra` benchmark | Provider-routed | **UNKNOWN** provider region | LLM/cascade manifests label `provider_routed` |
| Azure Realtime | Azure OpenAI `gpt-realtime-2.1` benchmark | Benchmark deployment `gpt-realtime-2.1` | Benchmark configured `francecentral`; published runtime **UNKNOWN** | Realtime manifest; runtime model resource is DB state |
| Direct OpenAI Realtime | OpenAI `gpt-realtime-2.1` standalone | Provider-routed benchmark | **UNKNOWN** provider region | Standalone manifest; not verified as production runtime path |
| ElevenLabs STT | `scribe_v2_realtime` benchmark | Runtime deployment ref | **UNKNOWN** ElevenLabs processing region | STT manifest uses `YOUR_REGION` placeholder |
| ElevenLabs TTS | `eleven_v3_conversational` benchmark | Runtime deployment ref/voice | **UNKNOWN** ElevenLabs processing region | TTS manifest uses `YOUR_REGION` placeholder |
| Backend / Control Plane / Job Worker | Self-hosted Compose | `backend`, `control-plane-service`, `job-worker` | Benchmark Backend label **Warsaw**; live host **UNKNOWN** | Network manifest and Compose |
| PostgreSQL / Redis | Self-hosted Compose | `postgres`, `redis` | **UNKNOWN** actual host/region; in Compose application network | Compose only |

## 17. Network Measurements

**MEASURED network/setup** (`benchmarks/network/artifacts/2026-09-24T145328Z`, 30 per target/boundary, median / p90):

| Target | DNS | TCP | TLS | Cold HEAD | Reused HEAD | WebSocket connect |
|---|---:|---:|---:|---:|---:|---:|
| Azure LLM | 3 / 11 | 21 / 34 | 172 / 370 | 143 / 234 | 29 / 55 | — |
| Azure Realtime | 3 / 14 | 21 / 32 | 233 / 416 | — | — | 348 / 601 |
| Direct OpenAI LLM | 2 / 6 | 5 / 15 | 114 / 341 | 268 / 404 | 204 / 259 | — |
| Direct OpenAI Realtime | — | — | — | — | — | 665 / 1038 |
| ElevenLabs | 2 / 2 | 10 / 11 | 41 / 52 | 179 / 202 | 138 / 164 | — |
| LiveKit | 2 / 7 | 24 / 35 | 226 / 459 | — | — | — |
| Backend | 2 / 8 | 23 / 30 | 116 / 449 | 125 / 339 | 28 / 47 | — |

HEAD may return an authorization/route error and still time setup. DNS, TCP, TLS, HEAD, and WebSocket columns are different boundaries, not additive per-turn charges. Cold connections should not automatically be attributed to every turn; connection pooling/continued session behavior differs. Geography may matter, but these tens-to-hundreds-of-ms measurements alone do not explain multi-second model-generation intervals. No Telnyx media timing was captured.

## 18. Latency Benchmark Methodology

**Provider microbenchmarks:** `benchmarks/llm/run.py` times streaming text response with minimal/production-like prompt and cache scenarios; `benchmarks/realtime/run.py` times direct Realtime WebSocket output after one burst audio append/manual commit; `benchmarks/stt/run.py` paces 50 ms WAV chunks and separates audio-end-to-final from full fixture streaming; `benchmarks/tts/run.py` times MP3 first bytes/completion for three texts. Local production-like prompt files are not effective published execution prompts.

**Synthetic pipeline benchmarks:** `benchmarks/pipeline/cascade/run.py` paces ElevenLabs STT, then direct model stream, LiveKit sentence tokenization, direct ElevenLabs TTS; `benchmarks/pipeline/realtime/run.py` burst-uploads audio to Azure Realtime and manually commits; `benchmarks/pipeline/half_cascade/run.py` uses burst Realtime text and direct ElevenLabs TTS at a word-token boundary, omitting observer STT. The same 9.5335-second Slovak WAV fixture is used; each measured pipeline has 30 attempts, half-cascade 29 successes. First-output boundaries are provider events/bytes. These are **synthetic pipeline latency**, not **production E2E latency** or **caller-audible latency**.

**Network/setup benchmark:** `benchmarks/network/run.py` times DNS/TCP/TLS, cold/reused HEAD and new WebSocket handshakes from the benchmark host. It does not measure live media or steady-state model inference. Manifests preserve model, target, output cap, region label, input mode, sample counts, and source commit.

## 19. LLM Benchmark Results

Standalone four-suite table and synthetic LLM stages are in §13. Important comparison: Azure default standalone TTFT **1416 / 1749** (N=80) versus direct OpenAI Fast **703 / 916** (N=80); direct default was **818 / 1451**. Synthetic cascade LLM first text is **2925 / 3915** Azure versus **2204 / 3121** direct Fast (both N=30). The standalone and pipeline tests differ in timing, prompt/tool representation, context, output cap (128 vs 512), and run time; the discrepancy is a research question. Direct Fast cascade total improved **463 ms median, 12.7%; 292 ms p90**, but provider and tier changed together. Actual service tier reported by the Fast API requests was `priority`.

## 20. STT Benchmark Results

See §12 for the exact STT artifact and boundaries. **MEASURED** Scribe standalone logical audio end → final **194 / 253**, N=30. Cascade pipeline audio end → STT final: Azure **210 / 270**, direct Fast **214 / 286**. Full WAV request start → final **10114 / 10821** includes approximately 9.53 seconds of paced audio and must not be called STT post-speech latency. Production EOU and sidecar lexical quality are **NOT MEASURED**.

## 21. TTS Benchmark Results

See §15 for all three standalone text lengths. **MEASURED** first audio: short **170 / 228**, normal **172 / 208**, long **161 / 176**, each N=30; completion **377 / 431**, **756 / 825**, **1718 / 1825** respectively. Synthetic TTS first audio spans **167–233 ms median** across the three relevant pipeline variants, with different token boundaries and concurrency. Caller playout and phonetic quality are **NOT MEASURED**.

## 22. Synthetic Pipeline Results

**Major comparison table — first provider output audio, median / p90 in ms.** These are separate runs; cascade paces STT, Realtime variants burst-upload/manual-commit. No strict apples-to-apples architecture claim follows.

| Architecture | Model path | Median | p90 | Successful N / attempts | Notes |
|---|---|---:|---:|---:|---|
| Cascade Azure | Azure `gpt-5.6-terra` + ElevenLabs STT/TTS | 3644 | 4534 | 30/30 | Paced STT; sentence threshold 20; cap 512 |
| Cascade OpenAI Fast | Direct OpenAI `gpt-5.6-terra`, requested fast + ElevenLabs | 3181 | 4242 | 30/30 | Paced STT; API reported priority; separate time |
| Realtime | Azure `gpt-realtime-2.1` native audio | 2857 | 3973 | 30/30 | Burst input/manual commit |
| Half-cascade | Azure `gpt-realtime-2.1` text + ElevenLabs TTS | 3096 | 4306 | 29/30 | Burst input; one first-output timeout |

Primary sources: `benchmarks/results/2026-09-24T150504Z/benchmark_summary.md`, `benchmarks/results/2026-09-24T152653Z/cascade_openai_fast_comparison.md`, and corresponding raw `summary.json`/`manifest.json` files (`cascade` `2026-09-24T145629Z`, `2026-09-24T151752Z`; `realtime` `2026-09-24T145329Z`; `half_cascade` `2026-09-24T145624Z`).

## 23. Latency Budget by Architecture

| Architecture | Measured causal stages | Interpretation boundary |
|---|---|---|
| Cascade Azure | STT after logical audio end 210 / 270; LLM first text 2925 / 3915; first speakable 2967 / 3951; TTS first audio 225 / 298; total 3644 / 4534 | Model text dominates; tokenizer may defer TTS. Medians are not additive because runs/overlap differ. |
| Cascade direct Fast | STT 214 / 286; LLM first text 2204 / 3121; first tokenizer chunk 2618 / 3649; TTS 233 / 330; total 3181 / 4242 | First text is earlier, but tokenizer/model completion still matters. |
| Realtime Azure | `response.created` 148 / 340; first text 2599 / 3719; native first audio 2857 / 3973 | Realtime generation dominates measured input-end interval. |
| Half-cascade | `response.created` 151 / 398; first text 2928 / 4085; first word 2952 / 4114; TTS 167 / 215; total 3096 / 4306 | Realtime text dominates; TTS adds roughly 167 ms median after TTS start. |

**INFERRED:** Current synthetic evidence points to model inference/generation as the dominant measured latency contributor. STT post-speech is low hundreds of ms, TTS first output roughly 160–225 ms in the core runs, and network/setup tens to hundreds depending on boundary. It does **not** establish the same percentage in production E2E because production EOU, LiveKit playout and PSTN/Telnyx timing are absent. A genuine sub-500 ms first-audio goal needs a precisely defined boundary before any architecture conclusion.

## 24. Slovak and Czech Quality Issues

**OBSERVED project testing context:** Full Realtime Slovak pronunciation and transcription have been raised as quality concerns; names/surnames, spelling and phone capture are high-value error points. Half-cascade exists to keep Realtime understanding while using external ElevenLabs TTS; standalone Scribe sidecar offers an alternate lexical transcript for Realtime paths. Cascade has a primary Scribe transcript. The code explicitly supports Slovak locales via `provider_languages`; Czech `cs` currently raises a `ValueError` at this adapter. Thus Czech production quality cannot be inferred from this checkout. The prompt target document discusses spoken normalization, but active tenant wording is runtime-provided.

**NOT MEASURED:** The 2026-09-24 suite has no MOS/AB preference, pronunciation evaluation, word error rate, name-specific recognition score, phone accuracy, interruption quality, or Czech sample. Any architecture quality preference should be stated as a hypothesis or separate project observation, not as a latency benchmark result.

## 25. Names and Surnames

The current design addresses misheard names and exact spelling by feeding Realtime/half-cascade audio to standalone STT in parallel. `LatencyInstrumentedAgent.stt_node` stores final segments in `RecentTranscriptBuffer` (per call, `deque(maxlen=20)`, monotonically numbered), and `recent_transcript_tool` returns 1–10 recent segments plus combined text on request. `assemble_instructions` tells the model to call `get_recent_transcript` when exact lexical form matters, particularly names, email, identifiers and spelling; the tool is installed only for Realtime and half-cascade. It is **observer-only**: final Scribe text is not yielded as Realtime turn input and cannot be assumed to override the Realtime model automatically. Cascade already uses Scribe as primary STT and does not add this tool. No name/surname recognition rate or verified gain from the sidecar is in the current benchmark.

## 26. Phone Numbers

`assemble_instructions` says to capture a spoken number as given and pass it unchanged to reservation actions; do not invent E.164 or digits. Explicit `+420`/`00421` country prefix needs no country question; a national number needs confirmed ISO alpha-2 `phone_country`. SIP `sip.phoneNumber` is available as caller number in dynamic context and must be preserved as received if used; Backend separately retains canonical `caller_phone_e164` for capability metadata when available. `docs/reservation-submit-request.md` shows a reservation schema with `phone_number` bound to canonical `guest.phone` plus optional `phone_country`, though the actual published tenant schema is **UNKNOWN**. Worker `_bind_input` applies the normalizer based on the **binding target**, strips formatting/`00` prefix, uses `phonenumbers`, requires `phone_country` for a national format, and rejects invalid numbers. A schema field alone does not cause normalization or the agent to supply a country. `phone_country_required` is a real failure path. Spoken-number fidelity and downstream acceptance are **NOT MEASURED** by latency suites.

## 27. Turn Detection / Interruptions / Barge-in

**CASCADE:** `create_agent_session` builds `inference.VAD` from runtime speech activity, `turn_detection="stt"`, fixed min/max endpoint delay, and either provider VAD or `LocalVadCommitSTT`/`LocalVadCommitController`. It applies configured interruption duration/words/false-interruption timeout/resume and configured preemptive generation/TTS. The actual published values are **UNKNOWN**; do not carry old constants from `docs/livekit-voice.md` into this runtime.

**REALTIME and HALF-CASCADE:** `vad=None`, `turn_detection="realtime_llm"`; `_realtime_turn_detection` selects Realtime `ServerVad` or `SemanticVad` from runtime `turn_completion`, with `create_response=True` and `interrupt_response` linked to interruption enabled. LiveKit handles session interruption; half-cascade code explicitly expects cancellation of Realtime text generation and TTS on caller interruption. Standalone STT does not own EOU for these modes. **NOT MEASURED:** natural production EOU delay and end-to-first-agent-audio timing. Burst/manual commit in synthetic Realtime bypasses normal server turn completion; cascade manual STT commit/paced audio does not reproduce all production VAD/EOU behavior. Barge-in correctness/latency needs real call evidence.

## 28. Transcript Handling

`run_job` subscribes to `user_input_transcribed` for privacy-safe length/language logging and to `conversation_item_added` for persistence. `ConversationPersistence.message_from_event` persists user/assistant `ChatMessage` text (including interruption flag) to Backend through a bounded queue; it does not persist raw sidecar STT events as extra user turns. On shutdown `finish()` drains pending messages before finalization. Realtime/half-cascade sidecar finalized text goes into call-local `RecentTranscriptBuffer`; `get_recent_transcript` exposes it to the model only when called. Backend `FinalizationService._transcript` builds the post-call transcript from canonical conversation messages. Recording/LiveKit Cloud record fields are disabled in `session.start` (`audio`, `traces`, `logs`, `transcript` false); explicit OpenTelemetry and Backend persistence remain. Exact transcript quality and sidecar use frequency are **UNKNOWN** from these artifacts.

## 29. Known Limitations of Current Measurements

- **NOT MEASURED:** production E2E, caller-audible first sound, PSTN delay, Telnyx media delivery/region, SIP transport, LiveKit production playout, and production EOU. Existing production observability code is present, but no correlated live call trace was included in these result snapshots.
- Realtime and half-cascade synthetic tests **burst-uploaded** 9.5335 seconds of audio and manually committed. Cascade/STT used **real-time-paced** 50 ms chunks and manual STT commit. Input-end boundaries therefore differ, so cross-architecture rows are directional.
- Sentence tokenizer threshold **20** was a benchmark argument because the published runtime value was unavailable. Successful cascade runs used **512** max output tokens; standalone LLM suites used **128**. Published production values remain unknown.
- Synthetic pipelines omit actual `AgentSession` room media, realistic conversation history, tool schemas/execution, Backend/Worker/integration, handoff, retries and audible decoding/playout. Half-cascade omits its non-causal standalone STT. The TTS MP3 probe lacks audio-duration/first-playable timing.
- Provider tests occurred at different times; some provider traffic may have overlapped. Direct Fast comparison changed provider and requested tier simultaneously. Direct Realtime standalone test ended with only 14 successes and one failure despite an 80-run target. Half-cascade pipeline had one first-output timeout.
- Benchmark configured-region fields include `YOUR_REGION` placeholders. DNS/TCP/TLS/HEAD setup from one host does not determine media/provider processing region or steady-state per-turn overhead. Manifest labels are not deployment verification.

## 30. Current Engineering Questions

1. Why is cascade LLM TTFT **2925 ms** Azure / **2204 ms** direct Fast in synthetic pipelines versus **1416 ms** / **703 ms** in standalone suites? How much is output cap, prompt/context, provider load, tokenization, and runner behavior?
2. How much does natural production EOU add for each mode, and where are its first/last audio timestamps recorded?
3. What are the actual published model, reasoning effort, token cap, prompt length, tool schema size, sentence threshold, voice, VAD, and region for the call under review?
4. How much does production-like Realtime audio streaming/server turn detection change the input-end-to-first-output result?
5. What exact media route and geography do LiveKit SIP, Telnyx, Voice Agent, Azure, and ElevenLabs use during a production call?
6. Which model/context/streaming design could reach a precisely defined sub-500 ms boundary while preserving Slovak/Czech name, phone and pronunciation quality?
7. How often does `get_recent_transcript` actually improve lexical accuracy, and what is the impact of sidecar completion timing?
8. What are tool call p50/p90 and speech-to-result-to-audio timing for real reservation actions?

## 31. Questions for Viktor

**Latency methodology**

1. When you say **<500 ms**, which exact timestamps define it: last user audio → first agent audio, detected EOU → first agent audio, or model-only? Where are the timestamps captured, including caller playout?
2. Is the path PSTN/SIP or WebRTC? Is the figure p50, p90, or best case; how many calls and which language/input length?
3. In your prior approximately 3-second LiveKit system, what were measured stage-level bottlenecks: EOU, STT, model first text, tokenizer, TTS, network, or playout?

**Cascade**

4. Which exact STT, LLM, TTS models, reasoning settings, output cap and prompt/tool context reach your target? Do you stream partial STT transcripts into the LLM or use preemptive/speculative execution?
5. Do you start TTS before sentence completion, and how do you prevent bad first phrases and interruptions? How do you explain our standalone LLM TTFT versus synthetic cascade TTFT difference?
6. Given our measured post-speech STT near 200 ms and TTS first bytes near 170–225 ms, where would you focus first for a genuine sub-500 ms cascade response?

**Realtime**

7. How do you handle EOU/server turn detection and interruption in production? What happens to latency with naturally streamed audio versus burst/manual commit?
8. What Slovak/Czech pronunciation, transcript, names and phone quality evidence do you have for full Realtime, including an exact model/voice/configuration?

**Half-cascade**

9. Have you measured audio-in/text-out Realtime plus external TTS with word-level or sentence-level streaming? Which stage dominated and how was TTS cancellation handled?
10. Would you favor cascade, full Realtime, or text-Realtime plus external TTS for Slovak/Czech, and on what measured quality and latency basis?

**Regions/network**

11. How are Telnyx, LiveKit media/SIP, agent process, Azure/direct OpenAI and ElevenLabs colocated? Which geography is verified versus inferred from RTT?

**Production experience**

12. What stage traces and caller-audible timestamps do you collect, and what p50/p90 variation appears with real calls, tools, barge-in and provider load?

## 32. File / Class / Function Index

| Search symbol | Exact file | Use during call |
|---|---|---|
| `run_job`, `build_server`, `resolve_call_session_id` | `apps/voice-agent/src/voice_agent/main.py` | LiveKit entry, architecture switch, SIP claim, session output |
| `assemble_instructions`, `build_agent_tools`, `capability_tool`, `handoff_tool` | `apps/voice-agent/src/voice_agent/main.py` | Effective prompt and tool schema/execution |
| `create_agent_session`, `create_realtime_session`, `create_half_cascade_session` | `apps/voice-agent/src/voice_agent/providers.py` | Three production runtime constructors |
| `_create_stt`, `_create_tts`, `_realtime_options`, `_realtime_transcription`, `_realtime_turn_detection`, `llm_behavior_options` | `apps/voice-agent/src/voice_agent/providers.py` | Exact provider/voice/turn adapter behavior |
| `LocalVadCommitController`, `LocalVadCommitSTT` | `apps/voice-agent/src/voice_agent/stt_endpointing.py` | Local VAD-based STT commit |
| `LatencyInstrumentedAgent`, `VoiceMetrics` | `apps/voice-agent/src/voice_agent/observability.py` | Production stage telemetry and STT sidecar suppression |
| `RecentTranscriptBuffer`, `recent_transcript_tool`, `role_for_architecture` | `apps/voice-agent/src/voice_agent/recent_transcript.py`; `stt_role.py` | Names/spelling observer path |
| `ConversationPersistence`, `message_from_event` | `apps/voice-agent/src/voice_agent/event_delivery.py` | User/assistant transcript persistence |
| `HandoffController` | `apps/voice-agent/src/voice_agent/handoff.py` | SIP answer confirmation/cancellation |
| `BackendClient`, `CallFinalizer` | `apps/voice-agent/src/voice_agent/backend.py` | Voice Agent → Backend requests |
| `RuntimeResolver.resolve_state`, `_cascade`, `_realtime`, `_half_cascade`, `_resource` | `apps/control-plane-service/src/control_plane/application/runtime_resolver.py` | Active architecture and deployment validation |
| `ExecutionMaterializationService._target_state`, `_voice_runtime`, `_runtime_bindings`, `runtime_secret`, `voice_context` | `apps/control-plane-service/src/control_plane/application/execution_materialization.py` | Pinned snapshot, consumer projection, late secrets |
| `CallSessionService.claim_inbound_sip`, `get_runtime_context`, `transfer_to_human` | `apps/backend/src/backend_core/modules/calls/service.py` | SIP claim, pinned context, outbound SIP |
| `CapabilityInvocationService._validate_request`, `_invoke`, `record_result` | `apps/backend/src/backend_core/runtime/capabilities/service.py` | Action validation, outbox and semantic result |
| `CapabilityWorker`, `_bind_input`, `HttpExecutionHandler` | `apps/job-worker/src/job_worker/worker.py` | Redis job, canonical phone normalization, external HTTP |
| `FinalizationService._transcript` | `apps/backend/src/backend_core/runtime/finalization/service.py` | Post-call transcript |
| `VoiceExecutionContext`, `WorkerExecutionContext`, `RuntimeSecretSlot` | `packages/contracts/src/contracts/` | Shared consumer contracts |
| `benchmarks/stt/run.py`, `benchmarks/tts/run.py`, `benchmarks/llm/run.py`, `benchmarks/realtime/run.py` | `benchmarks/` | Provider microbenchmark definitions |
| `benchmarks/pipeline/{cascade,realtime,half_cascade}/run.py`, `benchmarks/network/run.py` | `benchmarks/` | Synthetic pipeline and setup definitions |

## 33. Quick Search Keywords

| Keyword | Jump to |
|---|---|
| CASCADE | §02–03, §13, §18–23, §27 |
| REALTIME | §02, §04, §14, §18, §22–23, §27 |
| HALF-CASCADE | §02, §05, §14–15, §22–23, §27 |
| LIVEKIT | §01, §06, §10–11, §16–18 |
| TELNYX / SIP / PSTN | §01, §11, §16, §29 |
| STT / Scribe | §03–05, §12, §20, §25 |
| TTS / ElevenLabs | §03, §05, §15, §21 |
| AZURE OPENAI / DIRECT OPENAI | §13–14, §16–19 |
| REGIONS / network | §16–17, §29, §31 |
| PROMPTS / runtime resolution / secrets | §07–08, §32 |
| TOOLS / reservation / Worker | §09, §26, §32 |
| LATENCY / benchmarks / limitations | §18–23, §29–31 |
| SLOVAK / CZECH / NAMES | §24–25, §31 |
| PHONE NUMBERS / `phone_country` | §09, §26 |
| TURN DETECTION / BARGE-IN / TRANSCRIPT | §27–28 |
| VIKTOR | §31 |

### Current-document conflict and verification notes

- `docs/livekit-voice.md` describes older `VoiceRuntimeRevision` and environment-selected Azure deployment. Current `RuntimeResolver`/`ExecutionMaterializationService` use active semantic components, managed deployments, immutable execution snapshots and late-bound secrets. Use current code for call behavior; the older note is not an authority for current model/region/turn settings.
- Current `providers.py` passes a Realtime input-transcription configuration and `RuntimeResolver._realtime_transcription` enforces Azure same-connection compatibility; do not describe Realtime transcription as universally disabled merely because standalone STT was added.
- Result manifests contain `YOUR_REGION` placeholders and published runtime values are absent. Benchmark configuration is evidence of the benchmark only.
