import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Dict, Set

from kasa import Discover
from kasa.iot import IotDevice


class KasaUtil:
    _instance = None
    devices: Dict[str, IotDevice] = {}
    _devices_file_path: Path | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.devices: Dict[str, IotDevice] = {}
        self._devices_file_path: Path | None = None
        self._discovery_lock = asyncio.Lock()
        self._last_discovery: float = 0.0
        self._discovery_ttl_seconds: float = 300
        self._discover_timeout_seconds: int = 3
        self._command_timeout_seconds: int = 6
        self._initialized = True

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

    def _should_skip_discovery(self, force_refresh: bool) -> bool:
        if force_refresh or not self.devices:
            return False
        return (monotonic() - self._last_discovery) < self._discovery_ttl_seconds

    async def _discover_single_ip(self, ip: str) -> tuple[str, IotDevice | None]:
        try:
            device = await asyncio.wait_for(
                Discover.discover_single(
                    ip,
                    discovery_timeout=self._discover_timeout_seconds,
                    timeout=self._command_timeout_seconds,
                ),
                timeout=self._command_timeout_seconds + 1,
            )
            return ip, device
        except asyncio.TimeoutError:
            print(f"Discovery timed out for saved device {ip}")
        except Exception as e:
            print(f"Failed to connect to saved device {ip}: {e}")
        return ip, None

    async def _discover_saved_ips(self, saved_ips: Set[str]) -> Dict[str, IotDevice]:
        if not saved_ips:
            return {}
        results = await asyncio.gather(*(self._discover_single_ip(ip) for ip in saved_ips))
        return {ip: dev for ip, dev in results if dev is not None}

    async def _broadcast_discover(self) -> Dict[str, IotDevice]:
        try:
            devices = await asyncio.wait_for(
                Discover.discover(
                    discovery_timeout=self._discover_timeout_seconds,
                    timeout=self._command_timeout_seconds,
                ),
                timeout=self._discover_timeout_seconds + 1,
            )
            return devices or {}
        except asyncio.TimeoutError:
            print("Broadcast discovery timed out; using cached devices if available.")
        except Exception as e:
            print(f"Failed broadcast discovery: {e}")
        return {}

    async def discover_devices(self, force_refresh: bool = False) -> Dict[str, IotDevice]:
        if self._should_skip_discovery(force_refresh):
            return self.devices

        async with self._discovery_lock:
            if self._should_skip_discovery(force_refresh):
                return self.devices

            saved_ips = self._load_saved_device_ips()
            discovered: Dict[str, IotDevice] = {}
            discovered.update(await self._discover_saved_ips(saved_ips))
            discovered.update(await self._broadcast_discover())

            if not discovered and self.devices:
                discovered = self.devices

            self.devices = discovered
            if self.devices:
                self._save_device_ips(set(self.devices.keys()))
            self._last_discovery = monotonic()
            return self.devices

    async def are_lights_on(self) -> bool:
        await self.discover_devices()
        if not self.devices:
            return False

        await asyncio.gather(*(self._update_device_state(dev) for dev in self.devices.values()))
        return any(dev.is_on for dev in self.devices.values())

    async def _update_device_state(self, dev: IotDevice) -> None:
        try:
            await asyncio.wait_for(dev.update(), timeout=self._command_timeout_seconds)
        except asyncio.TimeoutError:
            print(f"Timeout updating {getattr(dev, 'alias', 'Unknown device')}")
        except Exception as e:
            print(f"Error updating {getattr(dev, 'alias', 'Unknown device')}: {e}")

    async def _run_command(
        self,
        dev: IotDevice,
        action: str,
        color_hsv: tuple[int, int, int],
        brightness: int,
    ) -> None:
        async def _execute():
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

        try:
            await asyncio.wait_for(_execute(), timeout=self._command_timeout_seconds)
        except asyncio.TimeoutError:
            print(f"Command timed out for {getattr(dev, 'alias', 'Unknown device')}")
        except Exception as e:
            print(f"Error controlling {getattr(dev, 'alias', 'Unknown device')}: {e}")

    async def execute_light_command(self, action: str, color_hsv: tuple[int, int, int], brightness: int) -> None:
        await self.discover_devices()

        if not self.devices:
            print("No Kasa devices available to control.")
            return

        await asyncio.gather(*(self._update_device_state(dev) for dev in self.devices.values()))
        tasks = [self._run_command(dev, action, color_hsv, brightness) for dev in self.devices.values()]
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(KasaUtil().discover_devices())
    print(asyncio.run(KasaUtil().execute_light_command("on", (40, 10, 100), 100)))
