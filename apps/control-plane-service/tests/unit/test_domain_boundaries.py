import builtins
import importlib


def test_domain_imports_without_infrastructure_dependencies(monkeypatch) -> None:
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"fastapi", "nats", "sqlalchemy"}:
            raise AssertionError(f"domain imported infrastructure dependency: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    importlib.import_module("control_plane.domain")
