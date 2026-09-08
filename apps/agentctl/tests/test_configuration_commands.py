from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from agentctl import control_plane
from agentctl import main as cli

ResponseFactory = Callable[[httpx.Request], httpx.Response]


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    responses: list[ResponseFactory],
    *arguments: str,
) -> tuple[int, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return responses.pop(0)(request)

    class FakeAuthenticatedClient:
        def __init__(
            self, *, base_url: str, token: str, timeout: httpx.Timeout
        ) -> None:
            self.client = httpx.Client(
                base_url=base_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                transport=httpx.MockTransport(handler),
            )

        def get_httpx_client(self) -> httpx.Client:
            return self.client

    monkeypatch.setattr(control_plane, "AuthenticatedClient", FakeAuthenticatedClient)
    monkeypatch.delenv("AGENTCTL_API_URL", raising=False)
    monkeypatch.delenv("AGENTCTL_TOKEN", raising=False)
    monkeypatch.setenv("AGENTCTL_CONTROL_PLANE_URL", "https://control-plane.example")
    monkeypatch.setenv("AGENTCTL_CONTROL_PLANE_TOKEN", "secret")
    code = cli.main(["--state-dir", str(tmp_path), "configuration", *arguments])
    return code, requests


def _json(status: int, payload: Any, **headers: str) -> ResponseFactory:
    return lambda request: httpx.Response(
        status, json=payload, headers=headers, request=request
    )


def _yaml(path: Path, value: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


SYSTEM_DESIRED = {
    "stt_defaults": {"deployment_ref": "stt-1"},
    "llm_defaults": {"deployment_ref": "llm-1", "max_completion_tokens": 20},
    "tts_defaults": {"deployment_ref": "tts-1", "default_voice_id": "alloy"},
    "realtime_defaults": {
        "deployment_ref": "rt-1",
        "input_transcription": {"deployment_ref": "stt-rt-1"},
        "default_voice": "marin",
        "turn_completion": {"strategy": "server_vad"},
        "interruption": {"enabled": True},
    },
    "policies": {"cascade": {}},
}


def test_system_plan_sends_yaml_directly_to_high_level_plan(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    desired_path = tmp_path / "system.yaml"
    _yaml(desired_path, SYSTEM_DESIRED)
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [_json(200, {"valid": True, "changes": [], "warnings": [], "errors": []})],
        "system",
        "plan",
        str(desired_path),
    )
    assert code == 0
    assert [request.url.path for request in requests] == [
        "/management/v1/system/configuration/plan"
    ]
    assert "If-Match" not in requests[0].headers
    assert "If-None-Match" not in requests[0].headers
    assert "Idempotency-Key" not in requests[0].headers
    assert json.loads(requests[0].content) == SYSTEM_DESIRED
    assert "valid: true" in capsys.readouterr().out


def test_system_apply_initializes_with_if_none_match_and_one_put(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desired_path = tmp_path / "system.yaml"
    _yaml(desired_path, SYSTEM_DESIRED)
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(
                404,
                {
                    "code": "configuration_not_found",
                    "message": "absent",
                    "request_id": "r1",
                },
            ),
            _json(200, {"configuration": SYSTEM_DESIRED}, ETag='"new"'),
        ],
        "system",
        "apply",
        str(desired_path),
    )
    assert code == 0
    assert [request.method for request in requests] == ["GET", "PUT"]
    assert requests[1].headers["If-None-Match"] == "*"
    assert requests[1].headers["Idempotency-Key"]
    assert "If-Match" not in requests[1].headers
    assert json.loads(requests[1].content) == SYSTEM_DESIRED


def test_system_apply_uses_current_etag_for_one_put(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desired_path = tmp_path / "system.yaml"
    _yaml(desired_path, SYSTEM_DESIRED)
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, SYSTEM_DESIRED, ETag='"current"'),
            _json(200, {"configuration": SYSTEM_DESIRED}, ETag='"next"'),
        ],
        "system",
        "apply",
        str(desired_path),
    )
    assert code == 0
    assert requests[1].headers["If-Match"] == '"current"'
    assert requests[1].headers["Idempotency-Key"]
    assert len([request for request in requests if request.method == "PUT"]) == 1


def test_platform_publish_is_one_aggregate_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"status": {"has_drafts": True}}, ETag='"platform"'),
            _json(200, {"configuration": {}}),
        ],
        "platform",
        "publish",
    )
    assert code == 0
    assert [request.url.path for request in requests] == [
        "/management/v1/platform/configuration",
        "/management/v1/platform/configuration/publish",
    ]
    assert requests[1].headers["If-Match"] == '"platform"'
    assert requests[1].headers["Idempotency-Key"]


def test_platform_plan_and_apply_use_complete_desired_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desired = {
        "system_prompt": {"content": "hello"},
        "profiles": [],
        "interaction_modes": [],
    }
    desired_path = tmp_path / "platform.yaml"
    _yaml(desired_path, desired)
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"valid": True, "catalog_changes": [], "draft_changes": []}),
        ],
        "platform",
        "plan",
        str(desired_path),
    )
    assert code == 0
    assert requests[0].url.path == "/management/v1/platform/configuration/plan"
    assert json.loads(requests[0].content) == desired

    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"configuration": {}}, ETag='"platform"'),
            _json(200, {"configuration": desired}, ETag='"next"'),
        ],
        "platform",
        "apply",
        str(desired_path),
    )
    assert code == 0
    assert requests[1].url.path == "/management/v1/platform/configuration"
    assert requests[1].headers["If-Match"] == '"platform"'
    assert json.loads(requests[1].content) == desired
    assert len([request for request in requests if request.method == "PUT"]) == 1

    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(
                404,
                {
                    "code": "configuration_not_found",
                    "message": "absent",
                    "request_id": "r5",
                },
            ),
            _json(200, {"configuration": desired}),
        ],
        "platform",
        "apply",
        str(desired_path),
    )
    assert code == 0
    assert requests[1].headers["If-None-Match"] == "*"
    assert "If-Match" not in requests[1].headers


