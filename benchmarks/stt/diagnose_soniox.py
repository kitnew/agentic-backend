"""Inspect Soniox token states without persisting provider payloads or credentials."""

import asyncio
import hashlib
import json
import re
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.artifacts import append, create, finish
from common.config import load_env, required
from common.metadata import manifest
from stt.run import measure_soniox


class ObservedSocket:
    def __init__(self, socket, frames, start_ns, on_frame=None):
        self.socket = socket
        self.frames = frames
        self.start_ns = start_ns
        self.final_text = ""
        self.on_frame = on_frame

    def __getattr__(self, name):
        return getattr(self.socket, name)

    async def __aiter__(self):
        import aiohttp

        async for message in self.socket:
            if message.type == aiohttp.WSMsgType.TEXT:
                body = json.loads(message.data)
                tokens = body.get("tokens", [])
                code = body.get("error_code")
                at_ns = time.perf_counter_ns()
                if self.on_frame:
                    self.on_frame(tokens, at_ns)
                provisional = ""
                endpoint_count = 0
                final_count = 0
                nonfinal_count = 0
                for token in tokens:
                    if token.get("text") in ("<end>", "<fin>") and token.get(
                        "is_final"
                    ):
                        endpoint_count += 1
                        self.final_text = ""
                    elif token.get("is_final"):
                        final_count += 1
                        self.final_text += token.get("text", "")
                    else:
                        nonfinal_count += 1
                        provisional += token.get("text", "")
                self.frames.append(
                    {
                        "elapsed_ms": (at_ns - self.start_ns) / 1e6,
                        "final_token_count": final_count,
                        "nonfinal_token_count": nonfinal_count,
                        "endpoint_token_count": endpoint_count,
                        "accumulated_final_char_count": len(self.final_text),
                        "provisional_char_count": len(provisional),
                        "would_emit_preflight": bool(self.final_text)
                        and not provisional,
                        "finished": bool(body.get("finished")),
                        "error_code_present": bool(body.get("error_code")),
                        "error_code": code
                        if isinstance(code, int)
                        or (
                            isinstance(code, str)
                            and re.fullmatch(r"[A-Za-z0-9_]{1,64}", code)
                        )
                        else None,
                    }
                )
            yield message


async def main():
    import os

    config = load_env()
    key = (
        os.environ.get("BENCH_SONIOX_API_KEY") or required(config, "SONIOX_API_KEY")[0]
    )
    region = config.get("SONIOX_REGION", "global")
    audio = Path(__file__).resolve().parents[1] / "fixtures/audio/sk_basic.wav"
    with wave.open(str(audio)) as wav:
        rate = wav.getframerate()
        pcm = wav.readframes(wav.getnframes())
    path = create(
        __file__,
        manifest(
            "soniox_token_diagnostic",
            "soniox",
            "stt-rt-v5",
            None,
            region,
            1,
            0,
            {
                "audio_file": str(audio),
                "audio_sha256": hashlib.sha256(pcm).hexdigest(),
                "sample_rate_hz": rate,
                "chunk_size_ms": 50,
                "stored_provider_data": "token counts and states only, no websocket payloads",
            },
        ),
    )
    frames = []
    row = await measure_soniox(
        key,
        region,
        pcm,
        rate,
        60,
        socket_wrapper=lambda ws, _stream, start_ns: ObservedSocket(
            ws, frames, start_ns
        ),
    )
    row.update(run_index=1, warmup=False, provider_frames=frames)
    append(path, "raw.jsonl", row)
    if row["status"] != "ok":
        append(path, "errors.jsonl", row)
    finish(path, [row])
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
