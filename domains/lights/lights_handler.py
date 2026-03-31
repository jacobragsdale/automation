from apscheduler.schedulers.asyncio import AsyncIOScheduler  # pyright: ignore[reportMissingTypeStubs]

from domains.lights.lights_repository import LightsRepository

lights_repository = LightsRepository()

MORNING_SCENE_HSV = (40, 10, 100)
MORNING_SCENE_BRIGHTNESS = 100
NIGHT_SCENE_HSV = (16, 100, 99)
NIGHT_SCENE_BRIGHTNESS = 100


async def initialize_lights() -> None:
    await lights_repository.discover_devices()


async def run_morning_scene() -> None:
    await lights_repository.set_all_color(MORNING_SCENE_HSV, MORNING_SCENE_BRIGHTNESS)


async def run_night_scene() -> None:
    are_on = await lights_repository.are_lights_on()
    if are_on:
        await lights_repository.set_all_color(NIGHT_SCENE_HSV, NIGHT_SCENE_BRIGHTNESS)


async def turn_all_lights_on() -> None:
    await lights_repository.turn_all_on()


async def turn_all_lights_off() -> None:
    await lights_repository.turn_all_off()


async def set_color(hsv: tuple[int, int, int]) -> None:
    await lights_repository.set_all_color(hsv, hsv[2])


async def get_devices(force_refresh: bool = False) -> list[dict[str, object]]:
    return await lights_repository.get_devices_inventory(force_refresh=force_refresh)


async def refresh_sunset_fade_jobs(scheduler: AsyncIOScheduler) -> None:
    del scheduler
