import pytest
from pydantic import ValidationError

from domains.lights import lights_controller
from domains.lights import lights_handler


@pytest.mark.asyncio
async def test_lights_color_passes_hsv_to_handler(monkeypatch):
    captured: dict[str, tuple[int, int, int]] = {}

    async def fake_set_color(hsv: tuple[int, int, int]) -> None:
        captured["hsv"] = hsv

    monkeypatch.setattr(lights_handler, "set_color", fake_set_color)

    payload = lights_controller.ColorRequest(hsv=(220, 90, 75))
    response = await lights_controller.set_lights_color(payload)

    assert captured["hsv"] == (220, 90, 75)
    assert response == {"action": "lights_color", "hsv": [220, 90, 75], "status": "ok"}


@pytest.mark.asyncio
async def test_lights_brightness_passes_value_to_handler(monkeypatch):
    captured: dict[str, int] = {}

    async def fake_set_brightness(brightness: int) -> None:
        captured["brightness"] = brightness

    monkeypatch.setattr(lights_handler, "set_brightness", fake_set_brightness)

    payload = lights_controller.BrightnessRequest(brightness=42)
    response = await lights_controller.set_lights_brightness(payload)

    assert captured["brightness"] == 42
    assert response == {"action": "lights_brightness", "brightness": 42, "status": "ok"}


@pytest.mark.asyncio
async def test_lights_scan_endpoint_forces_device_scan(monkeypatch):
    devices = [{"host": "192.168.1.20", "alias": "Desk"}]
    called = False

    async def fake_scan_devices() -> list[dict[str, object]]:
        nonlocal called
        called = True
        return devices

    monkeypatch.setattr(lights_handler, "scan_devices", fake_scan_devices)

    response = await lights_controller.scan_devices()

    assert called is True
    assert response == {"action": "lights_devices_scan", "count": 1, "data": devices, "status": "ok"}


def test_lights_color_rejects_out_of_range_hue():
    with pytest.raises(ValidationError):
        lights_controller.ColorRequest(hsv=(361, 50, 50))


def test_lights_brightness_rejects_out_of_range_value():
    with pytest.raises(ValidationError):
        lights_controller.BrightnessRequest(brightness=101)


def test_lights_color_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        lights_controller.ColorRequest.model_validate({"hsv": [30, 40, 90], "color": "red"})


def test_lights_brightness_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        lights_controller.BrightnessRequest.model_validate({"brightness": 50, "value": 50})


def test_lights_color_requires_three_hsv_values():
    with pytest.raises(ValidationError):
        lights_controller.ColorRequest.model_validate({"hsv": [30, 40]})
