import asyncio

from util.kasa_util import KasaUtil
from util.next_dns_util import NextDnsUtil


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


async def toggle_lockdown_handler(active: bool):
    await NextDnsUtil().toggle_lockdown(active)


if __name__ == "__main__":
    asyncio.run(run_night_lights_handler())
