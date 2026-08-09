from argparse import ArgumentParser
from json import dumps
from pathlib import Path
from typing import Any

from backend_core.interfaces.http.router import (  # type: ignore[import-untyped]
    admin_router,
)
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "packages/admin-client/openapi/admin.openapi.json"


def admin_openapi() -> dict[str, Any]:
    app = FastAPI(title="Agent Platform Admin API", version="0.1.0")
    app.include_router(admin_router)
    return app.openapi()


def render_admin_openapi() -> bytes:
    return (dumps(admin_openapi(), indent=2, sort_keys=True) + "\n").encode()


def export_admin_openapi(output: Path = DEFAULT_OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render_admin_openapi())


def main() -> None:
    parser = ArgumentParser(description="Export the Backend Admin OpenAPI schema")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    export_admin_openapi(parser.parse_args().output)


if __name__ == "__main__":
    main()
