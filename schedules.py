from apscheduler.schedulers.asyncio import AsyncIOScheduler

from domains.lights import handler as lights_handler
from domains.nextdns import handler as nextdns_handler

_MORNING_BLOCK_DOMAINS = [
    "reddit.com",
    "youtube.com",
    "news.ycombinator.com",
    "wsj.com",
    "nytimes.com",
    "nypost.com",
    "bbc.com",
    "bbc.co.uk",
    "apnews.com",
    "reuters.com",
    "theverge.com",
    "arstechnica.com",
    "businessinsider.com",
    "aljazeera.com",
]


async def block_morning_sites() -> None:
    await nextdns_handler.create_focus_session(
        duration_minutes=120,
        domains=_MORNING_BLOCK_DOMAINS,
        category_ids=[],
        service_ids=[],
        safe_search=False,
        youtube_restricted_mode=False,
        block_bypass=False,
        reason="Morning focus block",
    )


def register_schedules(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        lights_handler.run_night_scene,
        trigger="cron",
        hour=20,
        minute=0,
        id="lights_night_scene",
        replace_existing=True,
    )
    scheduler.add_job(
        block_morning_sites,
        trigger="cron",
        hour=6,
        minute=0,
        id="nextdns_morning_block",
        replace_existing=True,
    )
