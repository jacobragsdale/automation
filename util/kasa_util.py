import asyncio
from typing import Dict

from kasa import Discover
from kasa.iot import IotDevice, IotBulb


class KasaUtil:
    _instance = None
    devices: Dict[str, IotDevice] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def discover_devices(self):
        discovered_devices = await Discover.discover()
        if not discovered_devices:
            raise Exception("No Kasa devices found on the network.")
        self.devices = discovered_devices

    async def are_lights_on(self) -> bool:
        if not self.devices:
            await self.discover_devices()
        await asyncio.gather(*(dev.update() for dev in self.devices.values()))
        return any(dev.is_on for dev in self.devices.values())

    @staticmethod
    async def _run_command(dev: IotBulb, action: str, color_hsv, brightness: int) -> None:
        try:
            await dev.update()
            if action == "on":
                await dev.turn_on()
            elif action == "off":
                await dev.turn_off()
            elif action == "color":
                await dev.set_hsv(*color_hsv)
                await dev.set_brightness(brightness)
                await dev.turn_on()
            else:
                raise Exception(f"Unknown action: {action}")
        except Exception as e:
            print(f"Error controlling {getattr(dev, 'alias', 'Unknown device')}: {e}")

    async def execute_light_command(self, action: str, color_hsv, brightness: int) -> None:
        await self.discover_devices()

        tasks = [self._run_command(dev, action, color_hsv, brightness) for dev in list(self.devices.values())]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(KasaUtil().discover_devices())
    print(asyncio.run(KasaUtil().are_lights_on()))