def test_tenant_plan_and_apply_use_tenant_high_level_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desired_path = tmp_path / "tenant.yaml"
    desired = {
        "tenant_prompt": {"content": "hello"},
        "knowledge": {"content": "knowledge"},
        "agent_personality": {
            "identity": "concierge",
            "display_name": "Concierge",
            "greeting": "Hello",
            "conversation_scope": "property_only",
        },
        "business_info": {
            "business": {"name": "Hotel", "type": "hotel"},
            "contact": {"phones": [], "emails": []},
            "localization": {"default_locale": "en", "timezone": "UTC"},
        },
        "actions_definition": {"actions": {}},
        "architecture": {"architecture_key": "cascade"},
        "profile_reference": {"profile_key": "concierge"},
        "runtime_overrides": {},
        "actions_availability": {"actions": {}},
    }
    _yaml(desired_path, desired)
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"valid": True, "changes": [], "warnings": [], "errors": []}),
        ],
        "tenant",
        "tenant-1",
        "plan",
        str(desired_path),
    )
    assert code == 0
    assert requests[0].url.path == "/management/v1/tenants/tenant-1/configuration/plan"
    assert len(requests) == 1
    assert json.loads(requests[0].content) == desired

    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(
                404,
                {
                    "code": "configuration_not_found",
                    "message": "absent",
                    "request_id": "r3",
                },
            ),
            _json(200, {"configuration": desired}),
        ],
        "tenant",
        "tenant-1",
        "apply",
        str(desired_path),
    )
    assert code == 0
    assert [request.url.path for request in requests] == [
        "/management/v1/tenants/tenant-1/configuration",
        "/management/v1/tenants/tenant-1/configuration",
    ]
    assert requests[1].headers["If-None-Match"] == "*"
    assert json.loads(requests[1].content) == desired


def test_tenant_subsequent_apply_and_publish_are_aggregate_operations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desired = {"architecture": {"architecture_key": "cascade"}}
    desired_path = tmp_path / "tenant.yaml"
    _yaml(desired_path, desired)
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"configuration": {}}, ETag='"tenant-old"'),
            _json(200, {"configuration": desired}, ETag='"tenant-new"'),
        ],
        "tenant",
        "tenant-1",
        "apply",
        str(desired_path),
    )
    assert code == 0
    assert requests[1].headers["If-Match"] == '"tenant-old"'
    assert requests[1].headers["Idempotency-Key"]
    assert len([request for request in requests if request.method == "PUT"]) == 1

    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"status": {"has_drafts": True}}, ETag='"tenant"'),
            _json(200, {"configuration": {}}),
        ],
        "tenant",
        "tenant-1",
        "publish",
    )
    assert code == 0
    assert (
        requests[1].url.path == "/management/v1/tenants/tenant-1/configuration/publish"
    )
    assert requests[1].headers["If-Match"] == '"tenant"'
    assert requests[1].headers["Idempotency-Key"]


def test_get_returns_high_level_configuration_and_404_is_not_fabricated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [_json(200, SYSTEM_DESIRED, ETag='"system"')],
        "system",
        "get",
    )
    assert code == 0
    assert requests[0].url.path == "/management/v1/system/configuration"
    assert yaml.safe_load(capsys.readouterr().out) == SYSTEM_DESIRED

    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(
                404,
                {
                    "code": "configuration_not_found",
                    "message": "absent",
                    "request_id": "r4",
                },
            )
        ],
        "platform",
        "get",
    )
    assert code == 3
    assert len(requests) == 1
    assert "platform configuration is not initialized" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (422, "configuration_invalid", "llm_defaults: invalid_value: unsupported"),
        (412, "etag_mismatch", "Control Plane API request failed (412"),
    ],
)
def test_structured_control_plane_errors_are_readable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: int,
    code: str,
    expected: str,
) -> None:
    desired_path = tmp_path / "system.yaml"
    _yaml(desired_path, SYSTEM_DESIRED)
    payload = {
        "code": code,
        "message": "configuration failed",
        "issues": [
            {"path": "llm_defaults", "code": "invalid_value", "message": "unsupported"}
        ],
        "request_id": "request-1",
    }
    responses = [_json(status, payload)]
    if status == 412:
        responses.insert(0, _json(200, SYSTEM_DESIRED, ETag='"current"'))
    cli_code, requests = _run(
        monkeypatch,
        tmp_path,
        responses,
        "system",
        "plan" if status == 422 else "apply",
        str(desired_path),
    )
    assert cli_code == 3
    if status == 412:
        assert requests[1].headers["If-Match"] == '"current"'
    error = capsys.readouterr().err
    assert expected in error
    assert "configuration failed" in error
    assert "request-1" in error
