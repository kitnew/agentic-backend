"""Feed model deltas through the same LiveKit sentence tokenizer used by ElevenLabs TTS."""

import asyncio
import time

from livekit.agents import tokenize


class FirstChunkTTS:
    def __init__(self, synthesize, *, min_sentence_chars: int | None = 20, gate=None):
        tokenizer = (
            tokenize.blingfire.SentenceTokenizer(min_sentence_len=min_sentence_chars)
            if min_sentence_chars is not None
            else tokenize.basic.WordTokenizer(ignore_punctuation=False)
        )
        self.stream = tokenizer.stream()
        self.synthesize = synthesize
        self.gate = gate
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
                if self.gate is not None:
                    await self.gate.wait()
                self.tts_start_ns = time.perf_counter_ns()
                self._tts_task = asyncio.create_task(self.synthesize(token.token))

    async def finish(self):
        self.stream.end_input()
        await self._consumer
        if self._tts_task is not None:
            self.tts_result = await self._tts_task
        await self.stream.aclose()
        return self.tts_result

    async def aclose(self):
        self._consumer.cancel()
        if self._tts_task is not None:
            self._tts_task.cancel()
        await asyncio.gather(
            *(task for task in (self._consumer, self._tts_task) if task is not None),
            return_exceptions=True,
        )
        await self.stream.aclose()
