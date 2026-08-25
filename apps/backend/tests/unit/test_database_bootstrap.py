from backend_core.platform.database.bootstrap import registered_table_names


def test_metadata_registry_contains_application_schema() -> None:
    tables = set(registered_table_names())

    assert {"tenants", "tenant_releases", "call_sessions", "outbox_messages"} <= tables
