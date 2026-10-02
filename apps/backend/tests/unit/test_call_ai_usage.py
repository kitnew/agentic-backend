from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from backend_core.modules.calls.usage_service import estimate_cost, upsert_call_usage
from contracts import CallModelUsage, CallUsageReport


class FakeSession:
    def __init__(self, call_id):
        self.call_id = call_id
        self.tenant_id = uuid4()
        self.rows = {}

    async def get(self, model, key, **_):
        if isinstance(key, tuple):
            return self.rows.get(key)
        return (
            SimpleNamespace(tenant_id=self.tenant_id) if key == self.call_id else None
        )

    def add(self, row):
        self.rows[(row.call_id, row.provider, row.service, row.model, row.source)] = row


def item(service="llm", counters=None, at=None):
    return CallModelUsage(
        provider="openai",
        service=service,
        model="model-a",
        observed_at=at or datetime.now(UTC),
        counters=counters
        or {"input_tokens": 100, "input_cached_tokens": 20, "output_tokens": 10},
    )


def test_unknown_and_incomplete_prices_leave_cost_unknown():
    usage = item()
    assert estimate_cost(usage, {}) == (None, None)
    assert estimate_cost(
        usage,
        {
            "openai/llm/model-a": {
                "source": "rate-v1",
                "rates": {"input_tokens": "0.01"},
            }
        },
    ) == (None, None)


def test_decimal_price_separates_cached_tokens():
    cost, source = estimate_cost(
        item(),
        {
            "openai/llm/model-a": {
                "source": "rate-v1",
                "rates": {
                    "input_tokens": "0.01",
                    "input_cached_tokens": "0.002",
                    "output_tokens": "0.03",
                },
            }
        },
    )
    assert cost == Decimal("1.14")
    assert source == "rate-v1"


@pytest.mark.parametrize(
    ("service", "counters", "rates", "expected"),
    [
        (
            "stt",
            {"audio_duration": 30.0, "input_tokens": 0, "output_tokens": 0},
            {"audio_duration": "0.001"},
            Decimal("0.030"),
        ),
        (
            "tts",
            {
                "characters_count": 100,
                "audio_duration": 4.0,
                "input_tokens": 0,
                "output_tokens": 0,
            },
            {"characters_count": "0.0001", "audio_duration": "0"},
            Decimal("0.0100"),
        ),
    ],
)
def test_stt_and_tts_prices_require_explicit_measured_dimensions(
    service, counters, rates, expected
):
    usage = item(service=service, counters=counters)
    price = {f"openai/{service}/model-a": {"source": "rate-v1", "rates": rates}}
    assert estimate_cost(usage, price) == (expected, "rate-v1")


@pytest.mark.asyncio
async def test_upsert_replaces_cumulative_usage_and_ignores_stale_update():
    call_id = uuid4()
    session = FakeSession(call_id)
    at = datetime.now(UTC)
    first = item(at=at)
    found, changes = await upsert_call_usage(
        session, call_id, CallUsageReport(usage=[first]), {}
    )
    assert found and changes[0][3]["input_tokens"] == 100
    second = item(
        counters={"input_tokens": 130, "input_cached_tokens": 30, "output_tokens": 20},
        at=at + timedelta(seconds=1),
    )
    _, changes = await upsert_call_usage(
        session, call_id, CallUsageReport(usage=[second]), {}
    )
    assert changes[0][3]["input_tokens"] == 30
    _, changes = await upsert_call_usage(
        session, call_id, CallUsageReport(usage=[first]), {}
    )
    assert changes == []
    assert next(iter(session.rows.values())).counters["input_tokens"] == 130


@pytest.mark.asyncio
async def test_missing_call_rejected():
    found, changes = await upsert_call_usage(
        FakeSession(uuid4()), uuid4(), CallUsageReport(usage=[item()]), {}
    )
    assert not found and not changes


@pytest.mark.asyncio
async def test_multiple_providers_and_models_have_separate_rows():
    call_id = uuid4()
    session = FakeSession(call_id)
    rows = [item(), item(service="stt", counters={"audio_duration": 3.0})]
    rows[1].provider = "soniox"
    rows[1].model = "stt-rt-v5"
    found, changes = await upsert_call_usage(
        session, call_id, CallUsageReport(usage=rows), {}
    )
    assert found and len(changes) == len(session.rows) == 2
