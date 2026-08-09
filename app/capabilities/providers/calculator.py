from decimal import Decimal, DecimalException, localcontext

from app.capabilities.schemas import (
    CalculatorRequest,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from app.tenants.schemas import TenantContext


class CalculatorProvider:
    provider_name = "calculator"

    def execute(
        self,
        tenant_context: TenantContext,
        capability_request: CapabilityRequest,
    ) -> CapabilityResult:
        request = CalculatorRequest.model_validate(capability_request.input)
        operands = [Decimal(value) for value in request.operands]
        if request.operation == "divide" and operands[1].is_zero():
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=self.provider_name,
                error="division_by_zero",
            )

        try:
            with localcontext() as context:
                context.prec = 28
                result = self._calculate(request.operation, operands)
        except DecimalException:
            return CapabilityResult(
                name=capability_request.name,
                status=CapabilityStatus.FAILED,
                provider=self.provider_name,
                error="calculation_failed",
            )
        return CapabilityResult(
            name=capability_request.name,
            status=CapabilityStatus.SUCCESS,
            provider=self.provider_name,
            output={
                "status": "success",
                "operation": request.operation,
                "operands": request.operands,
                "result": str(result),
            },
        )

    @staticmethod
    def _calculate(operation: str, operands: list[Decimal]) -> Decimal:
        if operation == "add":
            return sum(operands, Decimal("0"))
        if operation == "multiply":
            result = Decimal("1")
            for operand in operands:
                result *= operand
            return result
        if operation == "subtract":
            return operands[0] - operands[1]
        if operation == "divide":
            return operands[0] / operands[1]
        return operands[0] * operands[1] / Decimal("100")
