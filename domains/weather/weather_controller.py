from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from domains.weather import weather_handler as handler

router = APIRouter(tags=["Weather"])


@router.get("/weather")
async def get_weather(location: str = "Nashville, TN", units: Literal["imperial", "metric"] = "imperial") -> dict:
    try:
        weather = await handler.get_weather(location=location, units=units)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "weather", "status": "ok", **weather}


@router.get("/weather/forecast/daily")
async def get_daily_forecast(
    location: str = "Nashville, TN",
    units: Literal["imperial", "metric"] = "imperial",
    days: Annotated[int, Query(ge=1, le=16)] = 5,
) -> dict:
    try:
        forecast = await handler.get_daily_forecast(location=location, units=units, days=days)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "weather_forecast_daily", "status": "ok", **forecast}


@router.get("/weather/forecast/hourly")
async def get_hourly_forecast(
    location: str = "Nashville, TN",
    units: Literal["imperial", "metric"] = "imperial",
    hours: Annotated[int, Query(ge=1, le=168)] = 24,
) -> dict:
    try:
        forecast = await handler.get_hourly_forecast(location=location, units=units, hours=hours)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "weather_forecast_hourly", "status": "ok", **forecast}
