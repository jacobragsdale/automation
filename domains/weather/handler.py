from typing import Any

from domains.weather.repository import WeatherRepository

weather_repository = WeatherRepository()


async def get_weather(location: str, units: str) -> dict[str, Any]:
    return await weather_repository.get_weather(location=location, units=units)


async def get_sunset(location: str) -> dict[str, Any]:
    return await weather_repository.get_sunset(location=location)
