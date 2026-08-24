from backend_core.runtime.capabilities.mapping import evaluate_template
from contracts import HttpOperation


def test_mapping_template_preserves_literals_and_evaluates_nested_expressions() -> None:
    operation = HttpOperation.model_validate(
        {
            "connection": "previo",
            "method": "POST",
            "timeout_seconds": 10,
            "request": {
                "codec": "json",
                "mapping": {
                    "guest": {"name": {"$expr": "business.guest.name"}},
                    "rooms": [{"$expr": "business.rooms"}],
                    "literal": False,
                    "empty": None,
                },
            },
        }
    )

    assert evaluate_template(
        operation.request.mapping,
        {"business": {"guest": {"name": "Ada"}, "rooms": [1, 2]}},
    ) == {"guest": {"name": "Ada"}, "rooms": [[1, 2]], "literal": False, "empty": None}
