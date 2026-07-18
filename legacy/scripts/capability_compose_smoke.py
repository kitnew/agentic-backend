import asyncio
import json
from uuid import uuid4

from redis.asyncio import Redis

from app.application.capabilities.redis_executor import RedisCapabilityExecutor
from app.capabilities.schemas import (
    CapabilityCommand,
    CapabilityExecutionStatus,
)
from app.core.config import CapabilitySettings


def command(
    command_id: str,
    tenant_id: str,
    session_id: str,
    idempotency_key: str,
) -> CapabilityCommand:
    return CapabilityCommand(
        command_id=command_id,
        tenant_id=tenant_id,
        conversation_id=f"conversation-{session_id}",
        call_session_id=session_id,
        capability="reservation",
        action="create_request",
        payload={"smoke": True},
        idempotency_key=idempotency_key,
        metadata={
            "legacy_capability_name": "reservation.create_request",
            "call_session_id": session_id,
            "smoke_session": session_id,
        },
    )


async def run() -> None:
    settings = CapabilitySettings.from_env()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    executor = RedisCapabilityExecutor(settings=settings, redis_client=redis)
    run_id = uuid4().hex
    try:
        await redis.ping()
        first = await executor.execute(
            command(f"{run_id}-first", "smoke_manual_a", "session-first", run_id)
        )
        reused = await executor.execute(
            command(f"{run_id}-reused", "smoke_manual_a", "session-reused", run_id)
        )
        isolated_a, isolated_b = await asyncio.gather(
            executor.execute(
                command(
                    f"{run_id}-tenant-a",
                    "smoke_manual_a",
                    "session-tenant-a",
                    f"{run_id}-shared",
                )
            ),
            executor.execute(
                command(
                    f"{run_id}-tenant-b",
                    "smoke_manual_b",
                    "session-tenant-b",
                    f"{run_id}-shared",
                )
            ),
        )
        results = [first, reused, isolated_a, isolated_b]
        assert all(item.status == CapabilityExecutionStatus.SUCCESS for item in results)
        assert [item.command_id for item in results] == [
            f"{run_id}-first",
            f"{run_id}-reused",
            f"{run_id}-tenant-a",
            f"{run_id}-tenant-b",
        ]
        assert reused.metadata["idempotency_reused"] is True
        assert reused.metadata["call_session_id"] == "session-reused"
        assert isolated_a.metadata["smoke_session"] == "session-tenant-a"
        assert isolated_b.metadata["smoke_session"] == "session-tenant-b"
        print(
            json.dumps(
                {
                    "status": "ok",
                    "correlated_results": len(results),
                    "idempotency_reused": True,
                    "tenant_session_isolation": True,
                }
            )
        )
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(run())
