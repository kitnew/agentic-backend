# LLM to TTS latency

Current measured runs: 20

| Stage | Median ms | P90 ms | N | % total |
|---|---:|---:|---:|---:|
| provider_to_livekit_ms | 5.733655499999999 | 40.061669800000026 | 20 | 1.0138141592664984 |
| livekit_to_tts_receive_ms | 0.1246895 | 0.1949103 | 20 | 0.02204736238719959 |
| tts_receive_to_plugin_ms | 0.0022455 | 0.0027101000000000004 | 20 | 0.00039704507789715 |
| plugin_to_tokenizer_receive_ms | 0.8681544999999999 | 30.726178200000007 | 20 | 0.15350544247573425 |
| livekit_to_tokenizer_ms | 356.09968100000003 | 509.4972528000001 | 20 | 62.96487445192397 |
| tokenizer_receive_to_emit_ms | 340.90851699999996 | 457.7211687000001 | 20 | 60.27880146429164 |
| tokenizer_to_tts_receive_ms | unavailable | unavailable | 0 | unavailable |
| tokenizer_to_websocket_ms | 0.3288355 | 1.4210351000000017 | 20 | 0.058144073352415164 |
| tts_receive_to_websocket_ms | 356.2871755 | 509.6525418000001 | 20 | 62.99802687604233 |
| websocket_to_provider_audio_ms | 152.968363 | 184.42904840000003 | 20 | 27.047577645573153 |
| provider_to_livekit_audio_ms | 70.3492675 | 110.15090870000002 | 20 | 12.43902489180358 |
| llm_text_to_audio_ms | 565.552912 | 735.5059465000002 | 20 | 100.0 |

## Example first turn

First tokenizer output: Dobrý deň, od dvadsiateho piateho do dvadsiateho šiesteho septembra ide o jednu noc; pre koľko osôb bude izba?

| ms from first LiveKit text | Event | Text |
|---:|---|---|
| 0.0 | LLM delta; 1 chars; 1 words | 'D' |
| 1.8 | LLM delta; 4 chars; 1 words | 'obr' |
| 13.3 | LLM delta; 5 chars; 1 words | 'ý' |
| 13.5 | LLM delta; 9 chars; 2 words | ' deň' |
| 35.2 | LLM delta; 10 chars; 2 words | ',' |
| 35.3 | LLM delta; 13 chars; 3 words | ' od' |
| 42.7 | LLM delta; 16 chars; 4 words | ' dv' |
| 42.8 | LLM delta; 18 chars; 4 words | 'ad' |
| 47.1 | LLM delta; 20 chars; 4 words | 'si' |
| 47.2 | LLM delta; 23 chars; 4 words | 'ate' |
| 113.4 | LLM delta; 25 chars; 4 words | 'ho' |
| 116.1 | LLM delta; 27 chars; 5 words | ' p' |
| 116.4 | LLM delta; 31 chars; 5 words | 'iate' |
| 116.6 | LLM delta; 33 chars; 5 words | 'ho' |
| 116.7 | LLM delta; 36 chars; 6 words | ' do' |
| 116.8 | LLM delta; 39 chars; 7 words | ' dv' |
| 116.9 | LLM delta; 41 chars; 7 words | 'ad' |
| 117.0 | LLM delta; 43 chars; 7 words | 'si' |
| 124.3 | LLM delta; 46 chars; 7 words | 'ate' |
| 124.4 | LLM delta; 48 chars; 7 words | 'ho' |
| 130.5 | LLM delta; 51 chars; 8 words | ' ši' |
| 130.6 | LLM delta; 55 chars; 8 words | 'este' |
| 168.6 | LLM delta; 57 chars; 8 words | 'ho' |
| 168.7 | LLM delta; 62 chars; 9 words | ' sept' |
| 195.6 | LLM delta; 67 chars; 9 words | 'embra' |
| 195.7 | LLM delta; 71 chars; 10 words | ' ide' |
| 216.5 | LLM delta; 73 chars; 11 words | ' o' |
| 216.6 | LLM delta; 79 chars; 12 words | ' jednu' |
| 220.3 | LLM delta; 83 chars; 13 words | ' noc' |
| 220.4 | LLM delta; 84 chars; 13 words | ';' |
| 230.7 | LLM delta; 88 chars; 14 words | ' pre' |
| 230.8 | LLM delta; 91 chars; 15 words | ' ko' |
| 235.3 | LLM delta; 92 chars; 15 words | 'ľ' |
| 235.4 | LLM delta; 94 chars; 15 words | 'ko' |
| 247.5 | LLM delta; 97 chars; 16 words | ' os' |
| 247.6 | LLM delta; 98 chars; 16 words | 'ô' |
| 263.7 | LLM delta; 99 chars; 16 words | 'b' |
| 263.8 | LLM delta; 104 chars; 17 words | ' bude' |
| 269.9 | LLM delta; 107 chars; 18 words | ' iz' |
| 270.0 | LLM delta; 109 chars; 18 words | 'ba' |
| 282.8 | LLM delta; 110 chars; 18 words | '?' |
| 327.3 | tokenizer emits | |
| 327.6 | websocket sends | |
| 484.3 | provider audio | |
| 555.5 | LiveKit audio | |

