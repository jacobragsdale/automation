from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from domains.lights.repository import LightsRepository
from domains.weather.repository import WeatherRepository

lights_repository = LightsRepository()
weather_repository = WeatherRepository()

COLOR_MAP: dict[str, tuple[int, int, int]] = {
    "red": (0, 100, 100),
    "orange": (30, 100, 100),
    "yellow": (55, 100, 100),
    "green": (120, 100, 100),
    "blue": (220, 100, 100),
    "indigo": (250, 100, 100),
    "violet": (275, 100, 100),
    "white": (0, 0, 100),
    "candle light": (30, 40, 100),
}

SUNSET_FADE_LOCATION = "Nashville, TN"
SUNSET_FADE_STEPS = 20
SUNSET_FADE_DURATION_MINUTES = 60
SUNSET_FADE_START_HSV = (30, 40, 100)
SUNSET_FADE_END_HSV = (0, 100, 100)
SUNSET_FADE_JOB_PREFIX = "sunset_fade_step_"


def _normalize_color(color: str) -> str:
    return " ".join(color.strip().lower().replace("-", " ").split())


def _interpolate_hsv(
    step_index: int,
    total_steps: int,
    start_hsv: tuple[int, int, int],
    end_hsv: tuple[int, int, int],
) -> tuple[int, int, int]:
    if total_steps <= 1:
        return start_hsv

    clamped_step = min(max(step_index, 0), total_steps - 1)
    ratio = clamped_step / (total_steps - 1)
    h = round(start_hsv[0] + (end_hsv[0] - start_hsv[0]) * ratio)
    s = round(start_hsv[1] + (end_hsv[1] - start_hsv[1]) * ratio)
    v = round(start_hsv[2] + (end_hsv[2] - start_hsv[2]) * ratio)
    return h, s, v


def _build_sunset_step_times(sunset_at: datetime, total_steps: int, duration_minutes: int) -> list[datetime]:
    if total_steps <= 1:
        return [sunset_at]

    start_at = sunset_at - timedelta(minutes=duration_minutes / 2)
    interval_seconds = (duration_minutes * 60) / (total_steps - 1)
    return [start_at + timedelta(seconds=interval_seconds * step_index) for step_index in range(total_steps)]


async def initialize_lights() -> None:
    await lights_repository.discover_devices()


async def run_morning_scene() -> None:
    await lights_repository.set_scene_color((40, 10, 100), 100)


async def run_night_scene() -> None:
    are_on = await lights_repository.are_lights_on()
    if are_on:
        await lights_repository.set_scene_color((16, 100, 99), 100)


async def turn_all_lights_on() -> None:
    await lights_repository.turn_all_on()


async def turn_all_lights_off() -> None:
    await lights_repository.turn_all_off()


async def set_color(color: str) -> bool:
    normalized_color = _normalize_color(color)
    hsv = COLOR_MAP.get(normalized_color)
    if hsv is None:
        return False
    await lights_repository.set_color(hsv, 100)
    return True


async def get_devices(force_refresh: bool = False) -> list[dict[str, object]]:
    return await lights_repository.get_devices_inventory(force_refresh=force_refresh)


async def run_sunset_fade_step(step_index: int, total_steps: int) -> None:
    hsv = _interpolate_hsv(
        step_index=step_index,
        total_steps=total_steps,
        start_hsv=SUNSET_FADE_START_HSV,
        end_hsv=SUNSET_FADE_END_HSV,
    )
    await lights_repository.set_color_on_active_lights(color_hsv=hsv, brightness=hsv[2])


async def refresh_sunset_fade_jobs(scheduler: AsyncIOScheduler) -> None:
    for job in scheduler.get_jobs():
        if job.id.startswith(SUNSET_FADE_JOB_PREFIX):
            scheduler.remove_job(job.id)

    try:
        sunset_payload = await weather_repository.get_sunset(location=SUNSET_FADE_LOCATION)
    except RuntimeError as exc:
        print(f"Failed to resolve sunset schedule: {exc}")
        return

    sunset_at_raw = sunset_payload.get("sunset")
    if not isinstance(sunset_at_raw, str):
        print("Failed to resolve sunset schedule: missing sunset timestamp.")
        return

    try:
        sunset_at = datetime.fromisoformat(sunset_at_raw)
    except ValueError:
        print(f"Failed to parse sunset timestamp: {sunset_at_raw}")
        return

    now = datetime.now(tz=sunset_at.tzinfo) if sunset_at.tzinfo else datetime.now()
    run_times = _build_sunset_step_times(
        sunset_at=sunset_at,
        total_steps=SUNSET_FADE_STEPS,
        duration_minutes=SUNSET_FADE_DURATION_MINUTES,
    )

    scheduled_count = 0
    for step_index, run_at in enumerate(run_times):
        if run_at <= now:
            continue

        scheduler.add_job(
            run_sunset_fade_step,
            trigger="date",
            run_date=run_at,
            id=f"{SUNSET_FADE_JOB_PREFIX}{sunset_at.date().isoformat()}_{step_index:02d}",
            replace_existing=True,
            kwargs={"step_index": step_index, "total_steps": SUNSET_FADE_STEPS},
        )
        scheduled_count += 1

    print(
        f"Scheduled {scheduled_count} sunset fade jobs for {sunset_payload.get('resolved_location', SUNSET_FADE_LOCATION)} "
        f"at {sunset_at.isoformat()}."
    )
