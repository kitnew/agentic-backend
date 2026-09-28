"""Signed timing and prefix measurements for Soniox's LiveKit preflights."""

import re


def normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold(), re.UNICODE))


def equivalent(first: str, second: str) -> bool:
    """LiveKit 1.8.2 compares case-folded words while ignoring punctuation."""
    from livekit.agents.tokenize.basic import split_words

    def words(text):
        return [
            word.casefold()
            for word, _, _ in split_words(
                text, ignore_punctuation=True, split_character=True
            )
        ]

    return bool(words(first)) and words(first) == words(second)


def metrics(preflights: list[dict], final: str, audio_end_ms: float) -> dict:
    usable = [item for item in preflights if normalize(item["text"])]
    first, latest = (usable[0], usable[-1]) if usable else (None, None)
    final_words = normalize(final).split()
    first_words = normalize(first["text"]).split() if first else []
    prefix = 0
    for left, right in zip(first_words, final_words, strict=False):
        if left != right:
            break
        prefix += 1
    lead = audio_end_ms - first["elapsed_ms"] if first else None
    return {
        "first_preflight_ms": first["elapsed_ms"] if first else None,
        "preflight_lead_time_ms": lead,
        "preflight_before_audio_end": lead > 0 if lead is not None else False,
        "preflight_count": len(usable),
        "preflight_replacement_count": max(0, len(usable) - 1),
        "preflight_text": first["text"] if first else None,
        "preflight_character_count": len(first["text"]) if first else 0,
        "preflight_word_count": len(first_words),
        "preflight_normalized_text": normalize(first["text"]) if first else None,
        "final_character_count": len(final),
        "final_word_count": len(final_words),
        "preflight_char_fraction": len(first["text"]) / len(final)
        if first and final
        else None,
        "preflight_word_fraction": len(first_words) / len(final_words)
        if first and final_words
        else None,
        "first_preflight_prefix_matches_final": final_words[: len(first_words)]
        == first_words
        if first
        else None,
        "first_preflight_normalized_prefix_length": prefix,
        "first_preflight_token_prefix_accuracy": prefix / len(first_words)
        if first_words
        else None,
        "latest_preflight_prefix_matches_final": final_words[
            : len(normalize(latest["text"]).split())
        ]
        == normalize(latest["text"]).split()
        if latest
        else None,
    }


def aggregate(rows: list[dict]) -> dict:
    measured = [row for row in rows if not row.get("warmup")]
    successful = [row for row in measured if row.get("status") == "ok"]
    with_preflight = sum(row.get("preflight_count", 0) > 0 for row in successful)
    early = sum(bool(row.get("preflight_before_audio_end")) for row in successful)
    return {
        "runs_with_preflight": with_preflight,
        "runs_with_preflight_before_audio_end": early,
        "percentage_with_early_preflight": 100 * early / len(successful)
        if successful
        else None,
        "final_transcript_non_empty_rate": sum(
            bool(row.get("transcript", "").strip()) for row in successful
        )
        / len(successful)
        if successful
        else None,
    }
