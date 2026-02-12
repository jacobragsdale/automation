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
