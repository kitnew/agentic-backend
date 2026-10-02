"""Validate and upsert LiveKit's cumulative usage snapshots."""

from datetime import UTC
from decimal import Decimal, InvalidOperation
from math import isfinite
from uuid import UUID

from contracts.usage import CallModelUsage, CallUsageReport
from sqlalchemy.ext.asyncio import AsyncSession

from backend_core.modules.calls.models import CallSession
from backend_core.modules.calls.usage import CallAIUsage

COUNTERS = {
    "llm": {
        "input_tokens",
        "input_cached_tokens",
        "input_cache_creation_tokens",
        "input_audio_tokens",
        "input_cached_audio_tokens",
        "input_text_tokens",
        "input_cached_text_tokens",
        "input_image_tokens",
        "input_cached_image_tokens",
        "output_tokens",
        "output_audio_tokens",
        "output_text_tokens",
        "output_reasoning_tokens",
        "session_duration",
    },
    "stt": {"input_tokens", "output_tokens", "audio_duration"},
    "tts": {"input_tokens", "output_tokens", "characters_count", "audio_duration"},
}


def validate_counters(item: CallModelUsage) -> None:
    if not set(item.counters) <= COUNTERS[item.service]:
        raise ValueError("unsupported usage counter")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not isfinite(value)
        or value < 0
        for value in item.counters.values()
    ):
        raise ValueError("invalid usage counter")
    if any(
        not isinstance(value, int)
        for name, value in item.counters.items()
        if name not in {"audio_duration", "session_duration"}
    ):
        raise ValueError("token and character counters must be integers")
    if item.observed_at.tzinfo is None:
        raise ValueError("usage timestamp requires timezone")


def estimate_cost(
    item: CallModelUsage, prices: dict[str, dict[str, object]]
) -> tuple[Decimal | None, str | None]:
    price = prices.get(f"{item.provider}/{item.service}/{item.model}")
    if not price:
        return None, None
    source = price.get("source")
    rates = price.get("rates")
    if (
        not isinstance(source, str)
        or not source
        or not isinstance(rates, dict)
        or not rates
    ):
        return None, None
    c = item.counters
    if item.service == "llm":
        if any(
            c.get(name, 0)
            for name in (
                "input_audio_tokens",
                "input_text_tokens",
                "input_image_tokens",
            )
        ):
            if c.get("input_tokens", 0) != sum(
                (
                    c.get("input_text_tokens", 0),
                    c.get("input_audio_tokens", 0),
                    c.get("input_image_tokens", 0),
                )
            ):
                return None, None
            dimensions = {
                "input_text_tokens": c.get("input_text_tokens", 0)
                - c.get("input_cached_text_tokens", 0),
                "input_cached_text_tokens": c.get("input_cached_text_tokens", 0),
                "input_audio_tokens": c.get("input_audio_tokens", 0)
                - c.get("input_cached_audio_tokens", 0),
                "input_cached_audio_tokens": c.get("input_cached_audio_tokens", 0),
                "input_image_tokens": c.get("input_image_tokens", 0)
                - c.get("input_cached_image_tokens", 0),
                "input_cached_image_tokens": c.get("input_cached_image_tokens", 0),
                "output_text_tokens": c.get("output_text_tokens", 0),
                "output_audio_tokens": c.get("output_audio_tokens", 0),
            }
            output_split = c.get("output_text_tokens", 0) + c.get(
                "output_audio_tokens", 0
            )
            if c.get("output_tokens", 0) == output_split + c.get(
                "output_reasoning_tokens", 0
            ):
                dimensions["output_reasoning_tokens"] = c.get(
                    "output_reasoning_tokens", 0
                )
            elif c.get("output_tokens", 0) != output_split:
                return None, None
        else:
            dimensions = {
                "input_tokens": c.get("input_tokens", 0)
                - c.get("input_cached_tokens", 0)
                - c.get("input_cache_creation_tokens", 0),
                "input_cached_tokens": c.get("input_cached_tokens", 0),
                "output_tokens": c.get("output_tokens", 0),
            }
        if c.get("input_cache_creation_tokens", 0):
            dimensions["input_cache_creation_tokens"] = c["input_cache_creation_tokens"]
        if c.get("session_duration", 0):
            dimensions["session_duration"] = c["session_duration"]
    elif item.service == "stt":
        dimensions = {
            name: c.get(name, 0)
            for name in ("input_tokens", "output_tokens", "audio_duration")
        }
    else:
        dimensions = {
            name: c.get(name, 0)
            for name in (
                "input_tokens",
                "output_tokens",
                "characters_count",
                "audio_duration",
            )
        }
    if any(value < 0 for value in dimensions.values()):
        return None, None
    total = Decimal(0)
    try:
        for name, value in dimensions.items():
            if not value:
                continue
            rate = Decimal(str(rates[name]))
            if not rate.is_finite() or rate < 0:
                return None, None
            total += Decimal(str(value)) * rate
    except KeyError, InvalidOperation, TypeError, ValueError:
        return None, None
    return total, source


async def upsert_call_usage(
    session: AsyncSession,
    call_id: UUID,
    report: CallUsageReport,
    prices: dict[str, dict[str, object]],
) -> tuple[bool, list[tuple[str, str, str, dict[str, float], Decimal]]]:
    # Lock the parent call so concurrent reports cannot both treat a row as new.
    call = await session.get(CallSession, call_id, with_for_update=True)
    if call is None:
        return False, []
    changes: list[tuple[str, str, str, dict[str, float], Decimal]] = []
    for item in report.usage:
        validate_counters(item)
        cost, source = estimate_cost(item, prices)
        observed_at = item.observed_at.astimezone(UTC)
        key = (call_id, item.provider, item.service, item.model, item.source)
        row = await session.get(CallAIUsage, key)
        if row is not None and row.last_observed_at >= observed_at:
            continue
        previous = row.counters if row is not None else {}
        previous_cost = row.estimated_cost_usd if row is not None else None
        if row is None:
            row = CallAIUsage(
                call_id=call_id,
                tenant_id=call.tenant_id,
                provider=item.provider,
                service=item.service,
                model=item.model,
                source=item.source,
                first_observed_at=observed_at,
                last_observed_at=observed_at,
                counters=item.counters,
                estimated_cost_usd=cost,
                estimated_cost_source=source,
            )
            session.add(row)
        else:
            row.counters = item.counters
            row.last_observed_at = observed_at
            row.estimated_cost_usd = cost
            row.estimated_cost_source = source
        delta = {
            name: float(value) - float(previous.get(name, 0))
            for name, value in item.counters.items()
            if float(value) > float(previous.get(name, 0))
        }
        cost_delta = max(
            Decimal(0), (cost or Decimal(0)) - (previous_cost or Decimal(0))
        )
        changes.append((item.provider, item.service, item.model, delta, cost_delta))
    return True, changes
