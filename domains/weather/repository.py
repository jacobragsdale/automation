from datetime import datetime
from math import ceil
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

    @staticmethod
    def _parse_provider_datetime(value: Any) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _get_unit_config(self, units: str) -> dict[str, str]:
        if units not in self.UNIT_CONFIG:
            raise RuntimeError("Unsupported unit system.")
        return self.UNIT_CONFIG[units]

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
        unit_config = self._get_unit_config(units)
        location_data = await self.resolve_location(location)

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

    async def get_daily_forecast(self, location: str, units: str, days: int) -> dict[str, Any]:
        if days < 1 or days > 16:
            raise RuntimeError("days must be between 1 and 16.")

        unit_config = self._get_unit_config(units)
        location_data = await self.resolve_location(location)
        forecast = await self._get_json(
            self.FORECAST_URL,
            {
                "latitude": location_data["latitude"],
                "longitude": location_data["longitude"],
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "temperature_unit": unit_config["temperature_unit"],
                "timezone": "auto",
                "forecast_days": days,
            },
        )

        daily = forecast.get("daily") or {}
        times = daily.get("time") or []
        highs = daily.get("temperature_2m_max") or []
        lows = daily.get("temperature_2m_min") or []
        weather_codes = daily.get("weather_code") or []
        precipitation = daily.get("precipitation_probability_max") or []

        entries: list[dict[str, Any]] = []
        for index, date_value in enumerate(times):
            weather_code = weather_codes[index] if index < len(weather_codes) else None
            entries.append(
                {
                    "date": date_value,
                    "condition": self.WEATHER_CODE_MAP.get(weather_code, "Unknown conditions"),
                    "weather_code": weather_code,
                    "high_temperature": highs[index] if index < len(highs) else None,
                    "low_temperature": lows[index] if index < len(lows) else None,
                    "precipitation_probability_max": (
                        precipitation[index] if index < len(precipitation) else None
                    ),
                }
            )

        if not entries:
            raise RuntimeError("Weather provider returned incomplete daily forecast data.")

        temp_symbol = unit_config["temp_symbol"]
        summary = (
            f"{len(entries)}-day forecast for {location_data['resolved_location']}: "
            f"{entries[0]['date']} through {entries[-1]['date']}."
        )

        return {
            "requested_location": location_data["requested_location"],
            "resolved_location": location_data["resolved_location"],
            "fallback_used": location_data["fallback_used"],
            "units": units,
            "days": days,
            "data": {
                "forecast": entries,
                "temperature_unit": temp_symbol,
            },
            "summary": summary,
        }

    async def get_hourly_forecast(self, location: str, units: str, hours: int) -> dict[str, Any]:
        if hours < 1 or hours > 168:
            raise RuntimeError("hours must be between 1 and 168.")

        unit_config = self._get_unit_config(units)
        location_data = await self.resolve_location(location)
        forecast_days = min(16, max(1, ceil(hours / 24) + 1))
        forecast = await self._get_json(
            self.FORECAST_URL,
            {
                "latitude": location_data["latitude"],
                "longitude": location_data["longitude"],
                "current": "temperature_2m",
                "hourly": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "wind_speed_10m,precipitation_probability,weather_code"
                ),
                "temperature_unit": unit_config["temperature_unit"],
                "wind_speed_unit": unit_config["wind_speed_unit"],
                "timezone": "auto",
                "forecast_days": forecast_days,
            },
        )

        hourly = forecast.get("hourly") or {}
        times = hourly.get("time") or []
        temperatures = hourly.get("temperature_2m") or []
        apparent_temperatures = hourly.get("apparent_temperature") or []
        humidity = hourly.get("relative_humidity_2m") or []
        wind_speed = hourly.get("wind_speed_10m") or []
        precipitation = hourly.get("precipitation_probability") or []
        weather_codes = hourly.get("weather_code") or []

        current = forecast.get("current") or {}
        current_time = self._parse_provider_datetime(current.get("time"))

        entries: list[dict[str, Any]] = []
        for index, timestamp_raw in enumerate(times):
            timestamp = self._parse_provider_datetime(timestamp_raw)
            if timestamp is None:
                continue
            if current_time is not None and timestamp <= current_time:
                continue

            weather_code = weather_codes[index] if index < len(weather_codes) else None
            entries.append(
                {
                    "time": timestamp.isoformat(timespec="minutes"),
                    "condition": self.WEATHER_CODE_MAP.get(weather_code, "Unknown conditions"),
                    "weather_code": weather_code,
                    "temperature": temperatures[index] if index < len(temperatures) else None,
                    "feels_like_temperature": (
                        apparent_temperatures[index] if index < len(apparent_temperatures) else None
                    ),
                    "humidity": humidity[index] if index < len(humidity) else None,
                    "wind_speed": wind_speed[index] if index < len(wind_speed) else None,
                    "precipitation_probability": (
                        precipitation[index] if index < len(precipitation) else None
                    ),
                }
            )
            if len(entries) >= hours:
                break

        if not entries:
            raise RuntimeError("Weather provider returned no future hourly forecast data.")

        temp_symbol = unit_config["temp_symbol"]
        wind_symbol = unit_config["wind_symbol"]
        summary = (
            f"Next {len(entries)} hours in {location_data['resolved_location']} from "
            f"{entries[0]['time']} to {entries[-1]['time']}."
        )

        return {
            "requested_location": location_data["requested_location"],
            "resolved_location": location_data["resolved_location"],
            "fallback_used": location_data["fallback_used"],
            "units": units,
            "hours_requested": hours,
            "hours_returned": len(entries),
            "data": {
                "forecast": entries,
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
