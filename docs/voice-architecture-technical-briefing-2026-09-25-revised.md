# Voice Architecture Technical Briefing — Call Edition

**Review date:** 2026-09-25  
**Repository checkout inspected by source briefing:** 2026-09-24  
**Primary use:** fast technical reference during the external architecture/performance call.  
**Units:** milliseconds unless stated. Benchmark values are `median / p90` unless stated otherwise.

> **Call rule:** current benchmark numbers are provider/synthetic measurements, **not production E2E or caller-audible latency**.

### Evidence labels

- **MEASURED** — backed by a benchmark result artifact.
- **OBSERVED** — current repository behavior or explicit project testing context recorded in the source briefing.
- **INFERRED** — interpretation of measured/observed facts.
- **UNKNOWN** — runtime-provided or unavailable in the inspected checkout/artifacts.
- **NOT MEASURED** — outside the benchmark boundary.

---

## 00. CALL DASHBOARD — START HERE

### 00.1 Current architecture snapshot

| Architecture | Causal response path | Synthetic first audio | N | Main measured bottleneck |
|---|---|---:|---:|---|
| **CASCADE — Azure** | Scribe STT → Azure `gpt-5.6-terra` → sentence tokenizer → ElevenLabs TTS | **3644 / 4534** | 30 | LLM first text / first speakable |
| **CASCADE — Direct OpenAI Fast** | Scribe STT → direct `gpt-5.6-terra` requested `fast` → sentence tokenizer → ElevenLabs TTS | **3181 / 4242** | 30 | LLM + sentence boundary |
| **REALTIME — Azure** | Realtime audio in → native audio out | **2857 / 3973** | 30 | Realtime generation after `response.created` |
| **HALF-CASCADE — Azure + ElevenLabs** | Realtime audio in → text → word boundary → ElevenLabs TTS | **3096 / 4306** | 29/30 | Realtime text generation |

**Comparison warning:** Cascade uses real-time-paced STT input. Realtime and half-cascade burst-upload the WAV and manually commit. The table is **directional, not a controlled architecture ranking**.

### 00.2 What the measurements actually say

1. **MEASURED — model generation dominates the synthetic pipelines.** Post-speech STT is roughly **194–214 ms median**; ElevenLabs first audio is roughly **161–233 ms median**; model text/audio generation is measured in **seconds**.
2. **MEASURED — direct OpenAI Fast materially improved the cascade baseline, but did not solve it.** Synthetic total improved **3644 → 3181 ms**: **−463 ms (−12.7%)** median and **−292 ms p90**. Provider **and** requested service tier changed, so the gain cannot be attributed to Fast alone.
3. **MEASURED — sentence chunking is now a visible cascade cost.** Azure: first text **2925 ms** → first speakable **2967 ms** (~42 ms gap). Direct Fast: first text **2204 ms** → first speakable **2618 ms** (~414 ms gap). The earlier TTFT advantage is partly lost before TTS can start.
4. **MEASURED — cascade streaming overlap is weak for this fixture.** TTS started before LLM completion in only **4/30 Azure** and **3/30 direct Fast** runs. In half-cascade it started before Realtime completion in **29/29** successful runs.
5. **MEASURED — external ElevenLabs TTS is not the dominant half-cascade penalty.** Half-cascade first Realtime text is **2928 / 4085**; first speakable **2952 / 4114**; TTS first audio adds only **167 / 215** after TTS start.
6. **MEASURED — Realtime control/session events are not the multi-second bottleneck.** Synthetic `response.created` occurs around **148 / 340** (Realtime) and **151 / 398** (half-cascade), while first text arrives around **2599 / 3719** and **2928 / 4085** respectively.
7. **MEASURED — connection/setup latency is material but does not by itself explain multi-second response generation.** Typical measured boundaries are tens to hundreds of milliseconds; cold/session setup must not be charged to every turn automatically.
8. **OBSERVED — quality remains a separate constraint.** Full Realtime Slovak pronunciation/transcript fidelity, names/surnames and phone capture are project concerns; the latency suite is not a quality benchmark.

### 00.3 Critical unknowns before any production latency claim

**NOT MEASURED:**

- natural production EOU / endpointing delay;
- production LiveKit playout;
- Telnyx/SIP/PSTN media delivery;
- caller-audible first audio;
- realistic tool-call latency;
- effective published tenant prompt + tool-schema context;
- exact published production model/voice/reasoning/tokenizer/region settings.

### 00.4 Highest-value questions for Viktor

