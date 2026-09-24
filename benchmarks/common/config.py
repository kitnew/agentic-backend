from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    path = ROOT / ".env.benchmark.local"
    if not path.is_file():
        raise SystemExit(f"Create {path} from .env.example")
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, separator, value = line.partition("=")
            if not separator:
                raise ValueError(f"Invalid env line: {key}")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def required(config: dict[str, str], *names: str) -> tuple[str, ...]:
    missing = [
        name
        for name in names
        if not config.get(name)
        or config[name].startswith("YOUR_")
        or "YOUR-" in config[name]
    ]
    if missing:
        raise SystemExit("Missing benchmark configuration: " + ", ".join(missing))
    return tuple(config[name] for name in names)
