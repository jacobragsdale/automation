import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from schedules import initialize_schedules, register_schedules


async def run_scheduler() -> None:
    scheduler = AsyncIOScheduler()
    register_schedules(scheduler)
    await initialize_schedules(scheduler)

    scheduler.start()
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    asyncio.run(run_scheduler())
