# Standalone benchmark snapshot

Created: 2026-09-24T15:07:28.534609+00:00. All latency values are milliseconds, median/p90 unless stated.

## Execution

| Suite | Provider/model | Measured | Success | Failure | Artifact |
|---|---|---:|---:|---:|---|
| stt | elevenlabs / scribe_v2_realtime | 30 | 30 | 0 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/stt/artifacts/2026-09-24T145535Z` |
| tts | elevenlabs / eleven_v3_conversational | 90 | 90 | 0 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/tts/artifacts/2026-09-24T145327Z` |
| network | multiple / — | 480 | 480 | 0 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/network/artifacts/2026-09-24T145328Z` |
| cascade | multiple / gpt-5.6-terra | 30 | 30 | 0 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/cascade/artifacts/2026-09-24T145629Z` |
| realtime | azure_openai / gpt-realtime-2.1 | 30 | 30 | 0 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/realtime/artifacts/2026-09-24T145329Z` |
| half_cascade | azure_openai+elevenlabs / gpt-realtime-2.1 | 30 | 29 | 1 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/half_cascade/artifacts/2026-09-24T145624Z` |

## STT

Scribe paced 50 ms chunks, 9.5335 s mono 24 kHz PCM16 fixture. First partial: 2422/2847; request start → final: 10114/10821; logical audio end → final: 194/253. N=30.

## TTS

| Text | First audio | Completion | N |
|---|---:|---:|---:|
| short | 170/228 | 377/431 | 30 |
| normal | 172/208 | 756/825 | 30 |
| long | 161/176 | 1718/1825 | 30 |

Audio duration and real-time factor were unavailable from the streamed MP3 probe.

## Network/setup

| Target | Useful boundary | Median/p90 | Min/max | N |
|---|---|---:|---:|---:|
| azure_llm | dns | 3/11 | 2/84 | 30 |
| azure_llm | tcp | 21/34 | 19/46 | 30 |
| azure_llm | tls | 172/370 | 95/515 | 30 |
| azure_llm | cold HTTP HEAD | 143/234 | 116/589 | 30 |
| azure_llm | reused HTTP HEAD | 29/55 | 23/140 | 30 |
| azure_realtime | dns | 3/14 | 2/43 | 30 |
| azure_realtime | tcp | 21/32 | 17/52 | 30 |
| azure_realtime | tls | 233/416 | 76/795 | 30 |
| openai_llm | dns | 2/6 | 2/23 | 30 |
| openai_llm | tcp | 5/15 | 3/83 | 30 |
| openai_llm | tls | 114/341 | 26/358 | 30 |
| openai_llm | cold HTTP HEAD | 268/404 | 185/598 | 30 |
| openai_llm | reused HTTP HEAD | 204/259 | 137/351 | 30 |
| openai_realtime_websocket | websocket_connect | 665/1038 | 519/1650 | 30 |
| elevenlabs | dns | 2/2 | 1/2 | 30 |
| elevenlabs | tcp | 10/11 | 10/12 | 30 |
| elevenlabs | tls | 41/52 | 32/77 | 30 |
| elevenlabs | cold HTTP HEAD | 179/202 | 171/965 | 30 |
| elevenlabs | reused HTTP HEAD | 138/164 | 133/176 | 30 |
| livekit | dns | 2/7 | 1/11 | 30 |
| livekit | tcp | 24/35 | 22/1041 | 30 |
| livekit | tls | 226/459 | 61/776 | 30 |
| backend | dns | 2/8 | 1/11 | 30 |
| backend | tcp | 23/30 | 21/92 | 30 |
| backend | tls | 116/449 | 47/968 | 30 |
| backend | cold HTTP HEAD | 125/339 | 81/1201 | 30 |
| backend | reused HTTP HEAD | 28/47 | 25/106 | 30 |
| azure_realtime_websocket | websocket_connect | 348/601 | 191/652 | 30 |

DNS, TCP, TLS, and HTTP fields remain separately available in the network suite artifacts. HTTP HEAD can return an authorization or route error and still time setup.

## Synthetic pipeline stages

| Architecture | Stage | Median/p90 | N |
|---|---|---:|---:|
| cascade | Audio end → STT final | 210/270 | 30 |
| cascade | STT final → LLM start | 0/0 | 30 |
| cascade | LLM start → first token | 2925/3915 | 30 |
| cascade | LLM start → first speakable | 2967/3951 | 30 |
| cascade | TTS start → first audio | 225/298 | 30 |
| cascade | Audio end → first TTS audio | 3644/4534 | 30 |
| realtime | Input end → response.created | 148/340 | 30 |
| realtime | Input end → first text | 2599/3719 | 30 |
| realtime | Input end → first audio | 2857/3973 | 30 |
| half_cascade | Input end → response.created | 151/398 | 29 |
| half_cascade | Input end → first text | 2928/4085 | 29 |
| half_cascade | Input end → first word | 2952/4114 | 29 |
| half_cascade | TTS start → first audio | 167/215 | 29 |
| half_cascade | Input end → first TTS audio | 3096/4306 | 29 |

TTS began before model completion in 4/30 cascade runs and 29/29 half-cascade runs. Cascade's sentence tokenizer generally flushed its first chunk at model completion for this fixture and prompt.

## Direct synthetic comparison

| Architecture | Input end → first output audio median | p90 | N |
|---|---:|---:|---:|
| cascade | 3644 | 4534 | 30 |
| realtime | 2857 | 3973 | 30 |
| half_cascade | 3096 | 4306 | 29 |

Cascade uses real-time-paced STT and a sentence tokenizer (20 characters used; published value unavailable). Realtime and half-cascade burst-upload audio and manually commit; half-cascade uses the Eleven v3 default word-token boundary. These input-end boundaries and TTS paths differ, so the table is directional rather than a controlled architecture comparison. None includes LiveKit, SIP, PSTN, playout, or caller-audible latency.

## Failures

- half_cascade: 1 measured failures; types: RuntimeError; detail: {'type': 'failed', 'error': {'type': 'server_error', 'code': 'first_output_timeout', 'message': 'Request timed out waiting for first output'}}.
