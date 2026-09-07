from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from enum import StrEnum
from typing import Protocol

from fastapi import FastAPI

from control_plane.runtime.health import Readiness

logger = logging.getLogger(__name__)
READINESS_TIMEOUT_SECONDS = 2.0


class LifecycleState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    READY = "ready"
    DRAINING = "draining"
    STOPPED = "stopped"


class RuntimeDependency(Protocol):
    async def connect(self) -> None: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class DatabaseDependency(RuntimeDependency, Protocol):
    async def schema_compatible(self) -> bool: ...


class TelemetryRuntime(Protocol):
    def shutdown(self) -> object: ...


class ServiceLifecycle:
    def __init__(
        self,
        database: DatabaseDependency,
        telemetry: TelemetryRuntime | None = None,
    ) -> None:
        self.database = database
        self.telemetry = telemetry
        self.state = LifecycleState.CREATED

    @asynccontextmanager
    async def lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        await self.start()
        try:
            yield
        finally:
            await self.stop()

    async def start(self) -> None:
        self.state = LifecycleState.STARTING
        logger.info("Control Plane starting")
        try:
            await self.database.connect()
            if not await self.database.schema_compatible():
                raise RuntimeError("Control Plane schema is not at the migration head")
        except Exception:
            with suppress(Exception):
                await self.database.close()
            self.state = LifecycleState.STOPPED
            raise
        self.state = LifecycleState.READY
        logger.info("Control Plane ready")

    async def stop(self) -> None:
        if self.state == LifecycleState.STOPPED:
            return
        self.state = LifecycleState.DRAINING
        logger.info("Control Plane draining")
        try:
            await self.database.close()
        finally:
            if self.telemetry is not None:
                self.telemetry.shutdown()
            self.state = LifecycleState.STOPPED
            logger.info("Control Plane stopped")

    async def readiness(self) -> Readiness:
        if self.state != LifecycleState.READY:
            return Readiness(
                postgres=False,
                control_plane_schema=False,
            )
        postgres = await _check(self.database)
        schema = postgres and await _schema_check(self.database)
        return Readiness(
            postgres=postgres,
            control_plane_schema=schema,
        )


async def _check(dependency: RuntimeDependency) -> bool:
    try:
        await asyncio.wait_for(dependency.ping(), timeout=READINESS_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001
        return False
    return True


async def _schema_check(database: DatabaseDependency) -> bool:
    try:
        return await asyncio.wait_for(
            database.schema_compatible(), timeout=READINESS_TIMEOUT_SECONDS
        )
    except Exception:  # noqa: BLE001
        return False
