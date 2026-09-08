import pytest
from control_plane.domain.components import ComponentAddress, ComponentKind, TenantScope
from control_plane.domain.components.errors import InvalidComponentValue
from control_plane.domain.frozen_components import default_component_definition_registry


def definition():
    return default_component_definition_registry().resolve(
        ComponentAddress(ComponentKind("ActionsDefinition"), TenantScope("tenant-a"))
    )


def runtime_action(**changes):
    value = {
        "phase": "runtime",
        "description": "Look up availability",
        "announcement": "One moment",
        "agent_input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["check_in", "check_out"],
            "properties": {
                "check_in": {"type": "string", "format": "date"},
                "check_out": {"type": "string", "format": "date"},
            },
        },
        "bindings": {
            "check_in": "stay.check_in",
            "check_out": "stay.check_out",
        },
        "input_constraints": [
            {
                "kind": "date_range",
                "start": "stay.check_in",
                "end": "stay.check_out",
            }
        ],
        "business_policy": {
            "requires_final_confirmation": True,
            "requires_caller_phone": False,
        },
        "execution": {
            "integration_key": "booking",
            "method": "POST",
            "path": {"$expr": "metadata.path"},
            "request": {
                "codec": "json",
                "mapping": {
                    "start": {"$expr": "business.stay.check_in"},
                    "note": {"$expr": "inputs.note"},
                },
            },
            "response": {
                "codec": "json",
                "mapping": {"status": {"$expr": "response.status_code"}},
            },
            "timeout_seconds": 5,
        },
        "result_schema": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "properties": {"status": {"type": "integer"}},
        },
    }
    value.update(changes)
    return value


def validate(action):
    return definition().deserialize({"actions": {"availability.lookup": action}})


def post_call_action(**changes):
    value = {
        "phase": "post_call",
        "artifact_inputs": {
            "summary": {
                "artifact": "call_summary",
                "representation": "plain_text",
            }
        },
        "execution": {
            "integration_key": "notify",
            "method": "POST",
            "request": {"codec": "json", "mapping": None},
            "response": {"codec": "json", "mapping": None},
            "timeout_seconds": 5,
        },
    }
    value.update(changes)
    return value


def test_runtime_and_post_call_actions_share_one_frozen_map() -> None:
    runtime = runtime_action()
    post_call = post_call_action()
    post_call["execution"] = {
        **post_call["execution"],
        "request": {
            "codec": "json",
            "mapping": {"summary": {"$expr": "inputs.summary"}},
        },
    }
    value = definition().deserialize(
        {"actions": {"availability.lookup": runtime, "summary.send": post_call}}
    )
    assert set(value.actions) == {"availability.lookup", "summary.send"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", True),
        ("version", 1),
        ("integration_id", "00000000-0000-0000-0000-000000000001"),
        ("requires_availability_proof", True),
        ("job_id", "job-1"),
    ],
)
def test_frozen_action_rejects_excluded_legacy_fields(
    field: str, value: object
) -> None:
    with pytest.raises(InvalidComponentValue):
        validate(runtime_action(**{field: value}))


def test_http_execution_has_no_semantic_type_discriminator() -> None:
    action = runtime_action()
    action["execution"] = {**action["execution"], "type": "http"}
    with pytest.raises(InvalidComponentValue):
        validate(action)


@pytest.mark.parametrize(
    "bindings",
    [
        ({"stay.check_in": "check_in"}),
        ({"check_in": "business.stay.check_in"}),
        ({"check_in": "stay.check_in", "check_out": "stay.check_in"}),
        ({"missing": "stay.check_in"}),
    ],
)
def test_bindings_are_agent_input_to_unique_canonical_path(bindings) -> None:
    with pytest.raises(InvalidComponentValue):
        validate(runtime_action(bindings=bindings))


def test_date_range_requires_reachable_required_date_bindings() -> None:
    action = runtime_action(bindings={"check_in": "stay.check_in"})
    with pytest.raises(InvalidComponentValue, match="stay.check_out"):
        validate(action)

    schema = dict(action["agent_input_schema"])
    schema["properties"] = {
        **schema["properties"],
        "check_out": {"type": "string"},
    }
    with pytest.raises(InvalidComponentValue, match="format: date"):
        validate(runtime_action(agent_input_schema=schema))


