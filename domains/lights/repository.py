import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Any

from kasa import Discover
from kasa.iot import IotDevice


class LightsRepository:
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

        project_root = Path(__file__).resolve().parents[2]
        util_dir = project_root / "util"

        self.devices: dict[str, IotDevice] = {}
        self._devices_file_path = util_dir / "devices.json"
        self._inventory_file_path = util_dir / "devices_inventory.json"
        self._discovery_lock = asyncio.Lock()
        self._last_discovery = 0.0
        self._initialized = True

    def _load_saved_device_ips(self) -> set[str]:
        try:
            data = json.loads(self._devices_file_path.read_text(encoding="utf-8"))
            return {str(ip) for ip in data if isinstance(ip, str)}
        except Exception:
            return set()

    def _save_device_ips(self, device_ips: set[str]) -> None:
        try:
            payload = json.dumps(sorted(device_ips), indent=2)
            self._devices_file_path.write_text(payload, encoding="utf-8")
        except Exception as exc:
            print(f"Failed to save devices to {self._devices_file_path}: {exc}")

    def _save_device_inventory(self, inventory: list[dict[str, Any]]) -> None:
        try:
            payload = json.dumps(inventory, indent=2)
            self._inventory_file_path.write_text(payload, encoding="utf-8")
        except Exception as exc:
            print(f"Failed to save device inventory to {self._inventory_file_path}: {exc}")

    def _stale(self, force_refresh: bool) -> bool:
        return force_refresh or not self.devices or (monotonic() - self._last_discovery) >= self.DISCOVERY_TTL

    async def _with_timeout(self, coro, message: str, *, timeout: int | None = None):
        try:
            return await asyncio.wait_for(coro, timeout=timeout or self.COMMAND_TIMEOUT)
        except Exception as exc:
            print(f"{message}: {exc}")
        return None

    async def _probe_ip(self, ip: str) -> tuple[str, IotDevice | None]:
        device = await self._with_timeout(
            Discover.discover_single(ip, discovery_timeout=self.DISCOVERY_TIMEOUT, timeout=self.COMMAND_TIMEOUT),
            f"Discovery timed out for saved device {ip}",
            timeout=self.COMMAND_TIMEOUT + 1,
        )
        return ip, device

    async def _discover_ips(self, ips: set[str]) -> dict[str, IotDevice]:
        if not ips:
            return {}
        results = await asyncio.gather(*(self._probe_ip(ip) for ip in ips))
        return {ip: dev for ip, dev in results if dev is not None}

    async def _broadcast_discover(self) -> dict[str, IotDevice]:
        devices = await self._with_timeout(
            Discover.discover(
                discovery_timeout=self.DISCOVERY_TIMEOUT,
                timeout=self.COMMAND_TIMEOUT,
            ),
            "Broadcast discovery timed out; using cached devices if available.",
            timeout=self.DISCOVERY_TIMEOUT + 1,
        )
        return devices or {}

    async def discover_devices(self, force_refresh: bool = False) -> dict[str, IotDevice]:
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

    @staticmethod
    def _safe_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def _safe_call(getter, default: Any = None) -> Any:
        try:
            return getter()
        except Exception:
            return default

    def _device_to_inventory(self, host: str, device: IotDevice) -> dict[str, Any]:
        device_type = self._safe_call(lambda: getattr(device, "device_type", None))
        if hasattr(device_type, "value"):
            device_type = getattr(device_type, "value")
        elif device_type is not None:
            device_type = str(device_type)

        children = self._safe_call(lambda: getattr(device, "children", []), default=[]) or []
        child_aliases = [
            str(alias)
            for alias in (self._safe_call(lambda child=child: getattr(child, "alias", None)) for child in children)
            if alias
        ]

        location = self._safe_call(lambda: getattr(device, "location", (None, None)), default=(None, None))
        lat, lon = (None, None)
        if isinstance(location, (tuple, list)) and len(location) >= 2:
            lat, lon = location[0], location[1]

        return {
            "host": host,
            "alias": self._safe_value(self._safe_call(lambda: getattr(device, "alias", None))),
            "model": self._safe_value(self._safe_call(lambda: getattr(device, "model", None))),
            "mac": self._safe_value(self._safe_call(lambda: getattr(device, "mac", None))),
            "device_id": self._safe_value(self._safe_call(lambda: getattr(device, "device_id", None))),
            "device_type": self._safe_value(device_type),
            "is_on": bool(self._safe_call(lambda: getattr(device, "is_on", False), default=False)),
            "is_bulb": bool(self._safe_call(lambda: getattr(device, "is_bulb", False), default=False)),
            "is_plug": bool(self._safe_call(lambda: getattr(device, "is_plug", False), default=False)),
            "brightness": self._safe_value(self._safe_call(lambda: getattr(device, "brightness", None))),
            "hsv": self._safe_value(self._safe_call(lambda: getattr(device, "hsv", None))),
            "color_temp": self._safe_value(self._safe_call(lambda: getattr(device, "color_temp", None))),
            "latitude": lat,
            "longitude": lon,
            "children": child_aliases,
        }

    async def get_devices_inventory(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        devices = await self.discover_devices(force_refresh=force_refresh)
        if not devices:
            self._save_device_inventory([])
            return []

        await self._update_all()
        inventory = [
            self._device_to_inventory(host, device)
            for host, device in sorted(devices.items(), key=lambda item: item[0])
        ]
        self._save_device_inventory(inventory)
        return inventory

    async def are_lights_on(self) -> bool:
        await self.discover_devices()
        if not self.devices:
            return False

        await self._update_all()
        return any(dev.is_on for dev in self.devices.values())

    async def _run_command(self, dev: IotDevice, action: str, color_hsv: tuple[int, int, int], brightness: int) -> None:
        async def _execute() -> None:
            if action == "on":
                await dev.turn_on()
            elif action == "off":
                await dev.turn_off()
            elif action == "color":
                await dev.set_hsv(*color_hsv)
                await dev.set_brightness(brightness)
                await dev.turn_on()
            else:
                raise RuntimeError(f"Unknown action: {action}")

        await self._with_timeout(_execute(), f"Command timed out for {getattr(dev, 'alias', 'Unknown device')}")

    async def execute_light_command(self, action: str, color_hsv: tuple[int, int, int], brightness: int) -> None:
        await self.discover_devices()
        if not self.devices:
            print("No Kasa devices available to control.")
            return

        await self._update_all()
        await asyncio.gather(*(self._run_command(dev, action, color_hsv, brightness) for dev in self.devices.values()))

    async def _run_color_if_on(self, dev: IotDevice, color_hsv: tuple[int, int, int], brightness: int) -> None:
        async def _execute() -> None:
            if not dev.is_on:
                return
            await dev.set_hsv(*color_hsv)
            await dev.set_brightness(brightness)

        await self._with_timeout(
            _execute(),
            f"Color command timed out for {getattr(dev, 'alias', 'Unknown device')}",
        )

    async def execute_color_on_active_lights(self, color_hsv: tuple[int, int, int], brightness: int) -> None:
        await self.discover_devices()
        if not self.devices:
            print("No Kasa devices available to control.")
            return

        await self._update_all()
        on_devices = [dev for dev in self.devices.values() if dev.is_on]
        if not on_devices:
            print("No lights are currently on; skipping color update.")
            return

        await asyncio.gather(*(self._run_color_if_on(dev, color_hsv, brightness) for dev in on_devices))

    async def set_scene_color(self, color_hsv: tuple[int, int, int], brightness: int) -> None:
        await self.execute_light_command("color", color_hsv, brightness)

    async def turn_all_on(self) -> None:
        await self.execute_light_command("on", (0, 0, 0), 0)

    async def turn_all_off(self) -> None:
        await self.execute_light_command("off", (0, 0, 0), 0)

    async def set_color(self, color_hsv: tuple[int, int, int], brightness: int) -> None:
        await self.execute_light_command("color", color_hsv, brightness)

    async def set_color_on_active_lights(self, color_hsv: tuple[int, int, int], brightness: int) -> None:
        await self.execute_color_on_active_lights(color_hsv=color_hsv, brightness=brightness)
