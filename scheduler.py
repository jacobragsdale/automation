import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # pyright: ignore[reportMissingTypeStubs]

from schedules import SCHEDULER_TIMEZONE, register_schedules


async def run_scheduler() -> None:
    scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
    register_schedules(scheduler)

    scheduler.start()
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(run_scheduler())
