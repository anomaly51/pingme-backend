import asyncio
import logging

from app.services.reminder_service import run_reminder_scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_reminder_scheduler())


if __name__ == "__main__":
    main()
