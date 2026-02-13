from apscheduler.schedulers.asyncio import AsyncIOScheduler

from domains.lights import handler as lights_handler


def register_schedules(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        lights_handler.run_night_scene,
        trigger="cron",
        hour=20,
        minute=0,
        id="lights_night_scene",
        replace_existing=True,
    )
