from dataclasses import asdict
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from control_plane.application.command_support import (
    IdempotencyKeyReused,
    StoredReplay,
    opaque_concurrency_token,
    request_fingerprint,
)
from control_plane.application.ports.transactions import PlatformCommandScope
from control_plane.domain.catalogs import CatalogStatus, InteractionMode, Profile


class ProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=2000)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(max_length=2000)


class InteractionModeCreate(ProfileCreate):
    pass


class InteractionModeUpdate(ProfileUpdate):
    pass


class CatalogError(Exception):
    code = "catalog_error"


class CatalogNotFound(CatalogError):
    code = "catalog_entry_not_found"


class CatalogConflict(CatalogError):
    code = "catalog_entry_conflict"


class CatalogPreconditionFailed(CatalogError):
    code = "precondition_failed"


class PlatformCatalogService:
    def __init__(self, command_scope: PlatformCommandScope) -> None:
        self._command_scope = command_scope

    @staticmethod
    def concurrency_token(value: Profile | InteractionMode) -> str:
        return opaque_concurrency_token(
            {**_semantic(value), "generation": value.generation}
        )

    async def list_profiles(self) -> tuple[Profile, ...]:
        async with self._command_scope() as (repository, _):
            return tuple(await repository.list_profiles())

    async def get_profile(self, key: str) -> Profile:
        async with self._command_scope() as (repository, _):
            value = await repository.get_profile(key)
        if value is None:
            raise CatalogNotFound(f"profile '{key}' does not exist")
        return value

    async def create_profile(
        self, body: ProfileCreate, principal: str, idempotency_key: str
    ) -> Profile:
        return await self._create("profile", body, principal, idempotency_key)

    async def update_profile(
        self,
        key: str,
        body: ProfileUpdate,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> Profile:
        return await self._update(
            "profile", key, body, None, expected_token, principal, idempotency_key
        )

    async def set_profile_enabled(
        self,
        key: str,
        enabled: bool,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> Profile:
        return await self._update(
            "profile", key, None, enabled, expected_token, principal, idempotency_key
        )

    async def list_interaction_modes(self) -> tuple[InteractionMode, ...]:
        async with self._command_scope() as (repository, _):
            return tuple(await repository.list_interaction_modes())

    async def get_interaction_mode(self, key: str) -> InteractionMode:
        async with self._command_scope() as (repository, _):
            value = await repository.get_interaction_mode(key)
        if value is None:
            raise CatalogNotFound(f"interaction mode '{key}' does not exist")
        return value

    async def create_interaction_mode(
        self, body: InteractionModeCreate, principal: str, idempotency_key: str
    ) -> InteractionMode:
        return await self._create("interaction_mode", body, principal, idempotency_key)

    async def update_interaction_mode(
        self,
        key: str,
        body: InteractionModeUpdate,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> InteractionMode:
        return await self._update(
            "interaction_mode",
            key,
            body,
            None,
            expected_token,
            principal,
            idempotency_key,
        )

    async def set_interaction_mode_enabled(
        self,
        key: str,
        enabled: bool,
        expected_token: str,
        principal: str,
        idempotency_key: str,
    ) -> InteractionMode:
        return await self._update(
            "interaction_mode",
            key,
            None,
            enabled,
            expected_token,
            principal,
            idempotency_key,
        )

    async def _create(self, kind, body, principal, idempotency_key):
        operation = f"{kind}_catalog.create"
        fingerprint = request_fingerprint(body.model_dump(mode="json"))
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._replay(kind, replay, fingerprint)
            getter = (
                repository.get_profile
                if kind == "profile"
                else repository.get_interaction_mode
            )
            if await getter(body.key, lock=True) is not None:
                raise CatalogConflict(f"{kind} key '{body.key}' already exists")
            putter = (
                repository.put_profile
                if kind == "profile"
                else repository.put_interaction_mode
            )
            result = await putter(
                body.key,
                body.name,
                body.description,
                CatalogStatus.ENABLED,
                principal,
            )
            await replays.add(
                principal, operation, idempotency_key, fingerprint, _result(result)
            )
            return result

    async def _update(
        self, kind, key, body, enabled, expected_token, principal, idempotency_key
    ):
        action = "update" if body is not None else "enable" if enabled else "disable"
        operation = f"{kind}_catalog.{action}"
        fingerprint = request_fingerprint(
            {
                "key": key,
                "body": body.model_dump(mode="json") if body is not None else None,
                "enabled": enabled,
                "if_match": expected_token,
            }
        )
        async with self._command_scope() as (repository, replays):
            replay = await replays.get(principal, operation, idempotency_key)
            if replay is not None:
                return self._replay(kind, replay, fingerprint)
            getter = (
                repository.get_profile
                if kind == "profile"
                else repository.get_interaction_mode
            )
            current = await getter(key, lock=True)
            if current is None:
                raise CatalogNotFound(f"{kind} key '{key}' does not exist")
            if expected_token != self.concurrency_token(current):
                raise CatalogPreconditionFailed(f"{kind} precondition failed")
            putter = (
                repository.put_profile
                if kind == "profile"
                else repository.put_interaction_mode
            )
            result = await putter(
                key,
                body.name if body is not None else current.name,
                body.description if body is not None else current.description,
                current.status
                if enabled is None
                else CatalogStatus.ENABLED
                if enabled
                else CatalogStatus.DISABLED,
                principal,
            )
            await replays.add(
                principal, operation, idempotency_key, fingerprint, _result(result)
            )
            return result

    @staticmethod
    def _replay(kind: str, replay: StoredReplay, fingerprint: str):
        if replay.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(
                "idempotency key reused with a different request"
            )
        value = replay.logical_result
        cls = Profile if kind == "profile" else InteractionMode
        return cls(
            value["key"],
            value["name"],
            value["description"],
            CatalogStatus(value["status"]),
            value["generation"],
            datetime.fromisoformat(value["created_at"]),
            datetime.fromisoformat(value["updated_at"]),
        )


def _semantic(value: Profile | InteractionMode) -> dict[str, str]:
    return {
        "key": value.key,
        "name": value.name,
        "description": value.description,
        "status": value.status.value,
    }


def _result(value: Profile | InteractionMode) -> dict[str, object]:
    result = asdict(value)
    result["status"] = value.status.value
    result["created_at"] = value.created_at.isoformat()
    result["updated_at"] = value.updated_at.isoformat()
    return result
