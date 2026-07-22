import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from livekit.agents.llm import ChatContext

from app.integrations.google_sheets.client import GoogleSheetsClient
from app.integrations.google_sheets.schemas import GoogleSheetsAppendRowRequest


logger = logging.getLogger(__name__)
SUMMARY_TIMEOUT_SECONDS = 10
SHEETS_TIMEOUT_SECONDS = 10
SUMMARY_UNAVAILABLE = "Zhrnutie sa nepodarilo vygenerovať."


def format_transcript(history, *, start_index: int = 0) -> str:
    lines = []
    for item in history.items[start_index:]:
        role = getattr(item, "role", None)
        if getattr(item, "type", None) != "message" or role not in {
            "user",
            "assistant",
        }:
            continue
        if role == "assistant" and getattr(item, "interrupted", False):
            continue
        content = " ".join((getattr(item, "raw_text_content", None) or "").split())
        if content:
            lines.append(f"{'Hosť' if role == 'user' else 'Agent'}: {content}")
    return "\n".join(lines)


async def generate_summary(llm, transcript: str) -> str:
    if llm is None:
        raise RuntimeError("LiveKit session LLM is unavailable")
    context = ChatContext()
    context.add_message(
        role="system",
        content=(
            "Napíš stručné operatívne zhrnutie hovoru po slovensky. Uveď dôvod "
            "hovoru, každú žiadosť o novú rezerváciu, zmenu alebo zrušenie a "
            "nevyriešené otázky. Za úspešnú považuj iba akciu, ktorú agent v "
            "prepise výslovne označil za odoslanú alebo vykonanú. Odoslanú "
            "žiadosť nikdy neoznačuj ako potvrdenú rezerváciu. Nevymýšľaj "
            "chýbajúce údaje. Odpovedz iba zhrnutím."
        ),
    )
    context.add_message(
        role="user",
        content=f"Prepis hovoru:\n{transcript or '(bez zachytených správ)'}",
    )
    chunks = []
    async with llm.chat(chat_ctx=context) as stream:
        async for chunk in stream:
            if chunk.delta and chunk.delta.content:
                chunks.append(chunk.delta.content)
    summary = "".join(chunks).strip()
    if not summary:
        raise RuntimeError("Post-call summary was empty")
    return summary


async def persist_post_call(
    session,
    metadata,
    caller_number: str,
    *,
    history_start_index: int = 0,
    completed_at: datetime | None = None,
    sheets: GoogleSheetsClient | None = None,
) -> bool:
    config = metadata.post_call_transcript
    if config is None:
        return False
    context = (
        f"tenant_id={metadata.tenant_id} call_session_id={metadata.call_session_id} "
        f"conversation_id={metadata.conversation_id}"
    )
    transcript = format_transcript(session.history, start_index=history_start_index)
    try:
        summary = await asyncio.wait_for(
            generate_summary(session.llm, transcript),
            timeout=SUMMARY_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Post-call summary generation failed %s", context)
        summary = SUMMARY_UNAVAILABLE

    completion_time = completed_at or datetime.now(timezone.utc)
    row = GoogleSheetsAppendRowRequest(
        spreadsheet_id=config.spreadsheet_id,
        sheet_name=config.sheet_name,
        values=[
            transcript,
            summary,
            completion_time.astimezone(ZoneInfo(metadata.timezone)).strftime(
                "%d.%m.%Y %H:%M:%S"
            ),
            str(caller_number),
        ],
    )
    try:
        await asyncio.wait_for(
            asyncio.to_thread((sheets or GoogleSheetsClient()).append_row, row),
            timeout=SHEETS_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception("Post-call transcript persistence failed %s", context)
        return False
    return True
