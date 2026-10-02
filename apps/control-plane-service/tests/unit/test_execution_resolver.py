from uuid import uuid4

from control_plane.application.execution_resolver import ExecutionResolver
from control_plane.application.runtime_resolver import RuntimeResolutionState


def test_integration_lookup_scopes_duplicate_keys_to_tenant() -> None:
    tenant_id = "tenant-b"
    expected = {
        "id": uuid4(),
        "key": "post_call_actions",
        "tenant_id": tenant_id,
        "integration_kind": "http",
        "config": {
            "endpoint": "https://example.com",
            "authentication": {"type": "none"},
        },
        "enabled": True,
        "credential": None,
    }
    state = RuntimeResolutionState(
        {},
        {},
        {},
        {},
        {},
        integrations={
            uuid4(): {**expected, "id": uuid4(), "tenant_id": "tenant-a"},
            expected["id"]: expected,
        },
    )

    assert ExecutionResolver._validate_integration(
        tenant_id, "post_call_actions", state
    ) is expected
