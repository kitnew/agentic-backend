"""Benchmark-only Soniox final-token to LiveKit preflight mapping."""

from math import ceil
from time import perf_counter_ns

from livekit.agents import stt
from livekit.agents.language import LanguageCode

from benchmarks.stt.preflight import normalize


class StableFinalPrefix:
    def __init__(self, stream, start_ns: int):
        self.stream = stream
        self.start_ns = start_ns
        self.final_text = ""
        self.last_emitted = ""
        self.endpointed = False
        self.audio_end_ns = None
        self.events: list[dict] = []

    def observe(self, tokens: list[dict], _received_ns: int) -> None:
        if self.endpointed:
            return
        new_final = [
            token["text"]
            for token in tokens
            if token.get("is_final") and token.get("text") not in ("<end>", "<fin>")
        ]
        provisional = "".join(
            token["text"] for token in tokens if not token.get("is_final")
        )
        endpoint = any(
            token.get("is_final") and token.get("text") in ("<end>", "<fin>")
            for token in tokens
        )
        self.final_text += "".join(new_final)
        if endpoint:
            self.endpointed = True
            return
        if (
            not new_final
            or not normalize(self.final_text)
            or self.final_text == self.last_emitted
        ):
            return
        self.last_emitted = self.final_text
        emitted_ns = perf_counter_ns()
        text = self.final_text
        self.events.append(
            {
                "timestamp_ms": (emitted_ns - self.start_ns) / 1e6,
                "stable_prefix_text": text,
                "stable_prefix_words": len(normalize(text).split()),
                "stable_prefix_chars": len(text),
                "new_final_tokens": new_final,
                "provisional_tail_text": provisional,
                "_emitted_ns": emitted_ns,
            }
        )
        self.stream._event_ch.send_nowait(
            stt.SpeechEvent(
                type=stt.SpeechEventType.PREFLIGHT_TRANSCRIPT,
                alternatives=[stt.SpeechData(language=LanguageCode("sk"), text=text)],
            )
        )

    def finish(self, final_text: str) -> list[dict]:
        final_words = normalize(final_text).split()
        for event in self.events:
            at_ns = event.pop("_emitted_ns")
            relative = (
                (at_ns - self.audio_end_ns) / 1e6
                if self.audio_end_ns is not None
                else None
            )
            event["preflight_relative_to_audio_end_ms"] = relative
            event["preflight_lead_ms"] = -relative if relative is not None else None
            words = normalize(event["stable_prefix_text"]).split()
            matching = 0
            for left, right in zip(words, final_words, strict=False):
                if left != right:
                    break
                matching += 1
            event["is_exact_token_prefix_of_final"] = final_words[: len(words)] == words
            event["is_character_prefix_of_final"] = final_text.startswith(
                event["stable_prefix_text"]
            )
            event["longest_common_token_prefix"] = matching
            event["complete_final_word_count"] = matching
            event["ends_inside_final_word"] = event[
                "is_character_prefix_of_final"
            ] and matching < len(words)
            event["prefix_token_accuracy"] = matching / len(words)
        return self.events


def threshold_leads(events: list[dict], final_text: str) -> dict:
    final_words = len(normalize(final_text).split())
    thresholds = {f"words_{count}": count for count in (1, 3, 5, 8)}
    thresholds.update(
        {
            f"fraction_{percent}": ceil(final_words * percent / 100)
            for percent in (25, 50, 75)
        }
    )
    return {
        name: next(
            (
                event["preflight_lead_ms"]
                for event in events
                if event["complete_final_word_count"] >= count
            ),
            None,
        )
        for name, count in thresholds.items()
    }
