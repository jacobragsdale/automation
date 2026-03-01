from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from domains.lights import lights_handler as handler

router = APIRouter(prefix="/lights", tags=["Lights"])

Hue = Annotated[int, Field(ge=0, le=360)]
Saturation = Annotated[int, Field(ge=0, le=100)]
Value = Annotated[int, Field(ge=0, le=100)]


class ColorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hsv: tuple[Hue, Saturation, Value]


@router.post("/scenes/morning")
async def run_morning_scene() -> dict[str, str]:
    await handler.run_morning_scene()
    return {"action": "lights_scene_morning", "status": "ok"}


@router.post("/scenes/night")
async def run_night_scene() -> dict[str, str]:
    await handler.run_night_scene()
    return {"action": "lights_scene_night", "status": "ok"}


@router.post("/power/on")
async def turn_lights_on() -> dict[str, str]:
    await handler.turn_all_lights_on()
    return {"action": "lights_power_on", "status": "ok"}


@router.post("/power/off")
async def turn_lights_off() -> dict[str, str]:
    await handler.turn_all_lights_off()
    return {"action": "lights_power_off", "status": "ok"}


@router.post("/color")
async def set_lights_color(payload: ColorRequest) -> dict[str, object]:
    await handler.set_color(payload.hsv)
    return {"action": "lights_color", "hsv": list(payload.hsv), "status": "ok"}


@router.get("/devices")
async def get_devices(force_refresh: bool = False) -> dict:
    devices = await handler.get_devices(force_refresh=force_refresh)
    return {"action": "lights_devices", "count": len(devices), "data": devices, "status": "ok"}
