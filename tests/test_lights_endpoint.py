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


def test_lights_color_rejects_out_of_range_hue():
    with pytest.raises(ValidationError):
        lights_controller.ColorRequest(hsv=(361, 50, 50))


def test_lights_color_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        lights_controller.ColorRequest.model_validate({"hsv": [30, 40, 90], "color": "red"})


def test_lights_color_requires_three_hsv_values():
    with pytest.raises(ValidationError):
        lights_controller.ColorRequest.model_validate({"hsv": [30, 40]})
