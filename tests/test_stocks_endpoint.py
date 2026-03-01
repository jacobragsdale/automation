import time
from typing import Any

import pytest
from fastapi import HTTPException

from domains.stocks import stocks_controller
from domains.stocks import stocks_handler
from domains.stocks.stocks_repository import StocksRepository


@pytest.fixture(autouse=True)
def reset_stocks_repository_state(monkeypatch):
    repository = StocksRepository()
    repository._cache.clear()
    repository._cache_ttl_seconds = 300
    repository._api_key = "test-api-key"
    monkeypatch.setenv("FMP_API_KEY", "test-api-key")


@pytest.mark.asyncio
async def test_stocks_quote_endpoint_returns_expected_envelope(monkeypatch):
    async def fake_get_quote(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        assert symbol == "aapl"
        assert force_refresh is False
        return {
            "action": "stocks_quote",
            "status": "ok",
            "symbol": "AAPL",
            "provider": "fmp",
            "cached": False,
            "data": {"price": 215.5},
        }

    monkeypatch.setattr(stocks_handler, "get_quote", fake_get_quote)

    payload = await stocks_controller.get_quote(symbol="aapl")

    assert payload["action"] == "stocks_quote"
    assert payload["status"] == "ok"
    assert payload["symbol"] == "AAPL"
    assert payload["provider"] == "fmp"
    assert payload["cached"] is False
    assert payload["data"]["price"] == 215.5


@pytest.mark.asyncio
async def test_stocks_ratios_endpoint_contains_pe_ratio(monkeypatch):
    async def fake_get_ratios(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        assert symbol == "MSFT"
        return {
            "action": "stocks_ratios",
            "status": "ok",
            "symbol": "MSFT",
            "provider": "fmp",
            "cached": False,
            "data": {"pe_ratio_ttm": 34.2},
        }

    monkeypatch.setattr(stocks_handler, "get_ratios", fake_get_ratios)

    payload = await stocks_controller.get_ratios(symbol="MSFT")

    assert payload["action"] == "stocks_ratios"
    assert payload["data"]["pe_ratio_ttm"] == 34.2


@pytest.mark.asyncio
async def test_stocks_company_endpoint_returns_company_fields(monkeypatch):
    async def fake_get_company(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        return {
            "action": "stocks_company",
            "status": "ok",
            "symbol": "NVDA",
            "provider": "fmp",
            "cached": False,
            "data": {
                "name": "NVIDIA Corporation",
                "exchange": "NASDAQ",
                "industry": "Semiconductors",
                "sector": "Technology",
                "website": "https://nvidia.com",
                "ceo": "Jensen Huang",
                "country": "US",
                "description": "GPU company",
                "market_cap": 100,
                "beta": 1.2,
            },
        }

    monkeypatch.setattr(stocks_handler, "get_company", fake_get_company)

    payload = await stocks_controller.get_company(symbol="NVDA")

    assert payload["action"] == "stocks_company"
    assert payload["data"]["name"] == "NVIDIA Corporation"
    assert payload["data"]["exchange"] == "NASDAQ"


@pytest.mark.asyncio
async def test_stocks_unknown_symbol_maps_to_404(monkeypatch):
    async def fake_get_quote(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        raise LookupError("No market data found for symbol 'ZZZZZZ'")

    monkeypatch.setattr(stocks_handler, "get_quote", fake_get_quote)

    with pytest.raises(HTTPException) as exc_info:
        await stocks_controller.get_quote(symbol="ZZZZZZ")

    assert exc_info.value.status_code == 404
    assert "No market data found" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_stocks_empty_symbol_maps_to_400(monkeypatch):
    async def fake_get_quote(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        raise ValueError("Symbol must be provided")

    monkeypatch.setattr(stocks_handler, "get_quote", fake_get_quote)

    with pytest.raises(HTTPException) as exc_info:
        await stocks_controller.get_quote(symbol=" ")

    assert exc_info.value.status_code == 400
    assert "Symbol must be provided" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_stocks_upstream_failure_maps_to_502(monkeypatch):
    async def fake_get_quote(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        raise RuntimeError("FMP request failed (500)")

    monkeypatch.setattr(stocks_handler, "get_quote", fake_get_quote)

    with pytest.raises(HTTPException) as exc_info:
        await stocks_controller.get_quote(symbol="AAPL")

    assert exc_info.value.status_code == 502
    assert "FMP request failed" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_stocks_repository_quote_normalizes_symbol_and_maps_fields(monkeypatch):
    repository = StocksRepository()
    captured_symbols: list[str] = []

    async def fake_request(path: str, *, params: dict[str, object]):
        captured_symbols.append(str(params["symbol"]))
        assert path == "/quote"
        return [
            {
                "price": 222.3,
                "change": 1.2,
                "changesPercentage": 0.54,
                "dayHigh": 223.0,
                "dayLow": 219.8,
                "volume": 123456,
                "marketCap": 1_000_000,
                "timestamp": 1_700_000_000,
            }
        ]

    monkeypatch.setattr(repository, "_request", fake_request)

    payload = await repository.get_quote(" aapl ")

    assert captured_symbols == ["AAPL"]
    assert payload["symbol"] == "AAPL"
    assert payload["cached"] is False
    assert payload["data"]["change_percent"] == 0.54
    assert payload["data"]["day_high"] == 223.0


@pytest.mark.asyncio
async def test_stocks_repository_quote_cache_hit_avoids_second_provider_call(monkeypatch):
    repository = StocksRepository()
    call_count = 0

    async def fake_request(path: str, *, params: dict[str, object]):
        nonlocal call_count
        call_count += 1
        return [{"price": 100, "change": 0, "changesPercentage": 0, "dayHigh": 100, "dayLow": 99}]

    monkeypatch.setattr(repository, "_request", fake_request)

    first = await repository.get_quote("AAPL")
    second = await repository.get_quote("AAPL")

    assert call_count == 1
    assert first["cached"] is False
    assert second["cached"] is True


@pytest.mark.asyncio
async def test_stocks_repository_force_refresh_bypasses_cache(monkeypatch):
    repository = StocksRepository()
    call_count = 0

    async def fake_request(path: str, *, params: dict[str, object]):
        nonlocal call_count
        call_count += 1
        return [{"price": 120}]

    monkeypatch.setattr(repository, "_request", fake_request)

    first = await repository.get_quote("AAPL")
    second = await repository.get_quote("AAPL", force_refresh=True)

    assert call_count == 2
    assert first["cached"] is False
    assert second["cached"] is False


@pytest.mark.asyncio
async def test_stocks_repository_cache_expiry_triggers_new_call(monkeypatch):
    repository = StocksRepository()
    call_count = 0

    async def fake_request(path: str, *, params: dict[str, object]):
        nonlocal call_count
        call_count += 1
        return [{"price": 130}]

    monkeypatch.setattr(repository, "_request", fake_request)

    await repository.get_quote("AAPL")
    for key, (_, value) in list(repository._cache.items()):
        repository._cache[key] = (time.time() - 1, value)

    payload = await repository.get_quote("AAPL")

    assert call_count == 2
    assert payload["cached"] is False


@pytest.mark.asyncio
async def test_stocks_repository_ratios_and_company_mapping(monkeypatch):
    repository = StocksRepository()

    async def fake_request(path: str, *, params: dict[str, object]):
        if path == "/ratios-ttm":
            return [
                {
                    "peRatioTTM": 20.1,
                    "pegRatioTTM": 1.5,
                    "priceToBookRatioTTM": 4.0,
                    "priceToSalesRatioTTM": 2.2,
                    "returnOnEquityTTM": 0.19,
                    "debtEquityRatioTTM": 0.8,
                }
            ]
        if path == "/profile":
            return [
                {
                    "companyName": "Apple Inc.",
                    "exchangeShortName": "NASDAQ",
                    "industry": "Consumer Electronics",
                    "sector": "Technology",
                    "website": "https://apple.com",
                    "ceo": "Tim Cook",
                    "country": "US",
                    "description": "Maker of iPhone",
                    "marketCap": 1000,
                    "beta": 1.1,
                }
            ]
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(repository, "_request", fake_request)

    ratios_payload = await repository.get_ratios("AAPL")
    company_payload = await repository.get_company("AAPL")

    assert ratios_payload["data"]["pe_ratio_ttm"] == 20.1
    assert company_payload["data"]["name"] == "Apple Inc."
    assert company_payload["data"]["exchange"] == "NASDAQ"
