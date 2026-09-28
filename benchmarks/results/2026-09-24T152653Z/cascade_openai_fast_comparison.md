# Cascade direct OpenAI fast comparison

Created: 2026-09-24T15:26:53.393885+00:00. Values are median / p90 in ms.

| Variant | LLM provider/model | Requested tier | Returned tier | Success/attempts | Artifact |
|---|---|---|---|---:|---|
| azure_default | multiple / gpt-5.6-terra | default | unavailable | 30/30 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/cascade/artifacts/2026-09-24T145629Z` |
| openai_fast | elevenlabs+openai / gpt-5.6-terra | fast | priority | 30/30 | `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/cascade/artifacts/2026-09-24T151752Z` |

| Measured stage | Azure default | Direct OpenAI fast |
|---|---:|---:|
| Audio end → STT final | 210 / 270 | 214 / 286 |
| LLM start → first text | 2925 / 3915 | 2204 / 3121 |
| LLM start → first tokenizer chunk | 2967 / 3951 | 2618 / 3649 |
| TTS start → first audio | 225 / 298 | 233 / 330 |
| Audio end → first TTS audio | 3644 / 4534 | 3181 / 4242 |

Directly measured median difference: -463 ms (-12.7%) versus the prior Azure cascade run. The number of runs where TTS started before LLM completion was 4/30 for Azure and 3/30 for direct OpenAI.

## Architecture snapshot

| Architecture | First audio median / p90 | N |
|---|---:|---:|
| Cascade Azure default | 3644 / 4534 | 30 |
| Cascade OpenAI fast | 3181 / 4242 | 30 |
| Realtime Azure | 2857 / 3973 | 30 |
| Half-cascade Azure | 3096 / 4306 | 29 |

Provider and service tier changed together, so the difference cannot be attributed to `fast` alone. Cascade used real-time-paced STT; Realtime and half-cascade burst-uploaded the fixture. The architecture rows come from separate runs and do not measure production end-to-end or caller-audible latency.
