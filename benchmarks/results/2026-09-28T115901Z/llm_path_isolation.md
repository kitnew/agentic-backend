# LLM path isolation

All values are median / p90 across measured runs in milliseconds unless marked as tokens. T0 is entry to the benchmark variant; T2 is the SDK chat.completions.create invocation; T4 is the first ChatCompletionChunk; T5 is its first nonempty content delta; T6 is first LiveKit text chunk when applicable; T7 is first text observed by benchmark code. The SDK stream is opened at T3. Existing direct request construction occurs inside request(), so T1 and build time are unavailable for those variants.

| Variant | Success | Pre-invoke | Build | Send → event | Send → text | Send → LiveKit text | LiveKit buffer | Consumer TTFT | Input tokens | Cached tokens | Reasoning tokens | Requested → returned tier | Tools | History |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| STANDALONE_EXISTING | 20 | 1 / 7 | unavailable | 868 / 1226 | 870 / 1234 | unavailable | unavailable | 873 / 1235 | 7327 / 7327 | 7324 / 7324 | 0 / 0 | fast → priority | 0 | 0 |
| DIRECT_CASCADE_PAYLOAD | 20 | 1 / 2 | unavailable | 1924 / 3533 | 1932 / 3535 | unavailable | unavailable | 1935 / 3536 | 7346 / 7346 | 7343 / 7343 | 100 / 261 | fast → priority | 0 | 0 |
| LIVEKIT_LLM_DIRECT | 20 | 3 / 6 | 0 / 0 | 2122 / 2553 | 2132 / 2558 | 2133 / 2559 | 1 / 8 | 2138 / 2561 | 7346 / 7346 | 7343 / 7343 | 129 / 171 | fast → priority | 0 | 0 |
| CASCADE_LLM_EXISTING | 20 | 1 / 6 | unavailable | 1839 / 2698 | 1856 / 2703 | unavailable | unavailable | 1858 / 2705 | 7346 / 7346 | 7343 / 7343 | 110 / 178 | fast → priority | 0 | 0 |

## Payload matrix

| Variant | API | Prompt hash | User hash | Max tokens | Tools | History | Reasoning parameter | Tier |
|---|---|---|---|---:|---:|---:|---|---|
| STANDALONE_EXISTING | chat.completions | `87143604bc17` | `a450ddd246a3` | 128 | 0 | 0 | omitted | fast |
| DIRECT_CASCADE_PAYLOAD | chat.completions | `ea2c872f635d` | `1eb9c060620a` | 512 | 0 | 0 | omitted | fast |
| LIVEKIT_LLM_DIRECT | chat.completions | `ea2c872f635d` | `1eb9c060620a` | 512 | 0 | 0 | omitted | fast |
| CASCADE_LLM_EXISTING | chat.completions | `ea2c872f635d` | `1eb9c060620a` | 512 | 0 | 0 | omitted | fast |

## Interpretation

Standalone and synthetic cascade both call the raw OpenAI AsyncOpenAI Chat Completions endpoint. DIRECT_CASCADE_PAYLOAD and CASCADE_LLM_EXISTING use the same effective request. LIVEKIT_LLM_DIRECT uses the same API family and textual payload, with a LiveKit User-Agent header and per-call timeout. The historical standalone shape differs in user text, one trailing prompt byte, and max_completion_tokens (128 versus 512). There are no tools or history in these synthetic paths. Reasoning effort is omitted, so provider default applies; zero reasoning tokens must be established from usage rather than interpreted from None alone.
The interleaved variants reuse one AsyncOpenAI client and HTTP transport. SDK serialization was checked offline with a mock transport: omitted reasoning_effort is absent from the JSON body; explicit none is serialized as `"reasoning_effort": "none"` (sdk_serialization.json). Both primary prompt prefixes are more than 99.9% cached, and every observed returned tier is priority despite requesting fast.

## Controlled output-cap A/B

Identical cascade prompt, transcript, model, cache key, tier, SDK, and execution window; only max_completion_tokens changes.

| Cap | Consumer TTFT median / p90 ms | First event median / p90 ms | Reasoning tokens median / p90 |
|---:|---:|---:|---:|
| 128 (3/10 text responses) | 1572 / 1819 | 1570 / 1795 | 95 / 102 |
| 512 (10/10 text responses) | 2070 / 2465 | 2056 / 2454 | 102 / 147 |

## Controlled User text A/B

| Variant | Text responses | Consumer TTFT median / p90 ms | First event median / p90 ms | Reasoning tokens median / p90 |
|---|---:|---:|---:|---:|
| standalone_user | 10/10 | 1099 / 1448 | 1084 / 1445 | 24 / 49 |
| cascade_user | 10/10 | 1973 / 3133 | 1968 / 3120 | 116 / 202 |

## Controlled Reasoning setting A/B

| Variant | Text responses | Consumer TTFT median / p90 ms | First event median / p90 ms | Reasoning tokens median / p90 |
|---|---:|---:|---:|---:|
| reasoning_omitted | 10/10 | 2163 / 2744 | 2158 / 2738 | 116 / 202 |
| reasoning_none | 10/10 | 923 / 1041 | 910 / 1021 | 0 / 0 |

## Root-cause classification

Case A (request shape): the primary same-window gap is 984 ms (1858 minus 873). The provider's first event accounts for nearly all of it. Direct cascade payload and the existing cascade stage cluster together; LiveKit emits normalized text within milliseconds of provider text. Case B/C/D/E are unsupported by these measurements.

Within an otherwise identical cascade request, explicit reasoning_effort=none reduces median consumer TTFT by 1240 ms (2163 to 923), and reasoning-token usage becomes zero. The original omitted parameter permits provider-default reasoning. The historical 700–800 versus 2200 ms gap was measured in separate windows; this experiment explains its mechanism but cannot assign every historical millisecond without a paired historical run.

Recommended production evaluation: test an explicit no-reasoning deployment setting on the relevant model and assess response quality before rollout. Do not reduce max_completion_tokens to 128 for the cascade transcript: seven of ten measured requests in the cap A/B produced no text.

