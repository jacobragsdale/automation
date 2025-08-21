import asyncio
import json
from pathlib import Path
from typing import Dict, Set

from kasa import Discover
from kasa.iot import IotDevice, IotBulb


class KasaUtil:
    _instance = None
    devices: Dict[str, IotDevice] = {}
    _devices_file_path: Path | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _get_devices_file_path(self) -> Path:
        if self._devices_file_path is None:
            self._devices_file_path = Path(__file__).resolve().parent / "devices.json"
        return self._devices_file_path

    def _load_saved_device_ips(self) -> Set[str]:
        devices_file = self._get_devices_file_path()
        try:
            with devices_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {str(item) for item in data if isinstance(item, str)}
                return set()
        except FileNotFoundError:
            return set()
        except json.JSONDecodeError:
            return set()

    def _save_device_ips(self, device_ips: Set[str]) -> None:
        devices_file = self._get_devices_file_path()
        try:
            with devices_file.open("w", encoding="utf-8") as f:
                json.dump(sorted(device_ips), f, indent=2)
        except Exception as e:
            print(f"Failed to save devices to {devices_file}: {e}")

    async def discover_devices(self):
        discovered_devices = await Discover.discover()
        self.devices = discovered_devices or {}

        if self.devices:
            saved_ips = self._load_saved_device_ips()
            merged_ips = saved_ips.union(set(self.devices.keys()))
            self._save_device_ips(merged_ips)

    async def are_lights_on(self) -> bool:
        if not self.devices:
            await self.discover_devices()
        await asyncio.gather(*(dev.update() for dev in self.devices.values()))
        return any(dev.is_on for dev in self.devices.values())

    @staticmethod
    async def _run_command(dev: IotDevice, action: str, color_hsv, brightness: int) -> None:
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
        saved_ips = self._load_saved_device_ips()
        await self.discover_devices()

        discovered_ips = set(self.devices.keys())
        all_ips = saved_ips.union(discovered_ips)

        # Start with the devices we already discovered
        devices_to_use = list(self.devices.values())

        # For any saved IP not in the current discovery, try to discover it individually
        missing_ips = all_ips - discovered_ips
        for ip in missing_ips:
            try:
                dev = await Discover.discover_single(ip)
                if dev is not None:
                    devices_to_use.append(dev)
                    self.devices[ip] = dev
            except Exception as e:
                print(f"Failed to connect to saved device {ip}: {e}")

        # Persist any new IPs we managed to connect to
        final_ips = set(self.devices.keys()).union(saved_ips)
        self._save_device_ips(final_ips)

        if not devices_to_use:
            print("No Kasa devices available to control.")
            return

        tasks = [self._run_command(dev, action, color_hsv, brightness) for dev in devices_to_use]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(KasaUtil().discover_devices())
    print(asyncio.run(KasaUtil().execute_light_command("on", (40, 10, 100), 100)))