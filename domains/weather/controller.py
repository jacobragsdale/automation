from typing import Literal

from fastapi import APIRouter, HTTPException

from domains.weather import handler

router = APIRouter(tags=["Weather"])


@router.get("/weather")
async def get_weather(location: str = "Nashville, TN", units: Literal["imperial", "metric"] = "imperial") -> dict:
    try:
        weather = await handler.get_weather(location=location, units=units)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "weather", "status": "ok", **weather}
