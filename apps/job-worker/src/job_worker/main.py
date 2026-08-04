import asyncio
import logging

from job_worker.worker import Settings, run_worker


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(Settings.from_env()))


if __name__ == "__main__":
    main()
