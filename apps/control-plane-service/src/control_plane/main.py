import logging

import uvicorn

from control_plane.settings import Settings


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings()  # type: ignore[call-arg]
    uvicorn.run(
        "control_plane.bootstrap:create_app",
        factory=True,
        host=settings.http_host,
        port=settings.http_port,
    )


if __name__ == "__main__":
    main()
