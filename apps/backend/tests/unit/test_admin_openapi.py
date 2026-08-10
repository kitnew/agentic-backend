from scripts.export_admin_openapi import admin_openapi, render_admin_openapi


def test_admin_openapi_is_isolated_deterministic_and_unique() -> None:
    schema = admin_openapi()
    paths = schema["paths"]

    assert "/admin/v1/tenants" in paths
    assert "/admin/v1/tenants/by-slug/{slug}" in paths
    assert all(path.startswith("/admin/v1/") for path in paths)
    assert "/admin/v1/tenants/{tenant_id}/config/import-yaml" not in paths
    assert not any(path.startswith("/internal/") for path in paths)
    assert "/" not in paths
    assert "/health" not in paths
    assert "/ready" not in paths
    assert set(schema["components"]["securitySchemes"]) == {"AdminToken"}

    operation_ids = [
        operation["operationId"]
        for path in paths.values()
        for operation in path.values()
        if "operationId" in operation
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert render_admin_openapi() == render_admin_openapi()
