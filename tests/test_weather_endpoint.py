import pytest
from fastapi import HTTPException

from domains.weather import handler as weather_handler
from domains.weather import controller as weather_controller
from domains.weather.repository import WeatherRepository


def _sample_forecast_payload() -> dict:
    return {
        "current": {
            "time": "2026-02-10T15:00",
            "temperature_2m": 52.1,
            "apparent_temperature": 49.8,
            "relative_humidity_2m": 61,
            "wind_speed_10m": 8.4,
            "weather_code": 2,
        },
        "daily": {
            "temperature_2m_max": [61.2],
            "temperature_2m_min": [46.4],
        },
    }


def _sample_daily_forecast_payload() -> dict:
    return {
        "daily": {
            "time": ["2026-02-10", "2026-02-11", "2026-02-12"],
            "weather_code": [2, 61, 3],
            "temperature_2m_max": [61.2, 58.8, 55.1],
            "temperature_2m_min": [46.4, 44.2, 41.0],
            "precipitation_probability_max": [20, 70, 40],
        }
    }


def _sample_hourly_forecast_payload() -> dict:
    return {
        "current": {
            "time": "2026-02-10T15:00",
        },
        "hourly": {
            "time": [
                "2026-02-10T13:00",
                "2026-02-10T14:00",
                "2026-02-10T15:00",
                "2026-02-10T16:00",
                "2026-02-10T17:00",
            ],
            "temperature_2m": [49.1, 50.2, 51.0, 52.3, 53.0],
            "apparent_temperature": [47.8, 48.5, 49.9, 50.4, 51.2],
            "relative_humidity_2m": [70, 68, 66, 64, 61],
            "wind_speed_10m": [5.0, 5.5, 6.0, 7.1, 7.8],
            "precipitation_probability": [10, 10, 15, 20, 25],
            "weather_code": [1, 1, 2, 2, 3],
        },
    }


