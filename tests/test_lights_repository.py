import asyncio

import pytest

from domains.lights.lights_repository import LightsRepository


class FakeCloudModule:
    def __init__(self, *, provisioned: bool = False, username: str = "") -> None:
        self.bind_calls: list[dict[str, str]] = []
        self._provisioned = provisioned
        self._username = username

    @property
    def info(self) -> "FakeCloudInfo":
        return FakeCloudInfo(provisioned=self._provisioned, username=self._username)

    async def call(self, method: str, params: dict[str, str] | None = None) -> dict[str, object]:
        if method == "bind":
            self.bind_calls.append(params or {})
        return {}


class FakeCloudInfo:
    def __init__(self, *, provisioned: bool, username: str) -> None:
        self.provisioned = provisioned
        self.username = username


class FakeDevice:
    def __init__(self, alias: str) -> None:
        self.alias = alias
        self.commands: list[str] = []
        self.modules: dict[object, object] = {}

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


@pytest.mark.asyncio
async def test_discover_devices_scans_saved_subnet_when_broadcast_misses(monkeypatch):
    repository = LightsRepository()
    discovered_device = FakeDevice("Moved")
    repository.devices = {}
    repository._last_discovery = 0
    repository._discovery_lock = asyncio.Lock()

    monkeypatch.setattr(repository, "_load_saved_device_ips", lambda: {"192.168.8.143"})
    monkeypatch.setattr(repository, "_save_device_ips", lambda device_ips: None)

    async def fake_discover_ips(
        ips,
        *,
        discovery_timeout=repository.DISCOVERY_TIMEOUT,
        command_timeout=repository.COMMAND_TIMEOUT,
        log_errors=True,
        concurrency=None,
    ):
        del discovery_timeout, command_timeout, log_errors, concurrency
        if "192.168.8.145" in ips:
            return {"192.168.8.145": discovered_device}
        return {}

    async def fake_broadcast_discover():
        return {}

    monkeypatch.setattr(repository, "_discover_ips", fake_discover_ips)
    monkeypatch.setattr(repository, "_broadcast_discover", fake_broadcast_discover)

    devices = await repository.discover_devices(force_refresh=True)

    assert devices == {"192.168.8.145": discovered_device}


@pytest.mark.asyncio
async def test_cloud_bind_calls_bind_when_unprovisioned(monkeypatch):
    from kasa import Module

    repository = LightsRepository()
    cloud = FakeCloudModule(provisioned=False)
    device = FakeDevice("Bulb")
    device.modules = {Module.IotCloud: cloud}
    repository.devices = {"192.168.1.1": device}  # type: ignore[dict-item]

    monkeypatch.setenv("KASA_CLOUD_USERNAME", "user@example.com")
    monkeypatch.setenv("KASA_CLOUD_PASSWORD", "secret")

    await repository._ensure_all_cloud_bound()

    assert cloud.bind_calls == [{"username": "user@example.com", "password": "secret"}]


@pytest.mark.asyncio
async def test_cloud_bind_skips_when_already_bound_to_correct_account(monkeypatch):
    from kasa import Module

    repository = LightsRepository()
    cloud = FakeCloudModule(provisioned=True, username="user@example.com")
    device = FakeDevice("Bulb")
    device.modules = {Module.IotCloud: cloud}
    repository.devices = {"192.168.1.1": device}  # type: ignore[dict-item]

    monkeypatch.setenv("KASA_CLOUD_USERNAME", "user@example.com")
    monkeypatch.setenv("KASA_CLOUD_PASSWORD", "secret")

    await repository._ensure_all_cloud_bound()

    assert cloud.bind_calls == []


@pytest.mark.asyncio
async def test_cloud_bind_rebinds_when_bound_to_different_account(monkeypatch):
    from kasa import Module

    repository = LightsRepository()
    cloud = FakeCloudModule(provisioned=True, username="old@example.com")
    device = FakeDevice("Bulb")
    device.modules = {Module.IotCloud: cloud}
    repository.devices = {"192.168.1.1": device}  # type: ignore[dict-item]

    monkeypatch.setenv("KASA_CLOUD_USERNAME", "new@example.com")
    monkeypatch.setenv("KASA_CLOUD_PASSWORD", "newsecret")

    await repository._ensure_all_cloud_bound()

    assert cloud.bind_calls == [{"username": "new@example.com", "password": "newsecret"}]


@pytest.mark.asyncio
async def test_cloud_bind_skips_when_env_vars_missing(monkeypatch):
    from kasa import Module

    repository = LightsRepository()
    cloud = FakeCloudModule(provisioned=False)
    device = FakeDevice("Bulb")
    device.modules = {Module.IotCloud: cloud}
    repository.devices = {"192.168.1.1": device}  # type: ignore[dict-item]

    monkeypatch.delenv("KASA_CLOUD_USERNAME", raising=False)
    monkeypatch.delenv("KASA_CLOUD_PASSWORD", raising=False)

    result = await repository._ensure_all_cloud_bound()

    assert result == {}
    assert cloud.bind_calls == []


@pytest.mark.asyncio
async def test_cloud_bind_continues_when_one_device_fails(monkeypatch):
    from kasa import Module

    repository = LightsRepository()

    cloud_ok = FakeCloudModule(provisioned=False)
    device_ok = FakeDevice("GoodBulb")
    device_ok.modules = {Module.IotCloud: cloud_ok}

    cloud_bad = FakeCloudModule(provisioned=False)

    async def _raise(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("timeout")

    cloud_bad.call = _raise  # type: ignore[method-assign]
    device_bad = FakeDevice("BadBulb")
    device_bad.modules = {Module.IotCloud: cloud_bad}

    repository.devices = {  # type: ignore[dict-item]
        "192.168.1.1": device_ok,
        "192.168.1.2": device_bad,
    }

    monkeypatch.setenv("KASA_CLOUD_USERNAME", "user@example.com")
    monkeypatch.setenv("KASA_CLOUD_PASSWORD", "secret")

    result = await repository._ensure_all_cloud_bound()

    assert result["192.168.1.1"] is True
    assert result["192.168.1.2"] is False
    assert cloud_ok.bind_calls == [{"username": "user@example.com", "password": "secret"}]
