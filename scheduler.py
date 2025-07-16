from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

from handlers import run_morning_lights_handler


async def run_weekday_hello():
    sched = AsyncIOScheduler()
    sched.add_job(run_morning_lights_handler, trigger="cron", day_of_week="mon-fri", hour=6, minute=45)
    sched.start()
    try:
        # Keep the scheduler running
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()


if __name__ == "__main__":
    asyncio.run(run_weekday_hello())
