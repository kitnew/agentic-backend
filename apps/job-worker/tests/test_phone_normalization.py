import pytest
from job_worker.worker import ExecutionError, HttpExecutionHandler, _bind_input


def normalize(phone: str, country: str | None = None) -> str:
    definition = {
        "agent_input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string", "minLength": 1},
                "phone_country": {"type": "string"},
            },
            "required": ["phone_number"],
            "additionalProperties": False,
        },
        "bindings": {"phone_number": "guest.phone"},
    }
    args = {"phone_number": phone}
    if country is not None:
        args["phone_country"] = country
    return _bind_input(definition, args)[1]["guest"]["phone"]  # type: ignore[index,return-value]


@pytest.mark.parametrize(
    ("phone", "country", "expected"),
    [
        ("0940583417", "SK", "+421940583417"),
        ("777123456", "CZ", "+420777123456"),
        ("+421940583417", None, "+421940583417"),
        ("+420777123456", None, "+420777123456"),
        ("00421940583417", None, "+421940583417"),
    ],
)
def test_phone_normalizes_to_e164(
    phone: str, country: str | None, expected: str
) -> None:
    assert normalize(phone, country) == expected


def test_national_phone_without_country_requests_country() -> None:
    with pytest.raises(ExecutionError) as error:
        normalize("0940583417")
    assert error.value.code == "phone_country_required"


def test_invalid_phone_with_country_is_rejected() -> None:
    with pytest.raises(ExecutionError) as error:
        normalize("123", "SK")
    assert error.value.code == "invalid_canonical_field"


def test_caller_sip_number_remains_valid_without_country() -> None:
    # Existing mappings can continue using canonical caller metadata directly.
    payload = HttpExecutionHandler._evaluate_template(
        {"caller_phone": {"$expr": "metadata.caller_phone"}},
        {"metadata": {"caller_phone": "+421940583417"}},
    )
    assert payload == {"caller_phone": "+421940583417"}


def test_reservation_mapping_receives_normalized_phone() -> None:
    definition = {
        "agent_input_schema": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string"},
                "phone_country": {"type": "string"},
            },
            "required": ["phone_number"],
        },
        "bindings": {"phone_number": "guest.phone"},
    }
    inputs, business = _bind_input(
        definition, {"phone_number": "0940583417", "phone_country": "SK"}
    )
    payload = HttpExecutionHandler._evaluate_template(
        {"reservation_phone": {"$expr": "business.guest.phone"}},
        {"inputs": inputs, "business": business, "metadata": {}},
    )
    assert payload == {"reservation_phone": "+421940583417"}