1. Your **<500 ms** claim: exact boundary — last user audio, detected EOU, or model request start → first agent audio?
2. Is that **PSTN/SIP or WebRTC**, and is it p50, p90, or best case?
3. Which exact **STT / LLM / TTS models**, reasoning settings, prompt/tool context and regions produce it?
4. In cascade, how do you get meaningful **LLM→TTS overlap** without waiting for a sentence boundary?
5. Do you use **partial STT / preemptive or speculative LLM execution** before final EOU?
6. Why might a standalone LLM test be much faster than the same LLM inside a synthetic voice pipeline?
7. In your prior ~3 s LiveKit system, what were the actual stage-level bottlenecks?
8. For Slovak/Czech, what measured quality/latency basis would you use to choose cascade vs full Realtime vs Realtime-text + external TTS?

---

## 01. SYSTEM MAP — COMPONENTS AND OWNERSHIP

```text
PSTN caller
  ↓
Telnyx
  ↓
LiveKit SIP → LiveKit room
  ↓
Voice Agent / AgentSession
  ├─ CASCADE: ElevenLabs STT → LLM → ElevenLabs TTS
  ├─ REALTIME: Azure Realtime audio → audio
  └─ HALF-CASCADE: Azure Realtime audio → text → ElevenLabs TTS
  ↕
Backend Core ←→ Control Plane
  ↕              ↕
PostgreSQL/Redis  immutable execution snapshot + late-bound secrets
  ↕
Job Worker → configured external integration
```

### 01.1 Runtime ownership

- **Backend Core:** call/conversation state, capability invocation, outbox, telephony reconciliation, runtime-context access.
- **Control Plane:** resolves published semantic state and materializes immutable execution snapshots; secrets remain late-bound.
- **Voice Agent:** constructs architecture-specific `AgentSession`, prompts/tools, provider adapters, transcript delivery and call lifecycle.
- **Job Worker:** executes configured integration jobs and reports typed results to Backend.
- **Observability:** OTel Collector, Prometheus, Tempo, Grafana plus existing `LatencyInstrumentedAgent` / `VoiceMetrics` production telemetry.

---

## 02. ARCHITECTURE — CASCADE

### 02.1 Runtime path

```text
Telnyx SIP
  → LiveKit room
  → local VAD / ElevenLabs Scribe STT [causal final]
  → Azure or direct OpenAI LLM
  → LiveKit SentenceTokenizer
  → ElevenLabs TTS
  → LiveKit output
```

**Source path:**

- `apps/voice-agent/src/voice_agent/main.py` — `run_job`
- `apps/voice-agent/src/voice_agent/providers.py` — `create_agent_session`, `_create_stt`, `_create_tts`, `llm_behavior_options`
- `apps/voice-agent/src/voice_agent/stt_endpointing.py` — `LocalVadCommitController`, `LocalVadCommitSTT`
- `apps/control-plane-service/src/control_plane/application/runtime_resolver.py` — `RuntimeResolver._cascade`

### 02.2 Production semantics

- `AgentSession(turn_detection="stt")`.
- STT final is causal for model input.
- LLM can be Azure OpenAI or direct OpenAI.
- TTS is ElevenLabs.
- Cascade uses `SentenceTokenizer(min_sentence_len=<runtime threshold>)`.
- Exact published deployment/model/reasoning/output cap/tokenizer threshold/voice are **UNKNOWN** from the checkout.

### 02.3 Synthetic stage breakdown

| Stage | Azure default | Direct OpenAI Fast |
|---|---:|---:|
| Audio end → STT final | 210 / 270 | 214 / 286 |
| STT final → LLM start | <1 / <1 | <1 / <1 |
| LLM start → first text | **2925 / 3915** | **2204 / 3121** |
| LLM start → first speakable/tokenizer chunk | **2967 / 3951** | **2618 / 3649** |
| TTS start → first audio | 225 / 298 | 233 / 330 |
| **Audio end → first TTS audio** | **3644 / 4534** | **3181 / 4242** |

### 02.4 Most important cascade finding

**MEASURED:** direct Fast improves first text much more than it improves first speakable audio. The first-text → first-speakable gap is roughly **42 ms Azure** versus **414 ms direct Fast**. For this fixture, sentence tokenization/response shape consumes a significant part of the provider TTFT gain.

**MEASURED:** TTS starts before model completion in only **4/30 Azure** and **3/30 direct Fast** runs. The current synthetic cascade behaves mostly like “model finishes enough text, then TTS” rather than aggressively overlapping generation and synthesis.

### 02.5 Direct Fast comparison caveat

- Requested service tier: `fast`.
- All measured API responses reported actual tier: `priority`.
- Provider changed **Azure → direct OpenAI** and tier changed **default → fast** together.
- Measurements occurred at different times.
- Therefore **Fast alone is not isolated**.

---

## 03. ARCHITECTURE — REALTIME

### 03.1 Runtime path

