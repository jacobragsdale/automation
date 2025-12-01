import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Dict, Set

from kasa import Discover
from kasa.iot import IotDevice


class KasaUtil:
    _instance = None
    DISCOVERY_TTL = 300
    DISCOVERY_TIMEOUT = 3
    COMMAND_TIMEOUT = 6

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.devices: Dict[str, IotDevice] = {}
        self._devices_file_path = Path(__file__).resolve().parent / "devices.json"
        self._discovery_lock = asyncio.Lock()
        self._last_discovery = 0.0
        self._initialized = True

    def _load_saved_device_ips(self) -> Set[str]:
        try:
            data = json.loads(self._devices_file_path.read_text(encoding="utf-8"))
            return {str(ip) for ip in data if isinstance(ip, str)}
        except Exception:
            return set()

    def _save_device_ips(self, device_ips: Set[str]) -> None:
        try:
            payload = json.dumps(sorted(device_ips), indent=2)
            self._devices_file_path.write_text(payload, encoding="utf-8")
        except Exception as e:
            print(f"Failed to save devices to {self._devices_file_path}: {e}")

    def _stale(self, force_refresh: bool) -> bool:
        return force_refresh or not self.devices or (monotonic() - self._last_discovery) >= self.DISCOVERY_TTL

    async def _with_timeout(self, coro, message: str, *, timeout: int | None = None):
        try:
            return await asyncio.wait_for(coro, timeout=timeout or self.COMMAND_TIMEOUT)
        except Exception as e:
            print(f"{message}: {e}")
        return None

    async def _probe_ip(self, ip: str) -> tuple[str, IotDevice | None]:
        device = await self._with_timeout(
            Discover.discover_single(ip, discovery_timeout=self.DISCOVERY_TIMEOUT, timeout=self.COMMAND_TIMEOUT),
            f"Discovery timed out for saved device {ip}",
            timeout=self.COMMAND_TIMEOUT + 1,
        )
        return ip, device

    async def _discover_ips(self, ips: Set[str]) -> Dict[str, IotDevice]:
        if not ips:
            return {}
        results = await asyncio.gather(*(self._probe_ip(ip) for ip in ips))
        return {ip: dev for ip, dev in results if dev is not None}

    async def _broadcast_discover(self) -> Dict[str, IotDevice]:
        devices = await self._with_timeout(
            Discover.discover(
                discovery_timeout=self.DISCOVERY_TIMEOUT,
                timeout=self.COMMAND_TIMEOUT,
            ),
            "Broadcast discovery timed out; using cached devices if available.",
            timeout=self.DISCOVERY_TIMEOUT + 1,
        )
        return devices or {}

    async def discover_devices(self, force_refresh: bool = False) -> Dict[str, IotDevice]:
        if not self._stale(force_refresh):
            return self.devices

        async with self._discovery_lock:
            if not self._stale(force_refresh):
                return self.devices

            saved_ips = self._load_saved_device_ips()
            saved_task = asyncio.create_task(self._discover_ips(saved_ips))
            broadcast_task = asyncio.create_task(self._broadcast_discover())
            discovered = {**await saved_task, **await broadcast_task}

            if not discovered and self.devices:
                discovered = self.devices

            self.devices = discovered
            if self.devices:
                self._save_device_ips(set(self.devices))
            self._last_discovery = monotonic()
            return self.devices

    async def _update_device(self, dev: IotDevice) -> None:
        await self._with_timeout(dev.update(), f"Timeout updating {getattr(dev, 'alias', 'Unknown device')}")

    async def _update_all(self) -> None:
        await asyncio.gather(*(self._update_device(dev) for dev in self.devices.values()))

    async def are_lights_on(self) -> bool:
        await self.discover_devices()
        if not self.devices:
            return False
        await self._update_all()
        return any(dev.is_on for dev in self.devices.values())

    async def _run_command(self, dev: IotDevice, action: str, color_hsv: tuple[int, int, int], brightness: int) -> None:
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

        await self._with_timeout(_execute(), f"Command timed out for {getattr(dev, 'alias', 'Unknown device')}")

    async def execute_light_command(self, action: str, color_hsv: tuple[int, int, int], brightness: int) -> None:
        await self.discover_devices()
        if not self.devices:
            print("No Kasa devices available to control.")
            return

        await self._update_all()
        await asyncio.gather(*(self._run_command(dev, action, color_hsv, brightness) for dev in self.devices.values()))


if __name__ == "__main__":
    asyncio.run(KasaUtil().discover_devices())
    print(asyncio.run(KasaUtil().execute_light_command("on", (40, 10, 100), 100)))
