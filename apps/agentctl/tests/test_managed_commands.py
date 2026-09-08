from __future__ import annotations

import builtins
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from agentctl import control_plane
from agentctl import main as cli
from agentctl.commands import managed

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
    monkeypatch.setattr(managed, "getpass", lambda _prompt: "super-secret")
    monkeypatch.delenv("AGENTCTL_API_URL", raising=False)
    monkeypatch.delenv("AGENTCTL_TOKEN", raising=False)
    monkeypatch.setenv("AGENTCTL_CONTROL_PLANE_URL", "https://control-plane.example")
    monkeypatch.setenv("AGENTCTL_CONTROL_PLANE_TOKEN", "token")
    return cli.main(["--state-dir", str(tmp_path), *arguments]), requests


def _json(status: int, payload: Any, **headers: str) -> ResponseFactory:
    return lambda request: httpx.Response(
        status, json=payload, headers=headers, request=request
    )


def test_managed_commands_do_not_require_backend_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [_json(200, [])],
        "provider",
        "list",
    )

    assert code == 0
    assert requests[0].url.path == "/management/v1/providers/connections"


def test_platform_credential_create_maps_target_dto_and_is_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [_json(200, {"id": "credential-1", "secret": "super-secret"})],
        "credential",
        "create",
        "--name",
        "azure",
    )

    assert code == 0
    assert requests[0].url.path == "/management/v1/credentials"
    assert json.loads(requests[0].content) == {
        "scope": {"type": "platform"},
        "name": "azure",
        "secret": "super-secret",
    }
    assert requests[0].headers["Idempotency-Key"]
    assert "super-secret" not in capsys.readouterr().out


def test_managed_reads_do_not_expose_internal_generation_or_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _ = _run(
        monkeypatch,
        tmp_path,
        [_json(200, {"id": "provider-1", "generation": 3, "secret": "hidden"})],
        "provider",
        "show",
        "provider-1",
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "provider-1" in output
    assert "generation" not in output
    assert "hidden" not in output


def test_provider_create_passes_target_provider_kind_and_nested_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = {
        "key": "azure-main",
        "provider_kind": "future_provider_kind",
        "credential_ref": "credential-1",
        "connection_config": {"endpoint": "https://azure.example", "api_version": "v1"},
    }
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [_json(200, {"id": "provider-1"})],
        "provider",
        "create",
        "--json",
        json.dumps(body),
    )

    assert code == 0
    assert requests[0].url.path == "/management/v1/providers/connections"
    assert json.loads(requests[0].content) == body
    assert set(json.loads(requests[0].content)) == {
        "key",
        "provider_kind",
        "credential_ref",
        "connection_config",
    }
    assert requests[0].headers["Idempotency-Key"]


def test_provider_enable_reads_etag_and_sends_if_match_and_idempotency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"id": "provider-1"}, ETag='"provider-v1"'),
            _json(200, {"id": "provider-1", "enabled": True}),
        ],
        "provider",
        "enable",
        "provider-1",
    )

    assert code == 0
    assert [request.method for request in requests] == ["GET", "POST"]
    assert (
        requests[1].url.path == "/management/v1/providers/connections/provider-1/enable"
    )
    assert requests[1].headers["If-Match"] == '"provider-v1"'
    assert requests[1].headers["Idempotency-Key"]
    assert "generation" not in requests[1].content.decode()


def test_deployment_create_passes_target_kind_and_nested_objects_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = {
        "key": "llm-main",
        "connection_ref": "provider-1",
        "deployment_kind": "llm",
        "deployment_config": {"model": "gpt-4o", "temperature": 0.2},
        "capabilities": {
            "kind": "llm",
            "supports_temperature": True,
            "supports_reasoning_effort": True,
        },
    }
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [_json(200, {"id": "deployment-1"})],
        "deployment",
        "create",
        "--json",
        json.dumps(body),
    )

    assert code == 0
    assert requests[0].url.path == "/management/v1/providers/deployments"
    assert json.loads(requests[0].content) == body
    assert requests[0].headers["Idempotency-Key"]


def test_deployment_enable_reads_etag_and_sends_if_match_and_idempotency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, requests = _run(
        monkeypatch,
        tmp_path,
        [
            _json(200, {"id": "deployment-1"}, ETag='"deployment-v1"'),
            _json(200, {"id": "deployment-1", "enabled": True}),
        ],
        "deployment",
        "enable",
        "deployment-1",
    )

    assert code == 0
    assert [request.method for request in requests] == ["GET", "POST"]
    assert (
        requests[1].url.path
        == "/management/v1/providers/deployments/deployment-1/enable"
    )
    assert requests[1].headers["If-Match"] == '"deployment-v1"'
    assert requests[1].headers["Idempotency-Key"]


@pytest.mark.parametrize("status", (422, 412))
def test_managed_errors_keep_structured_422_and_distinguishable_412(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    error = {
        "code": "invalid_provider_kind" if status == 422 else "etag_mismatch",
        "message": "provider operation failed",
        "issues": [
            {"path": "provider_kind", "code": "unsupported", "message": "unknown"}
        ],
        "details": {"expected": '"new"'} if status == 412 else None,
        "request_id": "request-1",
    }
    responses = [_json(status, error)]
    if status == 412:
        responses.insert(0, _json(200, {"id": "provider-1"}, ETag='"old"'))
    code, requests = _run(
        monkeypatch,
        tmp_path,
        responses,
        "provider",
        "enable",
        "provider-1",
    )

    assert code == 3
    output = capsys.readouterr().err
    assert "provider operation failed" in output
    assert "request-1" in output
    if status == 422:
        assert len(requests) == 1
        assert "provider_kind: unsupported: unknown" in output
    else:
        assert len(requests) == 2
        assert requests[1].headers["If-Match"] == '"old"'
        assert "412" in output
        assert "details:" in output


@pytest.mark.parametrize("resource", ("provider", "deployment"))
def test_managed_path_does_not_import_legacy_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, resource: str
) -> None:
    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("agentctl.workspace"):
            raise AssertionError("managed resource path imported legacy workspace")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    code, _ = _run(monkeypatch, tmp_path, [_json(200, [])], resource, "list")

    assert code == 0