```text
Telnyx SIP
  → LiveKit
  → Azure Realtime audio input
  → server turn detection
  → Realtime generation / native audio
  → LiveKit output

Parallel observer:
  same caller audio → standalone ElevenLabs STT final → RecentTranscriptBuffer
```

**Source path:**

- `providers.py` — `create_realtime_session`, `_realtime_options`, `_realtime_transcription`, `_realtime_turn_detection`
- `observability.py` — `LatencyInstrumentedAgent.stt_node`
- `stt_role.py` — observer role mapping

### 03.2 Production semantics

- `vad=None`, `turn_detection="realtime_llm"`.
- Realtime model provides causal turn understanding/output.
- Standalone ElevenLabs STT is observer-only for lexical review; it does not gate Realtime response generation.
- Realtime input transcription remains configured separately; an older statement that it is universally disabled is stale.

### 03.3 Synthetic results

| Boundary from logical input end | Median / p90 |
|---|---:|
| `response.created` | 148 / 340 |
| First text | 2599 / 3719 |
| **First native output audio** | **2857 / 3973** |

**Interpretation:** the provider can create the response quickly; the multi-second interval is mainly generation after `response.created`.

**Methodology warning:** WAV input is burst-uploaded into a fresh provider session and manually committed. This is **not** natural production streaming or production EOU.

### 03.4 Quality context

**OBSERVED project concern:** Slovak native Realtime pronunciation and transcript fidelity are weaker than desired, especially around names/surnames and exact lexical data. This benchmark does not quantify that concern.

---

## 04. ARCHITECTURE — HALF-CASCADE

### 04.1 Runtime path

```text
Telnyx SIP
  → LiveKit
  → Azure Realtime audio input
  → Realtime text modality
  → LiveKit/default word-token boundary
  → ElevenLabs TTS
  → LiveKit output

Parallel observer:
  caller audio → standalone ElevenLabs STT final → RecentTranscriptBuffer
```

**Source path:**

- `providers.py` — `create_half_cascade_session`, `_create_tts`
- `stt_role.py` — `role_for_architecture`

### 04.2 Synthetic results

| Boundary | Median / p90 |
|---|---:|
| Input end → `response.created` | 151 / 398 |
| Input end → first Realtime text | **2928 / 4085** |
| Input end → first speakable/word | **2952 / 4114** |
| TTS start → first audio | **167 / 215** |
| **Input end → first TTS audio** | **3096 / 4306** |

- Successes: **29/30**.
- One measured failure: Azure `first_output_timeout` after ~10.5 s waiting for first output.
- One timeout is **not enough to infer a reliability rate**.

### 04.3 Most important half-cascade finding

**MEASURED:** Realtime text dominates. First text → first speakable is only ~24 ms median, and ElevenLabs produces first audio ~167 ms after TTS start.

**MEASURED:** TTS started before Realtime completion in **29/29 successful runs**. This path achieves the overlap that the sentence-tokenized cascade did not achieve for the same fixture.

**INFERRED:** external TTS is not the main reason half-cascade remains around ~3.1 s synthetic first-audio latency; the delay is upstream in Realtime text generation.

---

## 05. LATENCY EVIDENCE — CANONICAL TABLES

### 05.1 Synthetic architecture comparison

| Architecture | Model path | First provider audio median | p90 | Successful N / attempts | Input method |
|---|---|---:|---:|---:|---|
| Cascade Azure | Azure `gpt-5.6-terra` + ElevenLabs | 3644 | 4534 | 30/30 | paced STT, manual commit |
| Cascade OpenAI Fast | direct `gpt-5.6-terra` requested `fast` + ElevenLabs | 3181 | 4242 | 30/30 | paced STT, manual commit |
| Realtime Azure | `gpt-realtime-2.1` native audio | 2857 | 3973 | 30/30 | burst upload, manual commit |
| Half-cascade | `gpt-realtime-2.1` text + ElevenLabs | 3096 | 4306 | 29/30 | burst upload, manual commit |

**Do not rank architectures strictly from this table.** The input methodology and output path differ.

### 05.2 Standalone STT — ElevenLabs Scribe v2 Realtime

Fixture: 9.5335 s, mono 24 kHz PCM16, paced 50 ms chunks. N=30.

| Boundary | Median / p90 |
|---|---:|
| Request start → first partial | 2422 / 2847 |
| Request start → final | 10114 / 10821 |
| **Logical audio end → final** | **194 / 253** |
| Connection setup | 205 / 470 |

**Use `audio end → final` for post-speech STT latency.** The ~10.1 s full duration mostly contains the 9.53 s spoken fixture.

All measured runs returned a non-empty transcript. This is **not** a WER or name-recognition benchmark.

