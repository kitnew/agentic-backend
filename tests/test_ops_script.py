import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "scripts" / "ops.sh"
COMPOSE = ROOT / "infrastructure" / "compose"


@pytest.fixture(autouse=True)
def deployment_env_files() -> Iterator[None]:
    created: list[Path] = []
    for environment in ("staging", "production"):
        path = COMPOSE / f".env.{environment}"
        if not path.exists():
            path.write_text((COMPOSE / f".env.{environment}.example").read_text())
            created.append(path)
    yield
    for path in created:
        path.unlink(missing_ok=True)


def fake_docker(tmp_path: Path) -> dict[str, str]:
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case " $* " in
  *" config --services "*)
    printf '%s\\n' backend control-plane-service postgres caddy livekit-egress
    ;;
  *" ps --status running --services "*)
    printf '%s\\n' postgres redis nats minio backend control-plane-service job-worker voice-agent admin-web livekit livekit-egress livekit-sip caddy
    ;;
  *" exec -T redis redis-cli ping "*)
    printf 'PONG\\n'
    ;;
  *" exec -T nats wget "*)
    printf 'ok\\n'
    ;;
  *" exec -T postgres sh -ec printf "*)
    printf 'backend'
    ;;
  *"SELECT 1 FROM pg_database "*)
    printf '1\\n'
    ;;
  *" pg_catalog.pg_tables "*)
    printf '0\\n'
    ;;
  *" config --environment "*)
    printf 'BACKUP_DIR=%s\\n' "$FAKE_BACKUP_DIR"
    ;;
  *" exec "*" pg_dump "*)
    printf 'fake-postgres-custom-archive'
    ;;
esac
"""
    )
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    return {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "DOCKER_LOG": str(log),
        "FAKE_BACKUP_DIR": str(tmp_path / "backups"),
        "BACKUP_DIR": str(tmp_path / "backups"),
    }


def run_ops(
    tmp_path: Path,
    *arguments: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(OPS), *arguments],
        cwd=tmp_path,
        env=fake_docker(tmp_path),
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def docker_log(tmp_path: Path) -> str:
    path = tmp_path / "docker.log"
    return path.read_text() if path.exists() else ""


def test_config_resolves_staging_to_canonical_compose_arguments(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "staging", "config")

    assert result.returncode == 0, result.stderr
    commands = docker_log(tmp_path)
    compose_prefix = (
        f"compose --env-file {COMPOSE / '.env.staging'} "
        f"-f {COMPOSE / 'docker-compose.yml'} "
        f"-f {COMPOSE / 'docker-compose.deploy.yml'}"
    )
    assert f"{compose_prefix} config --quiet" in commands
    assert f"{compose_prefix} config --services" in commands
    assert f"{compose_prefix} config --volumes" in commands


def test_config_does_not_print_resolved_secrets_by_default() -> None:
    source = OPS.read_text()

    assert "config [--show-secrets]" in source
    assert '[[ "$1" == "--show-secrets" ]]' in source


def test_help_lists_database_and_operator_commands(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "--help")

    assert result.returncode == 0
    assert "db-init" in result.stderr
    assert "db-reset [--yes]" in result.stderr
    assert "doctor" in result.stderr
    assert "release" in result.stderr


def test_db_init_starts_postgres_and_runs_backend_bootstrap(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "staging", "db-init")

    assert result.returncode == 0, result.stderr
    commands = docker_log(tmp_path)
    postgres = commands.index("up -d --wait --wait-timeout 180 postgres")
    bootstrap = commands.index("python -m backend_core.platform.database.bootstrap")
    assert postgres < bootstrap
    assert (
        "run --rm --build --no-deps --user root --entrypoint /bin/sh backend -ec"
        in commands
    )


def test_update_bootstraps_empty_database_and_ignores_optional_checks(
    tmp_path: Path,
) -> None:
    result = run_ops(tmp_path, "staging", "update")

    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert (
        "No Alembic revisions or application tables found; bootstrapping schema."
        in output
    )
    assert "[WARN] Prometheus [OPTIONAL]" in output
    assert "Result: healthy (optional checks degraded)" in output
    commands = docker_log(tmp_path)
    bootstrap = commands.index("python -m backend_core.platform.database.bootstrap")
    optional_start = commands.index(
        "up -d --remove-orphans prometheus tempo otel-collector grafana"
    )
    stack_start = commands.index("up -d --wait --wait-timeout 180 --remove-orphans")
    assert bootstrap < optional_start < stack_start


def test_production_db_reset_requires_non_tty_confirmation(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "production", "db-reset")

    assert result.returncode != 0
    assert (
        "production db-reset requires interactive confirmation or --yes"
        in result.stderr
    )
    assert (
        "stop backend control-plane-service job-worker voice-agent"
        not in docker_log(tmp_path)
    )


def test_invalid_environment_never_invokes_docker(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "development", "status")

    assert result.returncode != 0
    assert "environment must be staging or production" in result.stderr
    assert docker_log(tmp_path) == ""


def test_logs_rejects_unknown_service(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "staging", "logs", "unknown")

    assert result.returncode != 0
    assert "unknown service" in result.stderr
    assert "logs --tail" not in docker_log(tmp_path)


def test_backup_uses_environment_directory_and_atomic_dump_name(tmp_path: Path) -> None:
    result = run_ops(tmp_path, "staging", "backup")

    assert result.returncode == 0, result.stderr
    dump = Path(result.stdout.strip())
    assert dump.parent == tmp_path / "backups" / "staging" / "postgres"
    assert dump.suffix == ".dump"
    assert dump.read_bytes() == b"fake-postgres-custom-archive"
    assert not list(dump.parent.glob("*.tmp"))


def test_production_restore_requires_confirmation_unless_yes(tmp_path: Path) -> None:
    backup = tmp_path / "database.dump"
    backup.write_bytes(b"fake-postgres-custom-archive")

    rejected = run_ops(
        tmp_path, "production", "restore", str(backup), input_text="no\n"
    )
    assert rejected.returncode != 0
    assert (
        "production restore requires interactive confirmation or --yes"
        in rejected.stderr
    )
    assert "pg_restore --clean" not in docker_log(tmp_path)

    accepted = run_ops(tmp_path, "production", "restore", str(backup), "--yes")
    assert accepted.returncode == 0, accepted.stderr
    commands = docker_log(tmp_path)
    backend_stop = commands.index("stop backend control-plane-service")
    writers_stop = commands.index("stop job-worker voice-agent")
    restore = commands.index("pg_restore --clean --if-exists --exit-on-error")
    assert "run --rm --no-deps --user root --entrypoint /bin/sh backend -ec" in commands
    migrate = commands.index("alembic -c apps/backend/alembic.ini upgrade head")
    restart = commands.index("up -d --wait --wait-timeout 180 --remove-orphans")
    assert backend_stop < writers_stop < restore < migrate < restart


def test_script_never_uses_derived_container_names_or_volume_deletion() -> None:
    source = OPS.read_text()

    assert "docker restart" not in source
    assert "down -v" not in source
    assert "container_name" not in source


def test_release_uses_fast_forward_only_git_update_and_reexecutes_new_script() -> None:
    source = OPS.read_text()

    assert 'git -C "$ROOT" fetch --prune' in source
    assert 'git -C "$ROOT" pull --ff-only' in source
    assert 'exec "$ROOT/scripts/ops.sh" "$ENVIRONMENT" update' in source
    assert "git reset --hard" not in source
    assert "git clean -fd" not in source
    assert "git checkout -- ." not in source
