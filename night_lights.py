import asyncio
import json
import os
from typing import Dict

from kasa import Discover
from kasa.iot import IotBulb


class LightCommand:
    def __init__(self):
        self.devices: Dict[str, IotBulb] = {}
        self.devices_cache_file = "devices_cache.json"
        self.device_data_cache = {}
        self._load_devices_from_cache()

    def _load_devices_from_cache(self) -> None:
        try:
            if os.path.exists(self.devices_cache_file):
                # Add a simple button
                with open(self.devices_cache_file, "r") as f:
                    self.device_data_cache = json.load(f)
                print(f"Loaded {len(self.device_data_cache)} devices from cache.")
        except Exception as e:
            print(f"Error loading device cache: {e}")
            self.device_data_cache = {}

    def _save_devices_to_cache(self) -> None:
        try:
            serialized_data = {}
            for ip, device in self.devices.items():
                device_info = {
                    "ip": ip,
                    "alias": getattr(device, "alias", "Unknown Device"),
                    "model": getattr(device, "model", "Unknown Model"),
                    "device_type": "bulb" if isinstance(device, IotBulb) else "other"
                }
                serialized_data[ip] = device_info
            with open(self.devices_cache_file, "w") as f:
                json.dump(serialized_data, f, indent=2)
            print(f"Saved {len(serialized_data)} devices to cache.")
            self.device_data_cache = serialized_data
        except Exception as e:
            print(f"Error saving device cache: {e}")

    async def set_devices(self):
        if self.device_data_cache:
            print("Using cached device information...")
            tasks = [
                self._connect_to_cached_devices(ip)
                for ip, info in self.device_data_cache.items()
            ]
            await asyncio.gather(*tasks)
        else:
            print("Discovering devices...")
            try:
                discovered_devices = await Discover.discover()
                if not discovered_devices:
                    print("No Kasa devices found on the network.")
                    return
                self.devices = discovered_devices
                print(f"Found {len(self.devices)} device(s)")
                self._save_devices_to_cache()
            except Exception as e:
                print(f"Error discovering devices: {e}")
                return

    async def execute_light_command(self, action: str, color_hsv, brightness: int) -> None:
        if not self.devices:
            await self.set_devices()

        tasks = [self.run_command(dev, action, color_hsv, brightness) for dev in list(self.devices.values())]
        await asyncio.gather(*tasks)

    async def run_command(self, dev, action: str, color_hsv, brightness):
        try:
            await dev.update()
            dev_alias = getattr(dev, "alias", "Unknown device")
            if action == "on":
                if isinstance(dev, IotBulb):
                    await dev.set_brightness(brightness)
                await dev.turn_on()
                print(f"Turned on {dev_alias}" + (
                    f" at {brightness}% brightness" if isinstance(dev, IotBulb) else ""))
            elif action == "off":
                await dev.turn_off()
                print(f"Turned off {dev_alias}")
            elif action == "toggle":
                if dev.is_on:
                    await dev.turn_off()
                    print(f"Toggled {dev_alias} off")
                else:
                    if isinstance(dev, IotBulb):
                        await dev.set_brightness(brightness)
                    await dev.turn_on()
                    print(f"Toggled {dev_alias} on" + (
                        f" at {brightness}% brightness" if isinstance(dev, IotBulb) else ""))
            elif action == "color" and color_hsv is not None:
                if isinstance(dev, IotBulb) and hasattr(dev, "set_hsv"):
                    await dev.set_hsv(*color_hsv)
                    await dev.set_brightness(brightness)
                    await dev.turn_on()
                    print(f"Set {dev_alias} to color HSV{color_hsv} at {brightness}% brightness")
                else:
                    print(f"Device {dev_alias} doesn't support color changes")
            elif action == "status":
                state = "on" if dev.is_on else "off"
                brightness_str = f" at {dev.brightness}% brightness" if hasattr(dev, "brightness") else ""
                color_str = f", color HSV: {dev.hsv}" if hasattr(dev, "hsv") and dev.is_on else ""
                print(f"{dev_alias} is {state}{brightness_str}{color_str}")
            else:
                print(f"Unknown action: {action}")
        except Exception as e:
            print(f"Error controlling {getattr(dev, 'alias', 'Unknown device')}: {e}")

    async def _connect_to_cached_devices(self, ip) -> None:
        try:
            device = IotBulb(ip)
            await device.update()
            self.devices[ip] = device
            print(f"Connected to {getattr(device, 'alias', 'Unknown device')} ({ip})")
        except Exception as e:
            print(f"Error connecting to cached device at {ip}: {e}")


if __name__ == '__main__':
    action = "color"
    color_hsv = (16, 100, 99)
    brightness = 100
    light_command = LightCommand()
    asyncio.run(light_command.execute_light_command(action, color_hsv, brightness))