### 05.3 Standalone TTS — ElevenLabs v3 Conversational

N=30 per text.

| Text | First audio | Completion |
|---|---:|---:|
| Short | 170 / 228 | 377 / 431 |
| Normal | 172 / 208 | 756 / 825 |
| Long | 161 / 176 | 1718 / 1825 |

**Finding:** first-audio latency stays roughly stable as text length grows; completion latency grows with utterance length.

Measured output was streamed MP3. First caller-playable sample and real-time factor were unavailable.

### 05.4 Standalone LLM — compact comparison

| Provider / requested tier | TTFT | First speakable | Completion | N |
|---|---:|---:|---:|---:|
| Azure default | 1416 / 1749 | 1506 / 2108 | 1619 / 2131 | 80 |
| Azure priority | 1312 / 1733 | 1507 / 1865 | 1575 / 1906 | 80 |
| Direct OpenAI default | 818 / 1451 | 1325 / 1967 | 1689 / 2209 | 80 |
| Direct OpenAI fast (reported `priority`) | **703 / 916** | **952 / 1442** | **1219 / 1606** | 80 |

**Open question:** synthetic cascade TTFT is much slower than standalone LLM TTFT. The tests differ in prompt/context, timing, output cap, run time and pipeline behavior; this discrepancy is not explained yet.

### 05.5 Realtime microbenchmark context

- Azure standalone run: 80/80 successes; aggregate input-end → first audio **1740 / 3387**, first text **1495 / 3136**.
- Direct OpenAI standalone sample was incomplete and should not be used as a robust provider comparison.
- Synthetic Realtime used the simpler independent-session baseline shown in §03.

---

## 06. STREAMING / TOKENIZATION — IMPORTANT CALL TOPIC

This deserves its own section because it affects how much theoretical model TTFT improvement reaches the caller.

### 06.1 Cascade

- Azure first text → first speakable: ~**42 ms median**.
- Direct Fast first text → first speakable: ~**414 ms median**.
- TTS started before LLM completion: **4/30 Azure**, **3/30 direct Fast**.
- `first_speakable_to_tts_start_ms` itself is effectively zero; the waiting is before the tokenizer emits a usable chunk, not in application handoff.

### 06.2 Half-cascade

- Realtime first text → first word: ~**24 ms median**.
- TTS started before model completion: **29/29** successful runs.
- TTS first audio: **167 ms median**.

### 06.3 Question to investigate

How can cascade safely expose an earlier TTS boundary — word/phrase/semantic chunk, speculative TTS, or partial-sentence policy — without producing unstable first phrases or poor interruption behavior?

---

## 07. NETWORK / GEOGRAPHY

### 07.1 Useful measured setup boundaries

| Target | Cold/setup median / p90 | Reused / relevant median / p90 |
|---|---:|---:|
| Azure LLM | Cold HEAD 143 / 234 | Reused HEAD **29 / 55** |
| Direct OpenAI LLM | Cold HEAD 268 / 404 | Reused HEAD **204 / 259** |
| ElevenLabs | Cold HEAD 179 / 202 | Reused HEAD **138 / 164** |
| Backend | Cold HEAD 125 / 339 | Reused HEAD **28 / 47** |
| Azure Realtime | WS connect **348 / 601** | session is intended to persist during call |
| Direct OpenAI Realtime | WS connect **665 / 1038** | incomplete provider comparison elsewhere |
| LiveKit | DNS+TCP+TLS total setup order: hundreds of ms | no per-turn media timing captured |

### 07.2 Detailed network primitives

| Target | DNS | TCP | TLS |
|---|---:|---:|---:|
| Azure LLM | 3 / 11 | 21 / 34 | 172 / 370 |
| Azure Realtime | 3 / 14 | 21 / 32 | 233 / 416 |
| Direct OpenAI LLM | 2 / 6 | 5 / 15 | 114 / 341 |
| ElevenLabs | 2 / 2 | 10 / 11 | 41 / 52 |
| LiveKit | 2 / 7 | 24 / 35 | 226 / 459 |
| Backend | 2 / 8 | 23 / 30 | 116 / 449 |

### 07.3 Interpretation

- These are **setup/probe** boundaries, not guaranteed per-turn charges.
- HEAD probes may return auth/route errors and still provide setup timing.
- Do not add DNS + TCP + TLS + HEAD + WebSocket columns as a voice-turn budget.
- Geography may matter, but measured setup numbers alone do not explain multi-second model-generation latency.
- Direct OpenAI's LLM probe is not lower-latency at the HTTP setup layer than Azure, yet direct Fast produces faster model output in our model benchmarks. Provider inference/scheduling therefore remains a separate factor.

---