## Scope and configuration

Two warmups and 20 measured CURRENT turns succeeded. The measured path uses the installed `livekit-agents==1.8.2` OpenAI LLM and `livekit-plugins-elevenlabs==1.8.2` streaming TTS, direct OpenAI `gpt-5.6-terra`, requested Fast tier, `reasoning_effort="none"`, the repository's `benchmarks/llm/prompts/production.txt`, the exact transcript saved in the historical cascade raw artifact, `eleven_v3_conversational`, voice `9Nd358gE1qQp0pDh8FgP`, `auto_mode=False`, and `SentenceTokenizer(min_sentence_len=20)`. Hash and full configuration are in JSON. The published production runtime threshold, effective assembled prompt, and voice have not been verified against a live execution snapshot; 20 and the voice are the historical benchmark configuration. The benchmark excludes STT, AgentSession scheduling, output playout and SIP.

## Exact production path from installed source

`providers.create_agent_session` builds `livekit.plugins.openai.LLM`, passes `reasoning_effort` and `service_tier`, and calls `providers._create_tts`. `_create_tts` supplies `tokenize.blingfire.SentenceTokenizer(min_sentence_len=runtime["tts"]["tokenizer"]["min_sentence_chars"])` as ElevenLabs `word_tokenizer` and sets `auto_mode=False` for v3. `LatencyInstrumentedAgent.llm_node` wraps `Agent.default.llm_node`; its `tts_node` wraps `Agent.default.tts_node` and observes first output frame. LiveKit `inference.llm.LLMStream._run` receives OpenAI streamed choices and `_parse_choice` produces `ChatChunk`. `voice.generation._llm_inference_task` sends nonempty text to its channel; `AgentActivity._produce_segments` forwards it to `perform_tts_inference` and `Agent.default.tts_node`. That node calls `elevenlabs.TTS.stream()`, forwards text by `stream.push_text`, and yields `ev.frame`. The ElevenLabs `SynthesizeStream._run` passes input through the supplied sentence tokenizer, queues `_SynthesizeContent`, and `_DialogueConnection._send_loop` sends `inputs[{text,voice_id}]` on the text-to-dialogue websocket. `_DialogueConnection._recv_loop` receives an `audio` field and pushes decoded bytes into `AudioEmitter`, which exposes LiveKit audio frames.

The tokenizer is **inside the ElevenLabs plugin stream**, after LiveKit's TTS node has already received text. Thus a `tokenizer output → TTS receive` interval is not chronologically meaningful and is recorded as unavailable. There is no second LiveKit sentence buffer after this tokenizer; its output reaches the websocket send queue in 0.33 / 1.42 ms median / p90. The benchmark relay measures the LiveKit node input and plugin `push_text` calls, while the source establishes the actual `Agent.default.tts_node` routing. It does not execute an AgentSession.

## Why the first output waits

