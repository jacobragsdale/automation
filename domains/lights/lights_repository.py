import asyncio
from ipaddress import ip_address, ip_network
import json
import os
from pathlib import Path
from time import monotonic
from typing import Any, Awaitable, Callable, TypeVar

from kasa import Device, Discover, Module
from kasa.iot import IotDevice

T = TypeVar("T")
DeviceSelector = Callable[[list[IotDevice]], list[IotDevice]]


class LightsRepository:
    _instance = None
    DISCOVERY_TTL = 300
    DISCOVERY_TIMEOUT = 3
    COMMAND_TIMEOUT = 6
    NETWORK_SCAN_TIMEOUT = 1
    NETWORK_SCAN_COMMAND_TIMEOUT = 2
    NETWORK_SCAN_CONCURRENCY = 64

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self.devices: dict[str, IotDevice] = {}
        self._devices_file_path = Path(__file__).resolve().parent / "devices.json"
        self._inventory_file_path = Path(__file__).resolve().parent / "devices_inventory.json"
        self._discovery_lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task[None]] = set()
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

    async def _with_timeout(self, coro: Awaitable[T], message: str, *, timeout: int | None = None) -> T | None:
        try:
            result: T = await asyncio.wait_for(coro, timeout=timeout or self.COMMAND_TIMEOUT)  # type: ignore[arg-type]
            return result
        except Exception as exc:
            print(f"{message}: {exc}")
        return None

    async def _probe_ip(
        self,
        ip: str,
        *,
        discovery_timeout: int = DISCOVERY_TIMEOUT,
        command_timeout: int = COMMAND_TIMEOUT,
        log_errors: bool = True,
    ) -> tuple[str, IotDevice | None]:
        try:
            device: Device | None = await asyncio.wait_for(
                Discover.discover_single(ip, discovery_timeout=discovery_timeout, timeout=command_timeout),  # pyright: ignore[reportUnknownMemberType]
                timeout=command_timeout + 1,
            )
        except Exception as exc:
            if log_errors:
                print(f"Discovery timed out for saved device {ip}: {exc}")
            return ip, None
        return ip, device if isinstance(device, IotDevice) else None

    async def _discover_ips(
        self,
        ips: set[str],
        *,
        discovery_timeout: int = DISCOVERY_TIMEOUT,
        command_timeout: int = COMMAND_TIMEOUT,
        log_errors: bool = True,
        concurrency: int | None = None,
    ) -> dict[str, IotDevice]:
        if not ips:
            return {}

        if concurrency is None:
            results = await asyncio.gather(
                *(
                    self._probe_ip(
                        ip,
                        discovery_timeout=discovery_timeout,
                        command_timeout=command_timeout,
                        log_errors=log_errors,
                    )
                    for ip in ips
                )
            )
            return {ip: dev for ip, dev in results if dev is not None}

        semaphore = asyncio.Semaphore(concurrency)

        async def _limited_probe(ip: str) -> tuple[str, IotDevice | None]:
            async with semaphore:
                return await self._probe_ip(
                    ip,
                    discovery_timeout=discovery_timeout,
                    command_timeout=command_timeout,
                    log_errors=log_errors,
                )

        results = await asyncio.gather(*(_limited_probe(ip) for ip in ips))
        return {ip: dev for ip, dev in results if dev is not None}

    def _neighbor_ips(self, seed_ips: set[str]) -> set[str]:
        candidates: set[str] = set()
        for seed_ip in seed_ips:
            try:
                address = ip_address(seed_ip)
            except ValueError:
                continue
            if address.version != 4:
                continue

            network = ip_network(f"{address}/24", strict=False)
            candidates.update(str(host) for host in network.hosts())
        return candidates - seed_ips

    async def _discover_neighbor_ips(self, seed_ips: set[str]) -> dict[str, IotDevice]:
        return await self._discover_ips(
            self._neighbor_ips(seed_ips),
            discovery_timeout=self.NETWORK_SCAN_TIMEOUT,
            command_timeout=self.NETWORK_SCAN_COMMAND_TIMEOUT,
            log_errors=False,
            concurrency=self.NETWORK_SCAN_CONCURRENCY,
        )

    async def _broadcast_discover(self) -> dict[str, IotDevice]:
        raw: dict[str, Device] | None = await self._with_timeout(
            Discover.discover(  # pyright: ignore[reportUnknownMemberType]
                discovery_timeout=self.DISCOVERY_TIMEOUT,
                timeout=self.COMMAND_TIMEOUT,
            ),
            "Broadcast discovery timed out; using cached devices if available.",
            timeout=self.DISCOVERY_TIMEOUT + 1,
        )
        if not raw:
            return {}
        return {host: dev for host, dev in raw.items() if isinstance(dev, IotDevice)}

    async def discover_devices(self, force_refresh: bool = False) -> dict[str, IotDevice]:
        if not self._stale(force_refresh):
            return self.devices

        async with self._discovery_lock:
            if not self._stale(force_refresh):
                return self.devices

            saved_ips = self._load_saved_device_ips()
            seed_ips = saved_ips | set(self.devices)
            saved_task = asyncio.create_task(self._discover_ips(saved_ips))
            neighbor_task = asyncio.create_task(self._discover_neighbor_ips(seed_ips))
            broadcast_task = asyncio.create_task(self._broadcast_discover())
            discovered = {**await saved_task, **await neighbor_task, **await broadcast_task}

            if not discovered and self.devices:
                discovered = self.devices

            self.devices = discovered
            if self.devices:
                self._save_device_ips(set(self.devices))
            self._last_discovery = monotonic()
            return self.devices

    async def _update_device(self, dev: IotDevice) -> None:
        await self._with_timeout(dev.update(), f"Timeout updating {getattr(dev, 'alias', 'Unknown device')}")  # pyright: ignore[reportUnknownMemberType]

    async def _update_all(self) -> None:
        await asyncio.gather(*(self._update_device(dev) for dev in self.devices.values()))

    @staticmethod
    def _safe_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    @staticmethod
    def _safe_call(getter: Callable[[], Any], default: Any = None) -> Any:
        try:
            return getter()
        except Exception:
            return default

    def _device_to_inventory(self, host: str, device: IotDevice, *, cloud_bound: bool | None = None) -> dict[str, Any]:
        device_type = self._safe_call(lambda: getattr(device, "device_type", None))
        if hasattr(device_type, "value"):
            device_type = getattr(device_type, "value")
        elif device_type is not None:
            device_type = str(device_type)

        children: list[Any] = self._safe_call(lambda: getattr(device, "children", []), default=[]) or []
        child_aliases = [
            str(alias)
            for alias in (self._safe_call(lambda child=child: getattr(child, "alias", None)) for child in children)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
            if alias
        ]

        location: Any = self._safe_call(lambda: getattr(device, "location", (None, None)), default=(None, None))
        lat: Any = None
        lon: Any = None
        if isinstance(location, (tuple, list)) and len(location) >= 2:  # pyright: ignore[reportUnknownArgumentType]
            lat = location[0]  # pyright: ignore[reportUnknownVariableType]
            lon = location[1]  # pyright: ignore[reportUnknownVariableType]

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
            "cloud_bound": cloud_bound,
        }

    async def _ensure_cloud_bound(self, device: IotDevice, username: str, password: str) -> bool:
        cloud = device.modules.get(Module.IotCloud)
        if cloud is None:
            return False
        info = cloud.info
        if info.provisioned and info.username == username:
            return True
        await cloud.call("bind", {"username": username, "password": password})
        return True

    async def _ensure_all_cloud_bound(self) -> dict[str, bool]:
        username = os.getenv("KASA_CLOUD_USERNAME")
        password = os.getenv("KASA_CLOUD_PASSWORD")
        if not username or not password:
            print("KASA_CLOUD_USERNAME/KASA_CLOUD_PASSWORD not set; skipping cloud bind.")
            return {}
        results: dict[str, bool] = {}
        for host, dev in self.devices.items():
            bound = await self._with_timeout(
                self._ensure_cloud_bound(dev, username, password),
                f"Cloud bind timed out for {getattr(dev, 'alias', host)}",
            )
            results[host] = bool(bound)
        return results

    async def get_devices_inventory(self, force_refresh: bool = False, bind_to_cloud: bool = False) -> list[dict[str, Any]]:
        devices = await self.discover_devices(force_refresh=force_refresh)
        if not devices:
            self._save_device_inventory([])
            return []

        await self._update_all()

        cloud_bound: dict[str, bool] = {}
        if bind_to_cloud:
            cloud_bound = await self._ensure_all_cloud_bound()

        inventory = [
            self._device_to_inventory(host, device, cloud_bound=cloud_bound.get(host))
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

    async def _get_updated_devices(self) -> list[IotDevice]:
        await self.discover_devices()
        if not self.devices:
            return []

        await self._update_all()
        return list(self.devices.values())

    async def _run_for_devices(
        self,
        devices: list[IotDevice],
        command_factory: Callable[[IotDevice], Awaitable[None]],
        timeout_message_prefix: str,
    ) -> None:
        coros = [
            self._with_timeout(  # pyright: ignore[reportUnknownMemberType]
                command_factory(dev),
                f"{timeout_message_prefix} {getattr(dev, 'alias', 'Unknown device')}",
            )
            for dev in devices
        ]
        await asyncio.gather(*coros)

    def _track_background_task(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.add(task)
        task.add_done_callback(self._finish_background_task)

    def _finish_background_task(self, task: asyncio.Task[None]) -> None:
        self._background_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"Background lights refresh failed: {exc}")

    async def _refresh_and_run_for_devices(
        self,
        command_factory: Callable[[IotDevice], Awaitable[None]],
        timeout_message_prefix: str,
        device_selector: DeviceSelector | None = None,
        empty_message: str = "No Kasa devices found during background refresh.",
    ) -> None:
        refreshed_devices = await self.discover_devices(force_refresh=True)
        if not refreshed_devices:
            print(empty_message)
            return

        await self._update_all()
        devices = list(refreshed_devices.values())
        if device_selector is not None:
            devices = device_selector(devices)
        if not devices:
            print(empty_message)
            return

        await self._run_for_devices(
            devices,
            command_factory,
            f"{timeout_message_prefix} after refresh for",
        )

    def _schedule_refresh_command(
        self,
        command_factory: Callable[[IotDevice], Awaitable[None]],
        timeout_message_prefix: str,
        device_selector: DeviceSelector | None = None,
        empty_message: str = "No Kasa devices found during background refresh.",
    ) -> None:
        task = asyncio.create_task(
            self._refresh_and_run_for_devices(
                command_factory,
                timeout_message_prefix,
                device_selector=device_selector,
                empty_message=empty_message,
            )
        )
        self._track_background_task(task)

    async def _run_for_current_devices_and_refresh(
        self,
        command_factory: Callable[[IotDevice], Awaitable[None]],
        timeout_message_prefix: str,
        device_selector: DeviceSelector | None = None,
        empty_message: str = "No Kasa devices available to control.",
    ) -> None:
        devices = await self._get_updated_devices()
        if device_selector is not None:
            devices = device_selector(devices)
        if devices:
            await self._run_for_devices(devices, command_factory, timeout_message_prefix)
        else:
            print(empty_message)

        self._schedule_refresh_command(
            command_factory,
            timeout_message_prefix,
            device_selector=device_selector,
            empty_message=empty_message,
        )

    async def turn_all_on(self) -> None:
        async def _turn_on(dev: IotDevice) -> None:
            await dev.turn_on()  # pyright: ignore[reportUnknownMemberType]

        await self._run_for_current_devices_and_refresh(_turn_on, "Command timed out for")

    async def turn_all_off(self) -> None:
        async def _turn_off(dev: IotDevice) -> None:
            await dev.turn_off()  # pyright: ignore[reportUnknownMemberType]

        await self._run_for_current_devices_and_refresh(_turn_off, "Command timed out for")

    async def set_all_color(self, color_hsv: tuple[int, int, int], brightness: int) -> None:
        async def _set_color(dev: IotDevice) -> None:
            light = dev.modules[Module.Light]
            await light.set_hsv(*color_hsv)
            await light.set_brightness(brightness)
            await dev.turn_on()  # pyright: ignore[reportUnknownMemberType]

        await self._run_for_current_devices_and_refresh(_set_color, "Command timed out for")

    async def set_all_brightness(self, brightness: int) -> None:
        async def _set_brightness(dev: IotDevice) -> None:
            light = dev.modules[Module.Light]
            await light.set_brightness(brightness)
            await dev.turn_on()  # pyright: ignore[reportUnknownMemberType]

        await self._run_for_current_devices_and_refresh(_set_brightness, "Command timed out for")

    async def set_color_on_active_lights(self, color_hsv: tuple[int, int, int], brightness: int) -> None:
        def _on_devices(devices: list[IotDevice]) -> list[IotDevice]:
            return [dev for dev in devices if dev.is_on]

        async def _set_color_if_on(dev: IotDevice) -> None:
            light = dev.modules[Module.Light]
            await light.set_hsv(*color_hsv)
            await light.set_brightness(brightness)

        await self._run_for_current_devices_and_refresh(
            _set_color_if_on,
            "Color command timed out for",
            device_selector=_on_devices,
            empty_message="No lights are currently on; skipping color update.",
        )
