from __future__ import annotations

from livekit.agents import tokenize

_BOUNDARIES = ",;:.?!"


class PhraseTokenizer(tokenize.SentenceTokenizer):
    def __init__(self, min_phrase_len: int = 10) -> None:
        self._min_phrase_len = min_phrase_len

    def tokenize(self, text: str, *, language: str | None = None) -> list[str]:
        tokens = []
        start = 0
        length = 0
        for index, char in enumerate(text):
            if not char.isspace() or length:
                length += 1
            if char in _BOUNDARIES and length >= self._min_phrase_len:
                if phrase := text[start : index + 1].strip():
                    tokens.append(phrase)
                start = index + 1
                while start < len(text) and text[start].isspace():
                    start += 1
                length = 0
        if phrase := text[start:].strip():
            tokens.append(phrase)
        return tokens

    def stream(self, *, language: str | None = None) -> tokenize.SentenceStream:
        return _PhraseStream(self._min_phrase_len)


class _PhraseStream(tokenize.SentenceStream):
    def __init__(self, min_phrase_len: int) -> None:
        super().__init__()
        self._min_phrase_len = min_phrase_len
        self._buffer = ""

    def push_text(self, text: str) -> None:
        self._check_not_closed()
        self._buffer += text
        start = 0
        length = 0
        for index, char in enumerate(self._buffer):
            if not char.isspace() or length:
                length += 1
            if char in _BOUNDARIES and length >= self._min_phrase_len:
                self._emit(self._buffer[start : index + 1].strip())
                start = index + 1
                while start < len(self._buffer) and self._buffer[start].isspace():
                    start += 1
                length = 0
        self._buffer = self._buffer[start:]

    def flush(self) -> None:
        self._check_not_closed()
        self._emit(self._buffer.strip())
        self._buffer = ""

    def end_input(self) -> None:
        self.flush()
        self._do_close()

    async def aclose(self) -> None:
        self._do_close()

    def _emit(self, text: str) -> None:
        if text:
            self._event_ch.send_nowait(tokenize.TokenData(token=text))
