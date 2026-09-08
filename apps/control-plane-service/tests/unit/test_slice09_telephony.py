from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from control_plane.domain.managed_resources import normalize_e164
from control_plane.interfaces.http.app import (
    HandoffDestinationCreate,
    HandoffDestinationUpdate,
    InboundRouteResponse,
    PhoneNumberAssignmentCreate,
    create_http_app,
)
from pydantic import ValidationError


class _Lifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


def test_phone_normalization_and_validation() -> None:
    assert normalize_e164(" +421 900-111-111 ") == "+421900111111"
    with pytest.raises(ValueError):
        normalize_e164("00421 900 111 111")


def test_target_request_bodies_cannot_override_ownership_or_identity() -> None:
    assert PhoneNumberAssignmentCreate(phone_number="+421900111111").model_dump() == {
        "phone_number": "+421900111111"
    }
    assert HandoffDestinationCreate(
        key="front_desk",
        description="Front desk",
        phone_number="+421900222222",
    ).model_dump() == {
        "key": "front_desk",
        "description": "Front desk",
        "phone_number": "+421900222222",
    }
    for model, value in (
        (PhoneNumberAssignmentCreate, {"phone_number": "+421900111111", "tenant_id": "other"}),
        (
            HandoffDestinationCreate,
            {
                "key": "front_desk",
                "description": "Front desk",
                "phone_number": "+421900222222",
                "tenant_id": "other",
            },
        ),
        (
            HandoffDestinationUpdate,
            {
                "description": "Reception",
                "phone_number": "+421900333333",
                "key": "changed",
            },
        ),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(value)


def test_openapi_exposes_only_target_telephony_management_contract() -> None:
    schema = create_http_app(
        cast(Any, _Lifecycle()), telephony=cast(Any, object())
    ).openapi()
    paths = schema["paths"]
    assignment = "/management/v1/tenants/{tenant_id}/telephony/phone-number-assignments"
    destination = "/management/v1/tenants/{tenant_id}/telephony/handoff-destinations"

    assert set(paths[assignment]) == {"get", "post"}
    assert set(paths[f"{assignment}/{{id}}"] ) == {"get"}
    assert f"{assignment}/{{id}}/enable" in paths
    assert f"{assignment}/{{id}}/disable" in paths
    assert set(paths[destination]) == {"get", "post"}
    assert set(paths[f"{destination}/{{id}}"] ) == {"get", "put"}
    assert f"{destination}/{{id}}/enable" in paths
    assert f"{destination}/{{id}}/disable" in paths
    assert not any("/internal/v1/telephony/inbound-route" == path for path in paths)
    assert not any("/internal/v1/telephony/phone-number-assignments" in path for path in paths)
    assert not any("/v1/managed-resources/phone-number-assignments" in path for path in paths)
    assert not any("/v1/managed-resources/handoff-destinations" in path for path in paths)

    models = schema["components"]["schemas"]
    assert set(models["PhoneNumberAssignmentCreate"]["properties"]) == {"phone_number"}
    assert set(models["PhoneNumberAssignmentResponse"]["properties"]) == {
        "id", "tenant_id", "phone_number", "enabled", "created_at", "updated_at"
    }
    assert set(models["HandoffDestinationUpdate"]["properties"]) == {
        "description", "phone_number"
    }
    assert "TenantConfiguration" not in models


def test_inbound_route_transport_is_semantic_and_not_mounted_yet() -> None:
    assert set(InboundRouteResponse.model_fields) == {
        "tenant_id",
        "phone_number",
        "route_version",
    }
