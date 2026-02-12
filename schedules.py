from apscheduler.schedulers.asyncio import AsyncIOScheduler

from domains.lights import handler as lights_handler

SUNSET_FADE_PLANNER_JOB_ID = "sunset_fade_planner"


def register_schedules(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        lights_handler.run_morning_scene,
        trigger="cron",
        day_of_week="mon-fri",
        hour=6,
        minute=30,
        id="lights_morning_scene",
        replace_existing=True,
    )
    scheduler.add_job(
        lights_handler.run_night_scene,
        trigger="cron",
        hour=20,
        minute=0,
        id="lights_night_scene",
        replace_existing=True,
    )
    scheduler.add_job(
        lights_handler.refresh_sunset_fade_jobs,
        trigger="cron",
        hour=12,
        minute=5,
        id=SUNSET_FADE_PLANNER_JOB_ID,
        replace_existing=True,
        args=[scheduler],
    )


async def initialize_schedules(scheduler: AsyncIOScheduler) -> None:
    await lights_handler.refresh_sunset_fade_jobs(scheduler)
