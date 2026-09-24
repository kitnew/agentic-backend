"""Feed model deltas through the same LiveKit sentence tokenizer used by ElevenLabs TTS."""

import asyncio
import time

from livekit.agents import tokenize


class FirstChunkTTS:
    def __init__(self, synthesize, *, min_sentence_chars: int = 20):
        self.stream = tokenize.blingfire.SentenceTokenizer(
            min_sentence_len=min_sentence_chars
        ).stream()
        self.synthesize = synthesize
        self.first_speakable_ns = None
        self.tts_start_ns = None
        self.tts_result = None
        self._tts_task = None
        self._consumer = asyncio.create_task(self._consume())

    def push(self, text: str, _: int) -> None:
        self.stream.push_text(text)

    async def _consume(self) -> None:
        async for token in self.stream:
            if self._tts_task is None:
                self.first_speakable_ns = time.perf_counter_ns()
                self.tts_start_ns = time.perf_counter_ns()
                self._tts_task = asyncio.create_task(self.synthesize(token.token))

    async def finish(self):
        self.stream.end_input()
        await self._consumer
        if self._tts_task is not None:
            self.tts_result = await self._tts_task
        await self.stream.aclose()
        return self.tts_result
