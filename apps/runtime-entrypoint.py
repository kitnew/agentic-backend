import sys
from os import environ, execvpe, getuid, initgroups, setgid, setuid
from pathlib import Path
from pwd import getpwnam


def load_mounted_secrets() -> None:
    directory = Path("/run/secrets")
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                environ[path.name.upper()] = value


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("runtime entrypoint requires a command")
    if getuid() == 0:
        load_mounted_secrets()
        app = getpwnam("app")
        initgroups(app.pw_name, app.pw_gid)
        setgid(app.pw_gid)
        setuid(app.pw_uid)
    execvpe(sys.argv[1], sys.argv[1:], environ)


if __name__ == "__main__":
    main()