@pytest.mark.parametrize(
    "expression",
    ["credential.api_key", "secret.value", "integration_secret.token"],
)
def test_mapping_templates_reject_secret_contexts(expression: str) -> None:
    action = runtime_action()
    action["execution"] = {
        **action["execution"],
        "request": {"codec": "json", "mapping": {"$expr": expression}},
    }
    with pytest.raises(InvalidComponentValue, match="expression context"):
        validate(action)


@pytest.mark.parametrize("root", ["inputs", "business", "metadata"])
def test_runtime_request_accepts_only_runtime_request_namespaces(root: str) -> None:
    action = runtime_action()
    action["execution"] = {
        **action["execution"],
        "request": {"codec": "json", "mapping": {"$expr": f"{root}.value"}},
    }
    validate(action)


@pytest.mark.parametrize("root", ["response", "call", "agent"])
def test_runtime_request_rejects_non_runtime_namespaces(root: str) -> None:
    action = runtime_action()
    action["execution"] = {
        **action["execution"],
        "request": {"codec": "json", "mapping": {"$expr": f"{root}.value"}},
    }
    with pytest.raises(InvalidComponentValue, match="expression context"):
        validate(action)


@pytest.mark.parametrize("field", ["status_code", "content_type", "body"])
def test_response_mapping_accepts_response_namespace(field: str) -> None:
    action = runtime_action()
    action["execution"] = {
        **action["execution"],
        "response": {
            "codec": "json",
            "mapping": {"$expr": f"response.{field}"},
        },
    }
    validate(action)


@pytest.mark.parametrize("root", ["business", "inputs"])
def test_response_mapping_rejects_request_namespaces(root: str) -> None:
    action = runtime_action()
    action["execution"] = {
        **action["execution"],
        "response": {"codec": "json", "mapping": {"$expr": f"{root}.value"}},
    }
    with pytest.raises(InvalidComponentValue, match="expression context"):
        validate(action)


@pytest.mark.parametrize("root", ["call", "agent", "inputs"])
def test_post_call_request_accepts_only_post_call_namespaces(root: str) -> None:
    action = post_call_action()
    action["execution"] = {
        **action["execution"],
        "request": {"codec": "json", "mapping": {"$expr": f"{root}.value"}},
    }
    validate(action)


@pytest.mark.parametrize("root", ["business", "metadata"])
def test_post_call_request_rejects_runtime_only_namespaces(root: str) -> None:
    action = post_call_action()
    action["execution"] = {
        **action["execution"],
        "request": {"codec": "json", "mapping": {"$expr": f"{root}.value"}},
    }
    with pytest.raises(InvalidComponentValue, match="expression context"):
        validate(action)


@pytest.mark.parametrize("root", ["secret", "credential", "integration_secret"])
@pytest.mark.parametrize("location", ["runtime_request", "response", "post_call"])
def test_secret_namespaces_are_rejected_in_every_mapping_location(
    root: str, location: str
) -> None:
    action = post_call_action() if location == "post_call" else runtime_action()
    execution = action["execution"]
    field = "response" if location == "response" else "request"
    action["execution"] = {
        **execution,
        field: {"codec": "json", "mapping": {"$expr": f"{root}.value"}},
    }
    with pytest.raises(InvalidComponentValue, match="expression context"):
        validate(action)


def test_agent_and_result_json_schemas_are_structurally_valid() -> None:
    with pytest.raises(InvalidComponentValue, match="JSON Schema"):
        validate(runtime_action(agent_input_schema={"type": "not-a-json-schema-type"}))

    with pytest.raises(InvalidComponentValue, match="JSON Schema"):
        validate(runtime_action(result_schema={"type": "not-a-json-schema-type"}))

    with pytest.raises(InvalidComponentValue, match="local JSON Schema"):
        validate(
            runtime_action(
                agent_input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"guest": {"$ref": "https://example.com/guest"}},
                },
                bindings={},
                input_constraints=[],
            )
        )


def test_static_authoring_validation_needs_no_runtime_values_or_network() -> None:
    value = validate(runtime_action())
    assert value.actions["availability.lookup"].phase == "runtime"
