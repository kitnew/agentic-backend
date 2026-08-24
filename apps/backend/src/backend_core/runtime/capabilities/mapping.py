from collections.abc import Mapping

from contracts.http_operation import ExpressionNode, MappingTemplate


def evaluate_template(template: MappingTemplate, context: Mapping[str, object]) -> object:
    from backend_core.runtime.capabilities.domain import JsonataMappingEngine

    engine = JsonataMappingEngine()

    def visit(value: object) -> object:
        if isinstance(value, ExpressionNode):
            return engine.evaluate(value.expr, dict(context))
        if isinstance(value, dict):
            if set(value) == {"$expr"} and isinstance(value["$expr"], str):
                return engine.evaluate(value["$expr"], dict(context))
            return {key: visit(item) for key, item in value.items()}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    return visit(template)


def evaluate_query(query: dict[str, MappingTemplate] | None, context: Mapping[str, object]) -> dict[str, object] | None:
    if query is None:
        return None
    value = evaluate_template(query, context)
    if not isinstance(value, dict):
        raise TypeError("HTTP query template must evaluate to an object")
    return {key: item for key, item in value.items() if item is not None}
