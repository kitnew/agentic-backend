# Soniox stable-final-prefix preflight experiment

Source: `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/cascade/artifacts/2026-09-28T110827Z`. Synthetic/provider benchmark on the GLOBAL endpoint; 30 measured and 2 warmup runs per variant. Values are median / p90 in ms unless noted.

## Controlled comparison

| Metric | Stock preemptive LLM | Stable prefix + LLM | Stable prefix + LLM + TTS |
|---|---:|---:|---:|
| Success / attempts | 30 / 30 | 30 / 30 | 30 / 30 |
| Preflight rate | 0.0% | 100.0% | 100.0% |
| Early preflight rate | 0.0% | 100.0% | 100.0% |
| Preflights / turn | 0 / 0 | 2 / 2 | 2 / 2 |
| First raw preflight lead | N/A | 3364 / 3372 | 3367 / 3385 |
| First >=5 complete-word lead | N/A | 1284 / 1295 | 1290 / 1297 |
| Final-token batches / turn | 3 / 3 | 3 / 3 | 3 / 3 |
| Provisional frames / turn | 33 / 33 | 33 / 33 | 33 / 33 |
| Speculative attempts / turn | 0 / 0 | 2 / 2 | 2 / 2 |
| Restarts / turn | 0 / 0 | 1 / 1 | 1 / 1 |
| Reuse rate | 0.0% | 0.0% | 0.0% |
| Invalidation rate | 0.0% | 100.0% | 100.0% |
| LLM work before audio end | 0 / 0 | 2153 / 2398 | 2180 / 2476 |
| Reused LLM work before audio end | 0 / 0 | 0 / 0 | 0 / 0 |
| Audio end → first text | 1736 / 2198 | 1486 / 2334 | 1581 / 2430 |
| Audio end → first speakable | 2260 / 2620 | 2069 / 2734 | 2131 / 2972 |
| Audio end → TTS start | 2260 / 2620 | 2069 / 2734 | 2131 / 2972 |
| Audio end → first synthesized byte | 2508 / 2911 | 2325 / 2982 | 2321 / 3178 |

## Stable-prefix thresholds

Thresholds count complete leading words matching the final transcript, excluding a midword fragment. Availability and early rate use successful runs as denominator. Signed lead is audio end minus preflight time; positive means before audio end.

| Threshold | Available | Early | Lead median / p90 |
|---|---:|---:|---:|
| words_1 | 100.0% | 100.0% | 1284 / 1295 |
| words_3 | 100.0% | 100.0% | 1284 / 1295 |
| words_5 | 100.0% | 100.0% | 1284 / 1295 |
| words_8 | 0.0% | 0.0% | N/A |
| fraction_25 | 100.0% | 100.0% | 1284 / 1295 |
| fraction_50 | 0.0% | 0.0% | N/A |
| fraction_75 | 0.0% | 0.0% | N/A |

## Prefix stability and restart pressure

First-prefix token accuracy: 0.00 / 0.00; all-prefix accuracy: 0.43 / 0.86; non-token-prefix events: 60; non-character-prefix events: 0; midword events: 60.
Interval between preflights: 2080 / 2093 ms. Total invalidations: 60.
Prefix token accuracy is the matching leading normalized tokens divided by tokens in that experimental preflight; it is not WER.

## Preemptive TTS

Speculative TTS start: N/A ms from run start; first speculative byte: N/A ms from run start; audio end → eligible-first-audio lower bound: 2321 / 3178 ms.
Synthesis before turn commit is not caller-audible timing. The lower bound uses max(turn commit, first synthesized byte), without playout.

## Interpretation

Cases: D: early prefix, low reuse.
Answer: exposing every stable-final-prefix growth produced early preflights but no demonstrated meaningful latency improvement on this fixture.
Median first-speakable gain versus stock: 192 ms.
Median first synthesized byte gain versus stock: 183 ms.
No speculative attempt was reused, so the modest median latency differences cannot be attributed to reused speculative work. Both experimental preflights ended inside a word on every measured turn. The final transcript differed from the last preflight, requiring a new committed LLM request; preemptive TTS produced no speculative audio. This fixture does not justify a production adapter that emits every stable-prefix growth.

## Failures and limitations

Failure counts appear in the comparison table; details are in errors.jsonl. The synthetic coordinator mirrors LiveKit 1.8.2's three-attempt replacement and transcript reuse rules but is not AgentSession. It assumes fixed context and tools. No production local VAD, LiveKit media playout, Telnyx/SIP/PSTN, or caller-audible timing is measured. One fixed Slovak utterance may not represent natural turns. The result does not prove subjective UX improvement.

## Artifacts

- Raw runs: `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/pipeline/cascade/artifacts/2026-09-28T110827Z`
- JSON: `/home/nikitachernysh/Storage/Projects/agentic-backend/benchmarks/results/2026-09-28T113239Z/soniox_stable_prefix_preflight.json`
