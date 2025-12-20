import asyncio

from util.kasa_util import KasaUtil
from util.next_dns_util import NextDnsUtil

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


def _normalize_color(color: str) -> str:
    return " ".join(color.strip().lower().replace("-", " ").split())


async def run_morning_lights_handler():
    await KasaUtil().execute_light_command("color", (40, 10, 100), 100)


async def run_night_lights_handler():
    are_lights_on = await KasaUtil().are_lights_on()
    if are_lights_on:
        await KasaUtil().execute_light_command("color", (16, 100, 99), 100)


async def run_all_lights_on_handler():
    await KasaUtil().execute_light_command("on", (0, 0, 0), 0)


async def run_all_lights_off_handler():
    await KasaUtil().execute_light_command("off", (0, 0, 0), 0)


async def run_color_lights_handler(color: str) -> bool:
    normalized = _normalize_color(color)
    hsv = COLOR_MAP.get(normalized)
    if not hsv:
        return False
    await KasaUtil().execute_light_command("color", hsv, 100)
    return True


async def toggle_lockdown_handler(active: bool):
    await NextDnsUtil().toggle_lockdown(active)


if __name__ == "__main__":
    asyncio.run(run_night_lights_handler())