## 08. DEPLOYMENTS / REGIONS — WHAT IS KNOWN

| Component | Benchmark/current evidence | Geography | Confidence |
|---|---|---|---|
| Voice Agent runtime | self-hosted Compose service | actual host **UNKNOWN**; benchmark host `nikitapc` | checkout only |
| LiveKit | server `v1.13.1`, SIP `v1.2.0` | benchmark metadata label Warsaw; live placement **UNKNOWN** | configured label only |
| Telnyx SIP/media | provisioned trunk | media route **UNKNOWN** | not observable from artifacts |
| Azure cascade LLM | benchmark `gpt-5.6-terra` | configured `polandcentral`; published runtime **UNKNOWN** | benchmark manifest only |
| Direct OpenAI LLM | benchmark `gpt-5.6-terra` | provider-routed / **UNKNOWN** | benchmark only |
| Azure Realtime | benchmark `gpt-realtime-2.1` | configured `francecentral`; published runtime **UNKNOWN** | benchmark manifest only |
| ElevenLabs STT | benchmark `scribe_v2_realtime` | processing region **UNKNOWN** | manifest contains placeholder |
| ElevenLabs TTS | benchmark `eleven_v3_conversational` | processing region **UNKNOWN** | manifest contains placeholder |
| Backend | self-hosted | benchmark metadata label Warsaw; live host **UNKNOWN** | configured label only |
| PostgreSQL / Redis | Compose | actual region **UNKNOWN** | checkout only |

**Important:** network RTT is not proof of provider processing geography.

---

## 09. RUNTIME CONFIGURATION / CONTROL PLANE

### 09.1 Resolution flow

1. Published `Architecture`, `RuntimeOverrides`, `STTDefaults`, `LLMDefaults`, `TTSDefaults`, `RealtimeDefaults`, `Policies` enter `RuntimeResolver.resolve_state`.
2. `_resolve_candidate` selects `cascade`, `realtime`, or `half-cascade` and validates deployments/provider connections/credentials/capabilities.
3. `ExecutionMaterializationService.create_execution` persists an immutable `ExecutionSnapshot` and projects Backend/Voice/Worker consumer state.
4. Voice Agent gets the call's pinned `VoiceExecutionContext` through Backend and resolves late-bound secret slots.
5. Architecture-specific provider/session construction occurs in the Voice Agent.

### 09.2 Secret slots

- Cascade: `stt`, `llm`, `tts`.
- Realtime: `model`, `input_transcription`, `stt`.
- Half-cascade: same Realtime slots + `tts`.

### 09.3 Runtime values not verified in the checkout

**UNKNOWN:** active tenant execution ID, actual published provider resource IDs, voice IDs, keyterms, effective prompt text, tokenizer threshold, reasoning setting, output cap, service tier, exact production regions and credentials.

---

## 10. PROMPTS / TOOLS / CONTEXT

### 10.1 Prompt assembly

`main.py:assemble_instructions` assembles, in order:

1. System instructions
2. Profile instructions
3. Interaction instructions
4. Tenant instructions
5. Agent context / identity
6. Business context
7. Localization
8. Tenant knowledge
9. Dynamic context (date/time, SIP caller number where present)
10. Realtime/half-cascade recent-transcript instructions

The benchmark-local `production.txt` snapshots are **not proof of the actual published tenant prompt**.

### 10.2 Tools

`build_agent_tools` can install:

- calculator;
- `call.end`;
- `get_recent_transcript` where applicable;
- human handoff where configured;
- runtime actions such as reservation capabilities.

Tool execution can add Backend HTTP, Redis/Worker, external integration and polling latency. **None of that is represented in the current provider/synthetic latency results.**

---

## 11. LIVEKIT / TELNYX / MEDIA

### 11.1 LiveKit

Current source briefing records:

- `livekit-agents==1.8.2`
- `livekit-plugins-elevenlabs==1.8.2`
- `livekit-plugins-openai==1.8.2`
- LiveKit server `v1.13.1`
- SIP `v1.2.0`

`AgentSession` is shared across all architectures; the provider composition changes by architecture.

### 11.2 Telnyx / SIP

Inbound conceptual path:

```text
Telnyx PSTN/SIP → LiveKit inbound trunk → SIP participant/room → Voice Agent
```

Outbound handoff uses Backend-resolved destination/caller ID and LiveKit SIP participant creation. `HandoffController` treats participant connection as dialing evidence and confirms answer on `sip.callStatus == "active"`.

### 11.3 Media-latency boundary

**NOT MEASURED:**

- Telnyx media-region route;
- SIP media transport;
- LiveKit production output/pllout delay;
- RTP-on-wire timestamp;
- caller-audible first sample.

---

## 12. QUALITY — SLOVAK / CZECH / NAMES / PHONES

