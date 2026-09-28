# Soniox / Preemptive Generation Benchmark

## Execution

Measurements are median / p90 in ms. N/A means no measured run was available.

| Suite | Measured success / attempts | Artifact |
|---|---:|---|
| scribe | 30 / 30 | /home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/stt/artifacts/2026-09-24T145535Z |
| scribe_cascade | 30 / 30 | /home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/cascade/artifacts/2026-09-24T151752Z |
| soniox_stt | 30 / 30 | benchmarks/stt/artifacts/2026-09-28T101308Z |
| soniox_cascade | 33 / 33 | benchmarks/pipeline/cascade/artifacts/2026-09-28T101829Z |
Soniox cascade planned 30 measured runs per variant; completed soniox_baseline 11, soniox_preemptive_llm 11, soniox_preemptive_llm_tts 11. The run was interrupted for provider-token diagnosis.

## STT Provider Comparison

| Metric | ElevenLabs Scribe | Soniox |
|---|---:|---:|
| Connection setup | 205 / 470 | 336 / 405 |
| First partial | 2422 / 2847 | 2087 / 2104 |
| Audio end → final | 194 / 253 | -117 / -102 |
| First usable preflight | N/A | N/A |
| Signed preflight lead | N/A | N/A |
| Early preflight rate | N/A | 0.0% |
| Preflight word fraction | N/A | N/A |
| Final nonempty / successes | 30 / 30 | 30 / 30 |
| Failures | 0 | 0 |

## Soniox Preflight Timing

Early preflights: 0 / 30 successful runs. Signed lead: N/A ms.

## Preflight Stability

Preflight count: 0 / 0; replacements: 0 / 0; first-token prefix accuracy: N/A.
Token prefix accuracy is the longest common normalized leading-token sequence divided by the first preflight's token count; it is not WER.

## Provider Token Diagnostic

One diagnostic run recorded 35 provider messages: 3 with final tokens, 33 with provisional tokens, 1 with endpoint tokens, and 0 satisfying the installed plugin's preflight condition.
LiveKit Soniox 1.8.2 emits PREFLIGHT_TRANSCRIPT only when accumulated final text remains after processing a message and that message has no provisional text. A final-plus-provisional message stays interim; an endpoint in the final message clears the accumulated text before the preflight check.

## Cascade Comparison

| Variant | Audio end → first synthesized byte | Audio end → first speakable |
|---|---:|---:|
| Scribe current baseline | 3181 / 4242 | N/A |
| soniox_baseline | 2163 / 2944 | 1860 / 2759 |
| soniox_preemptive_llm | 2295 / 2998 | 2067 / 2765 |
| soniox_preemptive_llm_tts | 2270 / 3076 | 2057 / 2844 |

## Speculative LLM Behavior

soniox_baseline: reuse 0/11, invalidations 0, restarts 0, started LLM work before audio end 0 / 0 ms, reused work 0 / 0 ms.
soniox_preemptive_llm: reuse 0/11, invalidations 0, restarts 0, started LLM work before audio end 0 / 0 ms, reused work 0 / 0 ms.
soniox_preemptive_llm_tts: reuse 0/11, invalidations 0, restarts 0, started LLM work before audio end 0 / 0 ms, reused work 0 / 0 ms.

## Preemptive TTS Behavior

Preemptive LLM + TTS: speculative synthesis start N/A ms from run start; first speculative byte N/A ms; audio end → eligible-first-audio lower bound 2270 / 3076 ms.
Speculative TTS start/first bytes are recorded separately. The eligible-first-audio value is only a lower bound: max(first bytes, turn commit), not measured playout.

## Failures

See each run's errors.jsonl for failure types and counts.

## Interpretation

On this fixture Soniox emitted no preflight in 30/30 runs, so the preemptive variants have no event on which to start speculation. The provider token trace explains why; any small difference between partial cascade variants is run variability, not measured preemptive benefit. This does not establish the cause of the live call's subjective timing.

## Limitations

This is a synthetic/provider benchmark, not production E2E. It omits Telnyx/SIP/PSTN, caller-audible timing, and production LiveKit media playout. The fixed audio fixture may not represent natural conversational turns; local VAD and real-call EOU may differ. Speculative TTS synthesis is not automatically audible output. These results do not prove subjective UX improvement.

## Artifact Paths

- scribe: /home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/stt/artifacts/2026-09-24T145535Z
- scribe_cascade: /home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/cascade/artifacts/2026-09-24T151752Z
- soniox_stt: benchmarks/stt/artifacts/2026-09-28T101308Z
- soniox_cascade: benchmarks/pipeline/cascade/artifacts/2026-09-28T101829Z
- soniox_diagnostic: benchmarks/stt/artifacts/2026-09-28T102915Z