@pytest.mark.asyncio
async def test_weather_defaults_to_nashville(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_run_weather_handler(location: str, units: str):
        captured["location"] = location
        captured["units"] = units
        return {
            "requested_location": location,
            "resolved_location": "Nashville, Tennessee, US",
            "fallback_used": False,
            "units": units,
            "data": {},
            "summary": "Weather summary",
        }

    monkeypatch.setattr(weather_handler, "get_weather", fake_run_weather_handler)

    payload = await weather_controller.get_weather()

    assert captured["location"] == "Nashville, TN"
    assert captured["units"] == "imperial"
    assert payload["action"] == "weather"
    assert payload["status"] == "ok"
    assert payload["resolved_location"] == "Nashville, Tennessee, US"


@pytest.mark.asyncio
async def test_weather_custom_location_success(monkeypatch):
    async def fake_get_json(self, url: str, params: dict):
        if url == self.GEOCODE_URL:
            assert params["name"] == "Austin,TX"
            return {
                "results": [
                    {
                        "name": "Austin",
                        "admin1": "Texas",
                        "country_code": "US",
                        "latitude": 30.2672,
                        "longitude": -97.7431,
                    }
                ]
            }
        if url == self.FORECAST_URL:
            return _sample_forecast_payload()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(WeatherRepository, "_get_json", fake_get_json)

    payload = await WeatherRepository().get_weather(location="Austin,TX", units="imperial")

    assert payload["requested_location"] == "Austin,TX"
    assert payload["resolved_location"] == "Austin, Texas, US"
    assert payload["fallback_used"] is False
    assert payload["units"] == "imperial"
    assert payload["data"]["current_temperature"] == 52.1
    assert payload["data"]["today_high"] == 61.2


@pytest.mark.asyncio
async def test_weather_bad_location_falls_back_to_nashville(monkeypatch):
    geocode_calls: list[str] = []

    async def fake_get_json(self, url: str, params: dict):
        if url == self.GEOCODE_URL:
            geocode_calls.append(params["name"])
            if params["name"] == "NotARealPlace":
                return {"results": []}
            if params["name"] == "Nashville, TN":
                return {
                    "results": [
                        {
                            "name": "Nashville",
                            "admin1": "Tennessee",
                            "country_code": "US",
                            "latitude": 36.1627,
                            "longitude": -86.7816,
                        }
                    ]
                }
        if url == self.FORECAST_URL:
            return _sample_forecast_payload()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(WeatherRepository, "_get_json", fake_get_json)

    payload = await WeatherRepository().get_weather(location="NotARealPlace", units="imperial")

    assert geocode_calls == ["NotARealPlace", "Nashville, TN"]
    assert payload["resolved_location"] == "Nashville, Tennessee, US"
    assert payload["fallback_used"] is True


@pytest.mark.asyncio
async def test_weather_units_metric(monkeypatch):
    forecast_params: dict = {}

    async def fake_get_json(self, url: str, params: dict):
        if url == self.GEOCODE_URL:
            return {
                "results": [
                    {
                        "name": "London",
                        "admin1": "England",
                        "country_code": "GB",
                        "latitude": 51.5072,
                        "longitude": -0.1276,
                    }
                ]
            }
        if url == self.FORECAST_URL:
            forecast_params.update(params)
            return _sample_forecast_payload()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(WeatherRepository, "_get_json", fake_get_json)

    payload = await WeatherRepository().get_weather(location="London", units="metric")

    assert forecast_params["temperature_unit"] == "celsius"
    assert forecast_params["wind_speed_unit"] == "kmh"
    assert payload["units"] == "metric"
    assert payload["data"]["temperature_unit"] == "C"
    assert payload["data"]["wind_speed_unit"] == "km/h"


@pytest.mark.asyncio
async def test_weather_upstream_failure_returns_502(monkeypatch):
    async def fake_run_weather_handler(location: str, units: str):
        raise RuntimeError("Open-Meteo unavailable")

    monkeypatch.setattr(weather_handler, "get_weather", fake_run_weather_handler)

    with pytest.raises(HTTPException) as exc_info:
        await weather_controller.get_weather(location="Austin,TX", units="imperial")

    assert exc_info.value.status_code == 502
    assert "Open-Meteo unavailable" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_weather_summary_is_human_readable(monkeypatch):
    async def fake_get_json(self, url: str, params: dict):
        if url == self.GEOCODE_URL:
            return {
                "results": [
                    {
                        "name": "Nashville",
                        "admin1": "Tennessee",
                        "country_code": "US",
                        "latitude": 36.1627,
                        "longitude": -86.7816,
                    }
                ]
            }
        if url == self.FORECAST_URL:
            return _sample_forecast_payload()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(WeatherRepository, "_get_json", fake_get_json)

    payload = await WeatherRepository().get_weather(location="Nashville, TN", units="imperial")
    summary = payload["summary"]

    assert "Nashville, Tennessee, US" in summary
    assert "partly cloudy" in summary
    assert "Today ranges from" in summary


@pytest.mark.asyncio
async def test_daily_forecast_defaults_to_nashville(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_daily_handler(location: str, units: str, days: int):
        captured["location"] = location
        captured["units"] = units
        captured["days"] = days
        return {
            "requested_location": location,
            "resolved_location": "Nashville, Tennessee, US",
            "fallback_used": False,
            "units": units,
            "days": days,
            "data": {"forecast": [], "temperature_unit": "F"},
            "summary": "Forecast summary",
        }

    monkeypatch.setattr(weather_handler, "get_daily_forecast", fake_run_daily_handler)

    payload = await weather_controller.get_daily_forecast()

    assert captured["location"] == "Nashville, TN"
    assert captured["units"] == "imperial"
    assert captured["days"] == 5
    assert payload["action"] == "weather_forecast_daily"
    assert payload["status"] == "ok"


@pytest.mark.asyncio
async def test_hourly_forecast_upstream_failure_returns_502(monkeypatch):
    async def fake_run_hourly_handler(location: str, units: str, hours: int):
        raise RuntimeError("Open-Meteo unavailable")

    monkeypatch.setattr(weather_handler, "get_hourly_forecast", fake_run_hourly_handler)

    with pytest.raises(HTTPException) as exc_info:
        await weather_controller.get_hourly_forecast(location="Austin,TX", units="imperial", hours=12)

    assert exc_info.value.status_code == 502
    assert "Open-Meteo unavailable" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_daily_forecast_repository_uses_units_and_days(monkeypatch):
    forecast_params: dict = {}

    async def fake_get_json(self, url: str, params: dict):
        if url == self.GEOCODE_URL:
            return {
                "results": [
                    {
                        "name": "Austin",
                        "admin1": "Texas",
                        "country_code": "US",
                        "latitude": 30.2672,
                        "longitude": -97.7431,
                    }
                ]
            }
        if url == self.FORECAST_URL:
            forecast_params.update(params)
            return _sample_daily_forecast_payload()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(WeatherRepository, "_get_json", fake_get_json)

    payload = await WeatherRepository().get_daily_forecast(location="Austin,TX", units="metric", days=3)

    assert forecast_params["temperature_unit"] == "celsius"
    assert forecast_params["forecast_days"] == 3
    assert payload["units"] == "metric"
    assert payload["days"] == 3
    assert payload["data"]["temperature_unit"] == "C"
    assert payload["data"]["forecast"][1]["condition"] == "Slight rain"


@pytest.mark.asyncio
async def test_hourly_forecast_repository_filters_past_hours(monkeypatch):
    forecast_params: dict = {}

    async def fake_get_json(self, url: str, params: dict):
        if url == self.GEOCODE_URL:
            return {
                "results": [
                    {
                        "name": "Nashville",
                        "admin1": "Tennessee",
                        "country_code": "US",
                        "latitude": 36.1627,
                        "longitude": -86.7816,
                    }
                ]
            }
        if url == self.FORECAST_URL:
            forecast_params.update(params)
            return _sample_hourly_forecast_payload()
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(WeatherRepository, "_get_json", fake_get_json)

    payload = await WeatherRepository().get_hourly_forecast(
        location="Nashville, TN",
        units="imperial",
        hours=2,
    )

    assert forecast_params["wind_speed_unit"] == "mph"
    assert forecast_params["forecast_days"] == 2
    assert payload["hours_requested"] == 2
    assert payload["hours_returned"] == 2
    assert payload["data"]["forecast"][0]["time"] == "2026-02-10T16:00"
    assert payload["data"]["forecast"][1]["time"] == "2026-02-10T17:00"