### 12.1 Slovak / Czech status

- **OBSERVED:** full Realtime Slovak pronunciation/transcription are project concerns.
- **OBSERVED:** names/surnames, spelling and phone capture are high-value error points.
- **OBSERVED:** `provider_languages` currently supports Slovak `sk*`; Czech `cs` raises a `ValueError` at this adapter boundary in the inspected checkout.
- Therefore **Czech runtime readiness/quality is not established** by this code or benchmark.

### 12.2 Names / exact lexical data

For Realtime and half-cascade:

```text
caller audio → standalone ElevenLabs STT → RecentTranscriptBuffer
                                  ↓
                        get_recent_transcript tool
```

- Observer-only: sidecar STT does not automatically replace Realtime turn input.
- Buffer is per-call and used when the model needs exact lexical form.
- Cascade already uses Scribe as primary STT.
- No name-recognition accuracy benchmark exists yet.

### 12.3 Phone numbers

Current prompt logic instructs the agent to preserve the spoken number as given rather than inventing normalized digits/E.164. Explicit international prefixes can be used directly; national formats require country context. SIP caller number can also be exposed in dynamic context.

Backend/Worker normalization is downstream and may reject invalid/national numbers when required country context is missing.

**NOT MEASURED:** spoken-number recognition accuracy or reservation-tool acceptance rate.

---

## 13. TURN DETECTION / INTERRUPTIONS / TRANSCRIPTS

### 13.1 Cascade

- local `inference.VAD`;
- `turn_detection="stt"`;
- exactly one completion authority from `Policies.cascade.stt_commit`: local VAD,
  provider VAD, or native STT endpointing;
- endpoint/interruption/preemptive settings come from runtime policy.

### 13.2 Realtime / half-cascade

- `vad=None`;
- `turn_detection="realtime_llm"`;
- Realtime `ServerVad` or `SemanticVad` is chosen from runtime turn-completion policy;
- standalone STT does not own EOU.

### 13.3 Missing latency evidence

Natural production EOU is currently **NOT MEASURED**. Synthetic Realtime manually commits after burst upload; cascade/STT manually commits after paced fixture input. Real call endpointing may materially change perceived latency.

### 13.4 Transcript persistence

- Canonical user/assistant conversation items are persisted to Backend.
- Sidecar STT finals go to `RecentTranscriptBuffer`, not extra user conversation turns.
- Post-call transcript is built from canonical conversation messages.

---

## 14. BENCHMARK METHODOLOGY / LIMITATIONS

### 14.1 Benchmark classes

- **Provider microbenchmark:** isolates provider response timing.
- **Synthetic pipeline:** composes provider stages without LiveKit room/PSTN production media.
- **Network/setup benchmark:** probes DNS/TCP/TLS/HTTP/WS setup from one host.

### 14.2 Shared fixture

- Slovak WAV duration: **9.5335 s**.
- PCM16, mono, 24 kHz.
- Cascade/STT: real-time-paced 50 ms chunks.
- Realtime/half-cascade: burst-upload + manual commit.

### 14.3 Important limitations

- no production E2E/caller-audible measurement;
- no production EOU;
- no LiveKit/Telnyx/PSTN media timing;
- no realistic production conversation history/tools in synthetic pipelines;
- benchmark sentence threshold = 20 because published runtime value was unavailable;
- successful cascade pipeline uses 512 output-token cap; standalone LLM used 128;
- provider runs occurred at different times and may overlap with other traffic;
- Direct Fast comparison changes provider and tier simultaneously;
- direct OpenAI Realtime standalone sample is incomplete and not a strong provider comparison;
- half-cascade had one `first_output_timeout`;
- benchmark region metadata includes placeholders for some providers.

---

## 15. OPEN ENGINEERING QUESTIONS

1. Why does synthetic cascade LLM TTFT run at **2925 ms Azure / 2204 ms direct Fast** versus standalone **1416 / 703 ms** aggregate TTFT?
2. How much production latency is currently hidden in **EOU / endpointing**?
3. Why does direct Fast's early first-text gain turn into a ~414 ms first-text → first-speakable wait in this synthetic cascade?
4. Would a phrase/word/semantic TTS boundary materially improve cascade latency without damaging naturalness or barge-in?
5. Can partial STT / preemptive generation start useful model work before final EOU?
6. How much would production-like Realtime streaming change input-end → first-output versus burst/manual commit?
7. What are the real production regions and media route across Telnyx, LiveKit, agent, Azure/OpenAI and ElevenLabs?
8. What is the actual published prompt/tool-schema size and its impact on model latency?
9. What quality evidence exists for Slovak/Czech names, phone numbers and pronunciation by architecture?
10. What are real reservation-tool p50/p90 timings and how do they interact with speech generation?

