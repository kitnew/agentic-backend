from __future__ import annotations

import shutil
import sys
from argparse import ArgumentParser
from json import dumps, loads
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_control_plane_openapi import export_control_plane_openapi
from scripts.generate_admin_client import generate, snapshot

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "packages/admin-client/openapi/control-plane.openapi.json"
GENERATED = ROOT / "packages/admin-client/src/admin_client/control_plane"


def generator_schema(path: Path) -> None:
    document = loads(path.read_text())
    schemas = document["components"]["schemas"]
    for name, schema in schemas.items():
        schema["title"] = name.replace("-", "_")
    for name in ("MappingTemplate-Input", "MappingTemplate-Output"):
        schemas[name] = {
            "title": name.replace("-", "_"),
            "type": "object",
            "additionalProperties": True,
        }
    for name in ("ActionsDefinition-Input", "ActionsDefinition-Output"):
        actions = schemas[name]["properties"]["actions"]
        actions["additionalProperties"] = next(
            iter(actions.pop("patternProperties").values())
        )
        actions.pop("propertyNames", None)
    path.write_text(dumps(document, indent=2, sort_keys=True) + "\n")


def drift() -> list[str]:
    with TemporaryDirectory(prefix="control-plane-client-check-") as temporary:
        temp = Path(temporary)
        schema = temp / "control-plane.openapi.json"
        generated = temp / "generated"
        export_control_plane_openapi(schema)
        canonical = schema.read_bytes()
        generator_schema(schema)
        generate(schema, generated, temp / "ruff-cache")
        differences = []
        if not SCHEMA.exists() or canonical != SCHEMA.read_bytes():
            differences.append(str(SCHEMA.relative_to(ROOT)))
        if not GENERATED.exists() or snapshot(generated) != snapshot(GENERATED):
            differences.append(str(GENERATED.relative_to(ROOT)))
        return differences


def regenerate() -> None:
    export_control_plane_openapi()
    with TemporaryDirectory(prefix="control-plane-client-generate-") as temporary:
        temp = Path(temporary)
        generated = temp / "generated"
        schema = temp / "control-plane.openapi.json"
        shutil.copyfile(SCHEMA, schema)
        generator_schema(schema)
        generate(schema, generated, temp / "ruff-cache")
        if GENERATED.exists():
            shutil.rmtree(GENERATED)
        shutil.copytree(generated, GENERATED)


def main() -> int:
    parser = ArgumentParser(description="Generate the Control Plane Management client")
    parser.add_argument("--check", action="store_true")
    if not parser.parse_args().check:
        regenerate()
        return 0
    differences = drift()
    if differences:
        print(
            "Generated Control Plane client is stale: " + ", ".join(differences),
            file=sys.stderr,
        )
        return 1
    print("Generated Control Plane client is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
