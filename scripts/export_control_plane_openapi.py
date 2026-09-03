from argparse import ArgumentParser
from contextlib import asynccontextmanager
from json import dumps
from pathlib import Path
from re import findall
from typing import Any

from control_plane.interfaces.http import create_http_app

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "packages/admin-client/openapi/control-plane.openapi.json"
DEFAULT_BROWSER_OUTPUT = (
    ROOT / "packages/admin-client/openapi/control-plane-browser.openapi.json"
)


class SchemaLifecycle:
    @asynccontextmanager
    async def lifespan(self, _app):
        yield


def control_plane_openapi() -> dict[str, Any]:
    app = create_http_app(
        SchemaLifecycle(),  # type: ignore[arg-type]
        components=object(),  # type: ignore[arg-type]
        managed_resources=object(),  # type: ignore[arg-type]
    )
    schema = app.openapi()
    # FastAPI does not carry parameters declared by an APIRouter prefix into
    # the exported operation schema. Keep the generated client valid.
    for path, operations in schema["paths"].items():
        names = findall(r"\{([^}]+)\}", path)
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            parameters = operation.setdefault("parameters", [])
            declared = {item.get("name") for item in parameters}
            for name in names:
                if name not in declared:
                    parameters.append(
                        {
                            "in": "path",
                            "name": name,
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    )
    return schema


def export_control_plane_openapi(output: Path = DEFAULT_OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = control_plane_openapi()
    output.write_bytes((dumps(schema, indent=2, sort_keys=True) + "\n").encode())
    browser_schema = {
        **schema,
        "paths": {
            path.replace("/v1/", "/control-plane/"): operation
            for path, operation in schema["paths"].items()
            if path.startswith("/v1/")
        },
    }
    DEFAULT_BROWSER_OUTPUT.write_bytes(
        (dumps(browser_schema, indent=2, sort_keys=True) + "\n").encode()
    )


def main() -> None:
    parser = ArgumentParser(
        description="Export the Control Plane management OpenAPI schema"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    export_control_plane_openapi(parser.parse_args().output)


if __name__ == "__main__":
    main()