---

## 16. QUESTIONS FOR VIKTOR — FULL SET

### 16.1 Latency definition

1. When you say **<500 ms**, what exact timestamps define it: last user audio → first agent audio, detected EOU → first agent audio, or model request → first output?
2. Where are those timestamps captured? Do you have caller-side/audible timing or only server/provider timing?
3. PSTN/SIP or WebRTC? p50, p90, or best-case? How many calls?

### 16.2 Cascade

4. Which exact STT, LLM and TTS models/settings produce your best latency?
5. Do you stream partial STT into the LLM or wait for final transcript?
6. Do you use preemptive/speculative LLM work before final EOU?
7. What boundary do you use to start TTS — token, word, phrase, sentence, semantic chunk?
8. How do you prevent bad first phrases when starting TTS early?
9. In our direct Fast cascade, TTFT improves ~721 ms but first-speakable improves only ~350 ms; how would you attack that lost overlap?
10. Why might standalone LLM TTFT be much lower than synthetic-pipeline TTFT?

### 16.3 Realtime / half-cascade

11. How do you measure natural Realtime EOU and audio response latency with continuous input?
12. Have you measured audio-in/text-out Realtime + external TTS? Which stage dominates?
13. How do you cancel external TTS cleanly on barge-in?
14. What Slovak/Czech quality evidence do you have for full Realtime versus external STT/TTS paths?

### 16.4 Geography / infrastructure

15. How do you place Telnyx media, LiveKit SIP/media, agent compute, model provider and TTS/STT geographically?
16. Which geography facts do you verify directly versus infer from network timing?
17. In your prior ~3-second LiveKit deployment, what exact stage trace showed the biggest bottleneck?

### 16.5 Production observability

18. Which per-turn metrics do you retain in production: EOU, STT final, first model text, first speakable, TTS first byte, audio publish, caller-audible?
19. What p50/p90 variability do you normally see with real tools, interruptions and provider load?

---

## 17. SOURCE CODE MAP — CTRL+F REFERENCE

| Search symbol / topic | File | Why open it |
|---|---|---|
| `run_job`, `build_server`, `resolve_call_session_id` | `apps/voice-agent/src/voice_agent/main.py` | LiveKit entry, architecture switch, SIP claim, lifecycle |
| `assemble_instructions`, `build_agent_tools`, `capability_tool`, `handoff_tool` | `apps/voice-agent/src/voice_agent/main.py` | prompt + tools |
| `create_agent_session` | `apps/voice-agent/src/voice_agent/providers.py` | cascade construction |
| `create_realtime_session` | `apps/voice-agent/src/voice_agent/providers.py` | full Realtime construction |
| `create_half_cascade_session` | `apps/voice-agent/src/voice_agent/providers.py` | half-cascade construction |
| `_create_stt`, `_create_tts`, `_realtime_options`, `_realtime_transcription`, `_realtime_turn_detection`, `llm_behavior_options` | `apps/voice-agent/src/voice_agent/providers.py` | provider/model adapter behavior |
| `LocalVadCommitController`, `LocalVadCommitSTT` | `apps/voice-agent/src/voice_agent/stt_endpointing.py` | cascade STT commit/endpointing |
| `LatencyInstrumentedAgent`, `VoiceMetrics` | `apps/voice-agent/src/voice_agent/observability.py` | existing production telemetry / sidecar handling |
| `RecentTranscriptBuffer`, `recent_transcript_tool` | `apps/voice-agent/src/voice_agent/recent_transcript.py` | name/spelling lexical sidecar |
| `role_for_architecture` | `apps/voice-agent/src/voice_agent/stt_role.py` | primary vs observer STT role |
| `ConversationPersistence`, `message_from_event` | `apps/voice-agent/src/voice_agent/event_delivery.py` | transcript persistence |
| `HandoffController` | `apps/voice-agent/src/voice_agent/handoff.py` | human transfer lifecycle |
| `RuntimeResolver.resolve_state`, `_cascade`, `_realtime`, `_half_cascade` | `apps/control-plane-service/src/control_plane/application/runtime_resolver.py` | architecture/provider resolution |
| `ExecutionMaterializationService._target_state`, `_voice_runtime`, `runtime_secret`, `voice_context` | `apps/control-plane-service/src/control_plane/application/execution_materialization.py` | immutable execution snapshot + secrets |
| `CallSessionService.claim_inbound_sip`, `get_runtime_context`, `transfer_to_human` | `apps/backend/src/backend_core/modules/calls/service.py` | call/runtime/handoff backend path |
| `CapabilityInvocationService` | `apps/backend/src/backend_core/runtime/capabilities/service.py` | action invocation/outbox/result |
| `CapabilityWorker`, `_bind_input`, `HttpExecutionHandler` | `apps/job-worker/src/job_worker/worker.py` | integration jobs + phone normalization |
| `FinalizationService._transcript` | `apps/backend/src/backend_core/runtime/finalization/service.py` | post-call transcript |
| `VoiceExecutionContext`, `WorkerExecutionContext`, `RuntimeSecretSlot` | `packages/contracts/src/contracts/` | shared runtime contracts |

