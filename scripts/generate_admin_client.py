import os
import shutil
import subprocess
import sys
from argparse import ArgumentParser
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.export_admin_openapi import export_admin_openapi

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "packages/admin-client/openapi/admin.openapi.json"
GENERATED = ROOT / "packages/admin-client/src/admin_client/generated"


def snapshot(directory: Path) -> Mapping[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and not {"__pycache__", ".ruff_cache"}.intersection(path.parts)
        and path.suffix != ".pyc"
    }


def generate(schema: Path, output: Path, cache: Path) -> None:
    environment = os.environ.copy()
    environment["RUFF_CACHE_DIR"] = str(cache)
    subprocess.run(
        [
            "uvx",
            "--from",
            "openapi-python-client==0.29.0",
            "openapi-python-client",
            "generate",
            "--path",
            str(schema),
            "--meta",
            "none",
            "--output-path",
            str(output),
            "--fail-on-warning",
        ],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def drift() -> list[str]:
    with TemporaryDirectory(prefix="admin-client-check-") as temporary:
        temp = Path(temporary)
        schema = temp / "admin.openapi.json"
        generated = temp / "generated"
        export_admin_openapi(schema)
        generate(schema, generated, temp / "ruff-cache")
        differences = []
        if not SCHEMA.exists() or schema.read_bytes() != SCHEMA.read_bytes():
            differences.append(str(SCHEMA.relative_to(ROOT)))
        if not GENERATED.exists() or snapshot(generated) != snapshot(GENERATED):
            differences.append(str(GENERATED.relative_to(ROOT)))
        return differences


def regenerate() -> None:
    export_admin_openapi()
    with TemporaryDirectory(prefix="admin-client-generate-") as temporary:
        temp = Path(temporary)
        generated = temp / "generated"
        generate(SCHEMA, generated, temp / "ruff-cache")
        if GENERATED.exists():
            shutil.rmtree(GENERATED)
        shutil.copytree(generated, GENERATED)


def main() -> int:
    parser = ArgumentParser(description="Generate the Backend Admin API client")
    parser.add_argument("--check", action="store_true")
    if not parser.parse_args().check:
        regenerate()
        return 0
    differences = drift()
    if differences:
        print(
            "Generated Admin client is stale: " + ", ".join(differences),
            file=sys.stderr,
        )
        print(
            "Run: uv run python -m scripts.generate_admin_client",
            file=sys.stderr,
        )
        return 1
    print("Generated Admin client is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
