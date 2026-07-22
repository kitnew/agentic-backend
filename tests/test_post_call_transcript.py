import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from livekit.agents.llm import ChatContext

from app.tenants.schemas import TenantPostCallTranscriptConfig
from app.voice_agent.post_call import (
    SUMMARY_UNAVAILABLE,
    format_transcript,
    generate_summary,
    persist_post_call,
)


class Stream:
    def __init__(self, chunks=None, error=None):
        self.chunks = iter(chunks or [])
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self

    async def __aexit__(self, *_args):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            content = next(self.chunks)
        except StopIteration:
            raise StopAsyncIteration
        return SimpleNamespace(delta=SimpleNamespace(content=content))


class LLM:
    def __init__(self, chunks=None, error=None):
        self.chunks = chunks
        self.error = error
        self.context = None

    def chat(self, *, chat_ctx):
        self.context = chat_ctx
        return Stream(self.chunks, self.error)


class Sheets:
    def __init__(self, error=None):
        self.error = error
        self.rows = []

    def append_row(self, row):
        if self.error:
            raise self.error
        self.rows.append(row)


def history():
    context = ChatContext()
    context.add_message(role="system", content="tajný systémový prompt")
    context.add_message(role="user", content="  Dobrý deň,\nchcem izbu. ")
    context.items.append(SimpleNamespace(type="function_call", role="assistant"))
    context.add_message(role="assistant", content="Nedokončená odpoveď", interrupted=True)
    context.add_message(role="assistant", content="Žiadosť bola odoslaná.")
    context.add_message(role="user", content="   ")
    return context


def metadata():
    return SimpleNamespace(
        tenant_id="penzion_grand",
        call_session_id=uuid4(),
        conversation_id=uuid4(),
        timezone="Europe/Bratislava",
        post_call_transcript=TenantPostCallTranscriptConfig(
            spreadsheet_id="sheet-id", sheet_name="Transkripty"
        ),
    )


def test_transcript_contains_only_final_readable_user_and_assistant_messages():
    assert format_transcript(history()) == (
        "Hosť: Dobrý deň, chcem izbu.\nAgent: Žiadosť bola odoslaná."
    )


def test_summary_is_a_separate_slovak_llm_request():
    llm = LLM(["Hosť požiadal o izbu. ", "Žiadosť bola odoslaná."])
    result = asyncio.run(generate_summary(llm, "Hosť: Chcem izbu."))
    assert result == "Hosť požiadal o izbu. Žiadosť bola odoslaná."
    prompt = llm.context.messages()[0].raw_text_content
    assert "po slovensky" in prompt
    assert "potvrdenú rezerváciu" in prompt
    assert llm.context.messages()[1].raw_text_content.endswith("Hosť: Chcem izbu.")


def test_post_call_maps_one_row_and_preserves_phone_prefix():
    sheets = Sheets()
    session = SimpleNamespace(history=history(), llm=LLM(["Stručné zhrnutie."]))
    saved = asyncio.run(
        persist_post_call(
            session,
            metadata(),
            "+421900111222",
            completed_at=datetime(2026, 7, 22, 20, 15, tzinfo=timezone.utc),
            sheets=sheets,
        )
    )
    assert saved is True
    assert len(sheets.rows) == 1
    assert sheets.rows[0].sheet_name == "Transkripty"
    assert sheets.rows[0].values == [
        "Hosť: Dobrý deň, chcem izbu.\nAgent: Žiadosť bola odoslaná.",
        "Stručné zhrnutie.",
        "22.07.2026 22:15:00",
        "+421900111222",
    ]


def test_summary_and_sheets_failures_are_logged_without_raising(caplog):
    session = SimpleNamespace(history=history(), llm=LLM(error=RuntimeError("llm down")))
    fallback_sheets = Sheets()
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(
            persist_post_call(session, metadata(), "+421900111222", sheets=fallback_sheets)
        )
        assert not asyncio.run(
            persist_post_call(
                SimpleNamespace(history=history(), llm=LLM(["Zhrnutie."])),
                metadata(),
                "+421900111222",
                sheets=Sheets(error=RuntimeError("sheets down")),
            )
        )
    assert fallback_sheets.rows[0].values[1] == SUMMARY_UNAVAILABLE
    assert "tenant_id=penzion_grand" in caplog.text
    assert "summary generation failed" in caplog.text
    assert "transcript persistence failed" in caplog.text


def test_summary_timeout_uses_fallback_and_does_not_block_row(monkeypatch):
    class HangingStream(Stream):
        async def __anext__(self):
            await asyncio.Event().wait()

    class HangingLLM:
        def chat(self, *, chat_ctx):
            return HangingStream()

    monkeypatch.setattr("app.voice_agent.post_call.SUMMARY_TIMEOUT_SECONDS", 0.01)
    sheets = Sheets()
    saved = asyncio.run(
        persist_post_call(
            SimpleNamespace(history=history(), llm=HangingLLM()),
            metadata(),
            "+421900111222",
            sheets=sheets,
        )
    )
    assert saved is True
    assert sheets.rows[0].values[1] == SUMMARY_UNAVAILABLE
