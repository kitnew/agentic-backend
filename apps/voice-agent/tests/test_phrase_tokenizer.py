import pytest
from livekit.agents import tokenize
from voice_agent.phrase_tokenizer import PhraseTokenizer


@pytest.mark.asyncio
async def test_phrase_stream_emits_qualified_punctuation_and_flushes_remainder() -> (
    None
):
    stream = PhraseTokenizer(10).stream()
    stream.push_text("Dobrý deň,")
    assert (await stream.__anext__()).token == "Dobrý deň,"
    stream.push_text(" preverím dostupnosť.")
    assert (await stream.__anext__()).token == "preverím dostupnosť."
    stream.end_input()
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


@pytest.mark.asyncio
async def test_phrase_stream_holds_short_punctuation_and_partial_words() -> None:
    stream = PhraseTokenizer(10).stream()
    stream.push_text("Dobr")
    stream.push_text("ý,")
    stream.push_text(" áno")
    stream.push_text(";")
    assert (await stream.__anext__()).token == "Dobrý, áno;"
    stream.end_input()
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()


@pytest.mark.asyncio
@pytest.mark.parametrize("punctuation", [";", ":", ".", "?", "!"])
async def test_phrase_stream_emits_natural_boundaries(punctuation: str) -> None:
    stream = PhraseTokenizer(3).stream()
    stream.push_text(f"Áno{punctuation}")
    assert (await stream.__anext__()).token == f"Áno{punctuation}"
    stream.end_input()


def test_phrase_tokenize_keeps_order_and_flushes_final_text() -> None:
    assert PhraseTokenizer(10).tokenize("Dobrý deň, preverím dostupnosť.") == [
        "Dobrý deň,",
        "preverím dostupnosť.",
    ]
    assert PhraseTokenizer(10).tokenize("Dobr") == ["Dobr"]


def test_sentence_tokenizer_remains_the_livekit_default() -> None:
    from livekit.agents.tokenize.blingfire import SentenceTokenizer

    assert isinstance(
        SentenceTokenizer(min_sentence_len=20), tokenize.SentenceTokenizer
    )
