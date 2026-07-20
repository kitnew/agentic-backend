# LiveKit voice turn tuning

Backend Core resolves one immutable `VoiceTurnConfig` for each new LiveKit call:

```text
typed recommended defaults < tenant voice.turn < gated debug turn_overrides
```

All human-facing durations are milliseconds. The worker converts them to seconds only at the LiveKit or ElevenLabs SDK call. Preemptive generation and preemptive TTS are fixed off.

The debug page exposes the four groups directly: speech detection, turn completion, interruptions, and STT segmentation. Enable `VOICE_TURN_DEBUG_OVERRIDES_ENABLED=true`, change individual fields, and start a new LiveKit call. The returned `turn_config` is the immutable active-call snapshot; changing controls never mutates a running call.

The previous `VOICE_LIVEKIT_*` turn variables were removed. ElevenLabs 1.6.5 forwards `vad_silence_threshold_secs`, `vad_threshold`, `min_speech_duration_ms`, and `min_silence_duration_ms` without clamping. Backend validation therefore rejects an STT probability threshold outside `(0, 1]` before dispatch.
