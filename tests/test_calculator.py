import pytest

from app.capabilities.router import CapabilityRouter
from app.capabilities.schemas import CapabilityRequest, CapabilityStatus
from app.tenants.loader import TenantConfigLoader


@pytest.fixture
def router():
    return CapabilityRouter()


@pytest.fixture
def tenant():
    return TenantConfigLoader().load("demo_restaurant")


@pytest.mark.parametrize(
    ("operation", "operands", "result"),
    [
        ("add", ["1.1", "2.2", "-0.3"], "3.0"),
        ("subtract", ["-2.5", "3"], "-5.5"),
        ("multiply", ["55", "3"], "165"),
        ("divide", ["7.5", "2"], "3.75"),
        ("percentage", ["200", "12.5"], "25.0"),
    ],
)
def test_calculator_operations(router, tenant, operation, operands, result):
    response = router.execute(
        tenant,
        CapabilityRequest(
            name="calculator.calculate",
            input={"operation": operation, "operands": operands},
        ),
    )

    assert response.status == CapabilityStatus.SUCCESS
    assert response.provider == "calculator"
    assert response.output == {
        "status": "success",
        "operation": operation,
        "operands": operands,
        "result": result,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "power", "operands": ["2", "3"]},
        {"operation": "add", "operands": ["not-a-number", "1"]},
        {"operation": "add", "operands": ["NaN", "1"]},
        {"operation": "add", "operands": [1, "2"]},
        {"operation": "add", "operands": ["1"]},
        {"operation": "multiply", "operands": ["1"] * 11},
        {"operation": "subtract", "operands": ["1", "2", "3"]},
        {"operation": "divide", "operands": ["1", "2", "3"]},
        {"operation": "percentage", "operands": ["1", "2", "3"]},
    ],
)
def test_calculator_rejects_invalid_requests(router, tenant, payload):
    response = router.execute(
        tenant, CapabilityRequest(name="calculator.calculate", input=payload)
    )

    assert response.status == CapabilityStatus.SKIPPED
    assert response.provider == "validation"
    assert response.error == "invalid_calculator_request"


def test_calculator_rejects_division_by_zero(router, tenant):
    response = router.execute(
        tenant,
        CapabilityRequest(
            name="calculator.calculate",
            input={"operation": "divide", "operands": ["1", "0"]},
        ),
    )

    assert response.status == CapabilityStatus.FAILED
    assert response.provider == "calculator"
    assert response.error == "division_by_zero"


def test_calculator_ignores_backend_execution_context(router, tenant):
    response = router.execute(
        tenant,
        CapabilityRequest(
            name="calculator.calculate",
            input={
                "operation": "multiply",
                "operands": ["3.5", "2"],
                "tenant_id": "demo_restaurant",
                "message_id": "message-1",
                "conversation_id": "conversation-1",
                "source_channel": "voice",
            },
        ),
    )

    assert response.status == CapabilityStatus.SUCCESS
    assert response.output["result"] == "7.0"