---

## 18. BENCHMARK ARTIFACT INDEX

### 18.1 Consolidated snapshots

- `benchmarks/results/2026-09-24T150504Z/benchmark_summary.md`
- `benchmarks/results/2026-09-24T150504Z/benchmark_summary.json`
- `benchmarks/results/2026-09-24T152653Z/cascade_openai_fast_comparison.md`
- `benchmarks/results/2026-09-24T152653Z/cascade_openai_fast_comparison.json`

### 18.2 Raw suite artifacts

- STT: `benchmarks/stt/artifacts/2026-09-24T145535Z`
- TTS: `benchmarks/tts/artifacts/2026-09-24T145327Z`
- Network: `benchmarks/network/artifacts/2026-09-24T145328Z`
- Cascade Azure: `benchmarks/pipeline/cascade/artifacts/2026-09-24T145629Z`
- Cascade OpenAI Fast: `benchmarks/pipeline/cascade/artifacts/2026-09-24T151752Z`
- Realtime: `benchmarks/pipeline/realtime/artifacts/2026-09-24T145329Z`
- Half-cascade: `benchmarks/pipeline/half_cascade/artifacts/2026-09-24T145624Z`

---

## 19. QUICK SEARCH INDEX

| Search | Go to |
|---|---|
| `CALL DASHBOARD` / `VIKTOR` | §00, §16 |
| `CASCADE` | §02, §05, §06 |
| `REALTIME` | §03, §05 |
| `HALF-CASCADE` | §04, §05, §06 |
| `STT` / `SCRIBE` | §02, §05.2, §12 |
| `TTS` / `ELEVENLABS` | §02, §04, §05.3, §06 |
| `TOKENIZER` / `STREAMING` | §02.4, §06 |
| `AZURE` / `OPENAI FAST` | §02, §05.4, §07, §08 |
| `NETWORK` / `REGION` / `GEOGRAPHY` | §07–08 |
| `PROMPT` / `TOOLS` / `CONTROL PLANE` | §09–10 |
| `LIVEKIT` / `TELNYX` / `SIP` | §11 |
| `SLOVAK` / `CZECH` / `NAME` / `PHONE` | §12 |
| `EOU` / `BARGE-IN` / `INTERRUPTION` | §13 |
| `LIMITATION` / `METHODOLOGY` | §14 |
| `OPEN QUESTION` | §15 |
| `FILE` / `CLASS` / `FUNCTION` | §17 |

---

## 20. DOCUMENT CONFLICTS / STALE REFERENCES

1. `docs/livekit-voice.md` describes an older `VoiceRuntimeRevision` / environment-selected Azure deployment path. Current `RuntimeResolver` + `ExecutionMaterializationService` are the authority for active runtime configuration.
2. Current `providers.py` still passes Realtime input-transcription configuration while standalone STT also runs as a sidecar. Do not describe Realtime input transcription as universally disabled.
3. Benchmark `configured_region` fields include placeholders for some providers. Treat benchmark-region metadata as benchmark metadata, not production deployment proof.
4. Published tenant prompt, tools, model, voice, tokenizer, policy and exact deployment values are runtime-provided and were not available in the checkout used to prepare the source briefing.

---

## 21. ONE-MINUTE PRE-CALL RECAP

If there is only one minute before the call, remember:

- **STT is ~200 ms post-speech; TTS is ~170–230 ms first audio.** They are not currently the multi-second bottleneck.
- **Model generation is the dominant measured synthetic delay.**
- **Direct OpenAI Fast cascade improved synthetic median by 463 ms**, but provider+tier are confounded.
- **Cascade is not overlapping LLM→TTS effectively in this fixture**: only 3–4/30 early TTS starts; direct Fast loses ~414 ms between first text and first speakable chunk.
- **Half-cascade overlaps well**: 29/29 successful runs started TTS before model completion; TTS itself adds only ~167 ms after start.
- **Realtime synthetic first audio is ~2.86 s**, but its benchmark input method is not production-like EOU.
- **Production EOU, LiveKit/SIP/Telnyx and caller-audible latency are unknown.**
- Viktor's **<500 ms** claim is only meaningful after he defines timestamps, transport, percentile and exact model stack.