In the installed `tokenize.blingfire._split_sentences`, `min_sentence_len` is `len(sentence)`: **characters**, after trimming whitespace and normalizing newlines. Spans shorter than 20 characters merge forward. `BufferedTokenStream.push_text` waits for at least 10 buffered characters before tokenizing, and emits only when tokenization returns **more than one span**; it retains the newest span as lookahead. A punctuation mark therefore does not immediately flush. Blingfire must recognize a following sentence candidate, or `flush`/`end_input` must release the remaining buffer. Commas did not release a chunk in the measured turns; neither did the semicolon in the representative turn. `.?!` are subject to Blingfire segmentation and the 20-character minimum, followed by lookahead. Whitespace or later text can be needed for Blingfire to identify the next span. On stream close, `end_input()` calls `flush()` and emits the remainder regardless of the minimum.

In 14/20 runs, the first observed chunk came with input close/flush; 6/20 emitted after a following sentence candidate. This reason is inferred from the captured close and emission timestamps, not an internal tokenizer reason code. First complete word appeared at 13 ms median, first comma at 41 ms, first sentence-ending `.?!…` at 322 ms, and first tokenizer output at 356 ms after first LiveKit text. Paired first punctuation → output was 14 ms median. The dominant 300+ ms before punctuation is model text generation; the tokenizer policy then requires lookahead or stream close. The first complete word existed roughly 311 ms before the first tokenizer output, but the current sentence tokenizer intentionally does not treat that word as a speakable chunk.

In the representative turn above, `Dobrý` was complete at 13 ms, the comma arrived at 35 ms, the semicolon at 220 ms, and the question mark at 283 ms. The LLM finished and the tokenizer flushed at 327 ms; the websocket sent the first full sentence at 328 ms. First ElevenLabs audio arrived at 484 ms; a LiveKit audio frame was exposed at 555 ms.

## Buffering and bypass checks

`SynthesizeStream._run` forwards tokenizer output to `connection.send_content`, which queues it for `_DialogueConnection._send_loop`. With v3 conversational, this is the dialogue websocket; its URL has no `auto_mode` parameter. `auto_mode=False` makes `flush_on_chunk=False`, so ordinary chunks do not carry `flush`; a final empty `flush=True` message is sent when the stream closes. The configured tokenizer is the only plugin text tokenizer. No fixed local text threshold or timer appears after its output. The actual websocket send → first provider audio event is 153 / 184 ms median / p90. First provider audio event → exposed LiveKit frame is 70 / 110 ms, including plugin audio handling and decoding. These are separate from the 356 ms pre-send wait.

The PRE_RECORDED_LLM_STREAM variant replayed a captured real delta stream with recorded cadence through the same tokenizer; its first TTS input → websocket send was 266 ms. The BYPASS_TOKENIZER variant supplied that captured complete phrase through an immediate benchmark-only tokenizer over a preconnected websocket; TTS input → websocket send was 0.95 ms, and send → provider audio was 163 ms. These single-run controls localize the delay; they are not population latency estimates.

## Historical metric and conclusion

The historical `FirstChunkTTS.first_speakable_ns` timestamp marks the first output from a separate benchmark-local `SentenceTokenizer`. It then starts an HTTP ElevenLabs synthesis of only that first token. It was **not** actual `Agent.default.tts_node` receipt, plugin `push_text`, websocket send, or streaming audio. It remains a useful proxy for the first sentence-tokenizer output but was labeled too broadly as the TTS boundary. Its historical ~414 ms direct-Fast gap is also from a different request setting: reasoning effort was omitted there, while this run explicitly sends `none`.

Classification: **combination of LLM generation cadence and sentence-tokenizer emission policy**. The tokenizer holds the early words until a recognized next sentence or close, but there is no measured 300+ ms queue after a complete eligible sentence. Provider/network TTS and audio decoding account for the later 153 and 70 ms median stages. The smallest next experiment is benchmark-only: replay these captured streams through an earlier phrase boundary while holding the same ElevenLabs configuration, and assess the emitted text before any production change.

Stage percentages in the initial table use each stage's median divided by the median first LiveKit text → first LiveKit audio total. Several rows overlap (for example `livekit_to_tokenizer_ms` includes `tokenizer_receive_to_emit_ms`), and medians of separate stages need not sum exactly to the total. `raw.jsonl` contains every delta, tokenizer input/buffer state, emitted token and websocket text event. No credentials or raw websocket audio are persisted.
