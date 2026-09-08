from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from control_plane.application.system_configuration import (
    ConfigurationChange,
    SystemConfiguration,
    SystemConfigurationApplyResult,
    SystemConfigurationPlan,
)
from control_plane.interfaces.http import create_http_app
from httpx import ASGITransport, AsyncClient


class Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


def payload():
    refs = {name: str(uuid4()) for name in ("stt", "llm", "tts", "realtime")}
    return {
        "stt_defaults": {"deployment_ref": refs["stt"]},
        "llm_defaults": {
            "deployment_ref": refs["llm"],
            "temperature": None,
            "reasoning_effort": None,
            "max_completion_tokens": 100,
        },
        "tts_defaults": {"deployment_ref": refs["tts"], "default_voice_id": "marin"},
        "realtime_defaults": {
            "deployment_ref": refs["realtime"],
            "input_transcription": {"deployment_ref": refs["stt"]},
            "default_voice": "marin",
            "turn_completion": {"strategy": "server_vad"},
            "interruption": {"enabled": True},
        },
        "policies": {
            "cascade": {
                "speech_activity": {
                    "min_speech_seconds": 0.1,
                    "min_silence_seconds": 0.2,
                    "activation_threshold": 0.5,
                },
                "stt_commit": {"strategy": "local_vad"},
                "endpointing": {"min_delay_seconds": 0.1, "max_delay_seconds": 0.2},
                "interruption": {
                    "enabled": True,
                    "min_duration_seconds": 0,
                    "min_words": 0,
                    "false_interruption_timeout_seconds": 0,
                    "resume_after_false_interruption": True,
                },
                "response_scheduling": {
                    "preemptive_generation": False,
                    "preemptive_tts": False,
                },
                "tokenizer": {"min_sentence_chars": 3},
            }
        },
    }


class System:
    def __init__(self):
        self.value = SystemConfiguration.model_validate(payload())
        self.calls = []

    async def get(self):
        return self.value

    async def plan(self, desired):
        self.calls.append(("plan", desired))
        return SystemConfigurationPlan(
            True, (ConfigurationChange("tts_defaults", "update"),), (), ()
        )

    async def apply(self, desired, token, principal, key):
        self.calls.append(("apply", token, principal, key))
        self.value = SystemConfiguration.model_validate(desired.model_dump())
        return SystemConfigurationApplyResult(("tts_defaults",), (), self.value)

    @staticmethod
    def concurrency_token(value):
        return "aggregate"


@pytest.mark.asyncio
async def test_target_system_routes_etag_idempotency_and_no_publish() -> None:
    system = System()
    app = create_http_app(Lifecycle(), system_configuration=system)  # type: ignore[arg-type]
    app.state.settings = SimpleNamespace(
        control_plane_management_token=SimpleNamespace(
            get_secret_value=lambda: "secret"
        ),
        control_plane_management_actor="admin",
        control_plane_management_scopes="configuration:read,configuration:write",
    )
    auth = {"Authorization": "Bearer secret"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        read = await client.get("/management/v1/system/configuration", headers=auth)
        plan = await client.post(
            "/management/v1/system/configuration/plan", headers=auth, json=payload()
        )
        missing_key = await client.put(
            "/management/v1/system/configuration",
            headers={**auth, "If-Match": '"aggregate"'},
            json=payload(),
        )
        applied = await client.put(
            "/management/v1/system/configuration",
            headers={**auth, "If-Match": '"aggregate"', "Idempotency-Key": "apply"},
            json=payload(),
        )
        publish = await client.post(
            "/management/v1/system/configuration/publish", headers=auth
        )

    assert read.status_code == 200 and read.headers["etag"] == '"aggregate"'
    assert set(read.json()) == {
        "stt_defaults",
        "llm_defaults",
        "tts_defaults",
        "realtime_defaults",
        "policies",
    }
    assert plan.status_code == 200 and "etag" not in plan.headers
    assert missing_key.status_code == 400
    assert applied.status_code == 200 and applied.headers["etag"] == '"aggregate"'
    assert publish.status_code == 404


def test_openapi_contains_only_frozen_system_methods() -> None:
    app = create_http_app(
        Lifecycle(), system_configuration=System(), live_components=object()
    )  # type: ignore[arg-type]
    paths = app.openapi()["paths"]
    assert set(paths["/management/v1/system/configuration"]) == {"get", "put"}
    assert set(paths["/management/v1/system/configuration/plan"]) == {"post"}
    assert set(paths["/management/v1/system/components/{kind}"]) == {"get", "put"}
    assert "/management/v1/system/configuration/publish" not in paths
