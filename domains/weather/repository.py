from datetime import datetime
from typing import Any

import httpx


class WeatherRepository:
    _instance = None
    DEFAULT_LOCATION = "Nashville, TN"
    GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    WEATHER_CODE_MAP = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    UNIT_CONFIG = {
        "imperial": {
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "temp_symbol": "F",
            "wind_symbol": "mph",
        },
        "metric": {
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "temp_symbol": "C",
            "wind_symbol": "km/h",
        },
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

    @staticmethod
    def _normalize_location(location: str) -> str:
        normalized = location.strip()
        return normalized or WeatherRepository.DEFAULT_LOCATION

    @staticmethod
    def _location_queries(location: str) -> list[str]:
        normalized = WeatherRepository._normalize_location(location)
        queries: list[str] = []

        def _add(candidate: str) -> None:
            value = " ".join(candidate.strip().split())
            if value and value not in queries:
                queries.append(value)

        _add(normalized)
        _add(normalized.replace(",", " "))

        if "," in normalized:
            city = normalized.split(",", maxsplit=1)[0].strip()
            _add(city)

        return queries

    @staticmethod
    def _format_location(result: dict[str, Any]) -> str:
        name = result.get("name")
        admin1 = result.get("admin1")
        country = result.get("country_code") or result.get("country")
        parts = [part for part in [name, admin1, country] if part]
        return ", ".join(parts) if parts else WeatherRepository.DEFAULT_LOCATION

    @staticmethod
    def _format_number(value: Any) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, (int, float)):
            rounded = round(float(value), 1)
            if rounded.is_integer():
                return str(int(rounded))
            return str(rounded)
        return str(value)

    async def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"Weather provider request failed ({response.status_code}) at {url}: "
                    f"{response.text or 'Unknown error'}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError(f"Weather provider returned invalid JSON from {url}") from exc

    async def _geocode(self, location: str) -> list[dict[str, Any]]:
        payload = await self._get_json(
            self.GEOCODE_URL,
            {
                "name": location,
                "count": 1,
                "language": "en",
                "format": "json",
            },
        )
        results = payload.get("results")
        if isinstance(results, list):
            return [entry for entry in results if isinstance(entry, dict)]
        return []

    async def resolve_location(self, location: str) -> dict[str, Any]:
        requested_location = self._normalize_location(location)
        fallback_used = False

        results: list[dict[str, Any]] = []
        for query in self._location_queries(requested_location):
            results = await self._geocode(query)
            if results:
                break

        if not results:
            fallback_used = True
            for query in self._location_queries(self.DEFAULT_LOCATION):
                results = await self._geocode(query)
                if results:
                    break

        if not results:
            raise RuntimeError("Unable to resolve location from weather provider.")

        best = results[0]
        latitude = best.get("latitude")
        longitude = best.get("longitude")
        if latitude is None or longitude is None:
            raise RuntimeError("Weather provider geocoding returned incomplete coordinates.")

        resolved_location = self._format_location(best)
        return {
            "requested_location": requested_location,
            "resolved_location": resolved_location,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": best.get("timezone"),
            "fallback_used": fallback_used,
        }

    async def get_weather(self, location: str, units: str) -> dict[str, Any]:
        if units not in self.UNIT_CONFIG:
            raise RuntimeError("Unsupported unit system.")

        location_data = await self.resolve_location(location)
        unit_config = self.UNIT_CONFIG[units]

        forecast = await self._get_json(
            self.FORECAST_URL,
            {
                "latitude": location_data["latitude"],
                "longitude": location_data["longitude"],
                "current": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "wind_speed_10m,weather_code"
                ),
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": unit_config["temperature_unit"],
                "wind_speed_unit": unit_config["wind_speed_unit"],
                "timezone": "auto",
                "forecast_days": 1,
            },
        )

        current = forecast.get("current") or {}
        daily = forecast.get("daily") or {}
        today_high_values = daily.get("temperature_2m_max") or []
        today_low_values = daily.get("temperature_2m_min") or []

        current_temp = current.get("temperature_2m")
        feels_like = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        wind_speed = current.get("wind_speed_10m")
        weather_code = current.get("weather_code")
        today_high = today_high_values[0] if today_high_values else None
        today_low = today_low_values[0] if today_low_values else None
        condition = self.WEATHER_CODE_MAP.get(weather_code, "Unknown conditions")

        if current_temp is None and today_high is None and today_low is None:
            raise RuntimeError("Weather provider returned incomplete forecast data.")

        temp_symbol = unit_config["temp_symbol"]
        wind_symbol = unit_config["wind_symbol"]
        summary = (
            f"In {location_data['resolved_location']}, it is {self._format_number(current_temp)} {temp_symbol} "
            f"and {condition.lower()} with {self._format_number(wind_speed)} {wind_symbol} wind. "
            f"Today ranges from {self._format_number(today_low)} {temp_symbol} "
            f"to {self._format_number(today_high)} {temp_symbol}."
        )

        return {
            "requested_location": location_data["requested_location"],
            "resolved_location": location_data["resolved_location"],
            "fallback_used": location_data["fallback_used"],
            "units": units,
            "data": {
                "current_temperature": current_temp,
                "feels_like_temperature": feels_like,
                "humidity": humidity,
                "wind_speed": wind_speed,
                "condition": condition,
                "today_high": today_high,
                "today_low": today_low,
                "observation_time": current.get("time"),
                "temperature_unit": temp_symbol,
                "wind_speed_unit": wind_symbol,
            },
            "summary": summary,
        }

    async def get_sunset(self, location: str) -> dict[str, Any]:
        location_data = await self.resolve_location(location)
        forecast = await self._get_json(
            self.FORECAST_URL,
            {
                "latitude": location_data["latitude"],
                "longitude": location_data["longitude"],
                "daily": "sunset",
                "timezone": "auto",
                "forecast_days": 1,
            },
        )

        daily = forecast.get("daily") or {}
        sunset_values = daily.get("sunset") or []
        sunset_raw = sunset_values[0] if sunset_values else None
        if not sunset_raw:
            raise RuntimeError("Weather provider returned no sunset data.")

        try:
            sunset_at = datetime.fromisoformat(sunset_raw)
        except ValueError as exc:
            raise RuntimeError("Weather provider returned invalid sunset timestamp.") from exc

        return {
            "requested_location": location_data["requested_location"],
            "resolved_location": location_data["resolved_location"],
            "fallback_used": location_data["fallback_used"],
            "sunset": sunset_at.isoformat(),
        }
