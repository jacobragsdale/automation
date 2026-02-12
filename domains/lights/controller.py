from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from domains.lights import handler

router = APIRouter(prefix="/lights", tags=["Lights"])


class ColorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    color: str = Field(min_length=1)


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
async def set_lights_color(payload: ColorRequest) -> dict[str, str]:
    success = await handler.set_color(payload.color)
    if not success:
        raise HTTPException(status_code=400, detail="Unsupported color value.")
    return {"action": "lights_color", "color": payload.color, "status": "ok"}


@router.get("/devices")
async def get_devices(force_refresh: bool = False) -> dict:
    devices = await handler.get_devices(force_refresh=force_refresh)
    return {"action": "lights_devices", "count": len(devices), "data": devices, "status": "ok"}
