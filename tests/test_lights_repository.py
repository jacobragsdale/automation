import asyncio

import pytest

from domains.lights.lights_repository import LightsRepository


class FakeDevice:
    def __init__(self, alias: str) -> None:
        self.alias = alias
        self.commands: list[str] = []

    async def turn_on(self) -> None:
        self.commands.append("on")


@pytest.mark.asyncio
async def test_light_command_scans_and_reruns_in_background(monkeypatch):
    repository = LightsRepository()
    cached_device = FakeDevice("Cached")
    refreshed_device = FakeDevice("Refreshed")
    repository.devices = {"192.168.1.10": cached_device}  # type: ignore[dict-item]
    repository._background_tasks.clear()

    force_refresh_values: list[bool] = []
    commanded_aliases: list[str] = []
    refresh_commanded = asyncio.Event()

    async def fake_discover_devices(force_refresh: bool = False):
        force_refresh_values.append(force_refresh)
        if force_refresh:
            repository.devices = {"192.168.1.11": refreshed_device}  # type: ignore[dict-item]
        return repository.devices

    async def fake_update_all() -> None:
        return None

    async def fake_run_for_devices(devices, command_factory, timeout_message_prefix):
        del timeout_message_prefix
        for device in devices:
            await command_factory(device)
            commanded_aliases.append(device.alias)
            if device.alias == "Refreshed":
                refresh_commanded.set()

    monkeypatch.setattr(repository, "discover_devices", fake_discover_devices)
    monkeypatch.setattr(repository, "_update_all", fake_update_all)
    monkeypatch.setattr(repository, "_run_for_devices", fake_run_for_devices)

    await repository.turn_all_on()
    await asyncio.wait_for(refresh_commanded.wait(), timeout=1)
    await asyncio.sleep(0)

    assert force_refresh_values == [False, True]
    assert commanded_aliases == ["Cached", "Refreshed"]
    assert cached_device.commands == ["on"]
    assert refreshed_device.commands == ["on"]
    assert repository._background_tasks == set()
