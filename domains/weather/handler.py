from typing import Any

from domains.weather.repository import WeatherRepository

weather_repository = WeatherRepository()


async def get_weather(location: str, units: str) -> dict[str, Any]:
    return await weather_repository.get_weather(location=location, units=units)


async def get_daily_forecast(location: str, units: str, days: int) -> dict[str, Any]:
    return await weather_repository.get_daily_forecast(location=location, units=units, days=days)


async def get_hourly_forecast(location: str, units: str, hours: int) -> dict[str, Any]:
    return await weather_repository.get_hourly_forecast(location=location, units=units, hours=hours)


async def get_sunset(location: str) -> dict[str, Any]:
    return await weather_repository.get_sunset(location=location)
