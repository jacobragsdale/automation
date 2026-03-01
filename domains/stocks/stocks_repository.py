import logging
import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv


class StocksRepository:
    _instance = None
    BASE_URL = "https://financialmodelingprep.com/stable"
    PROVIDER = "fmp"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._cache_ttl_seconds = 300
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._api_key: str | None = None
        self._initialized = True

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("Symbol must be provided")
        return normalized

    @staticmethod
    def _pick(payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in payload and payload[key] is not None:
                return payload[key]
        return None

    def _ensure_api_key(self) -> str:
        if self._api_key:
            return self._api_key

        load_dotenv()
        api_key = os.getenv("FMP_API_KEY")
        if not api_key:
            raise RuntimeError("FMP_API_KEY is not set")
        self._api_key = api_key
        return api_key

    async def _request(self, path: str, *, params: dict[str, Any]) -> Any:
        query_params = dict(params)
        query_params["apikey"] = self._ensure_api_key()
        url = f"{self.BASE_URL}{path}"

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=query_params)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"FMP request failed ({response.status_code}) on {path}: {response.text or 'Unknown error'}"
                )
            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError(f"FMP returned invalid JSON from {path}") from exc

    async def _fetch_first(self, path: str, symbol: str) -> dict[str, Any]:
        payload = await self._request(path, params={"symbol": symbol})

        entries: list[Any]
        if isinstance(payload, list):
            entries = payload
        elif isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                entries = data
            else:
                entries = [payload]
        else:
            raise RuntimeError(f"FMP returned unexpected payload shape for {path}")

        if not entries:
            raise LookupError(f"No market data found for symbol '{symbol}'")

        first = entries[0]
        if not isinstance(first, dict):
            raise RuntimeError(f"FMP returned non-object entry for {path}")
        return first

    def _cache_key(self, endpoint: str, symbol: str) -> str:
        return f"{endpoint}:{symbol}"

    def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        entry = self._cache.get(cache_key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            self._cache.pop(cache_key, None)
            return None
        return value

    def _set_cache(self, cache_key: str, value: dict[str, Any]) -> None:
        self._cache[cache_key] = (time.time() + self._cache_ttl_seconds, value)

    def _build_response(
        self,
        *,
        action: str,
        symbol: str,
        data: dict[str, Any],
        cached: bool,
    ) -> dict[str, Any]:
        return {
            "action": action,
            "status": "ok",
            "symbol": symbol,
            "provider": self.PROVIDER,
            "cached": cached,
            "data": data,
        }

    async def get_quote(self, symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        normalized_symbol = self._normalize_symbol(symbol)
        cache_key = self._cache_key("quote", normalized_symbol)
        logger = logging.getLogger(__name__)

        if not force_refresh:
            cached_quote = self._get_cached(cache_key)
            if cached_quote is not None:
                logger.info("stocks quote cache hit symbol=%s", normalized_symbol)
                return self._build_response(
                    action="stocks_quote",
                    symbol=normalized_symbol,
                    data=dict(cached_quote),
                    cached=True,
                )

        logger.info("stocks quote cache miss symbol=%s force_refresh=%s", normalized_symbol, force_refresh)
        quote = await self._fetch_first("/quote", normalized_symbol)
        mapped = {
            "price": self._pick(quote, "price"),
            "change": self._pick(quote, "change"),
            "change_percent": self._pick(quote, "changePercent", "changesPercentage"),
            "day_high": self._pick(quote, "dayHigh"),
            "day_low": self._pick(quote, "dayLow"),
            "volume": self._pick(quote, "volume"),
            "market_cap": self._pick(quote, "marketCap", "mktCap"),
            "timestamp": self._pick(quote, "timestamp"),
        }
        self._set_cache(cache_key, mapped)
        return self._build_response(action="stocks_quote", symbol=normalized_symbol, data=mapped, cached=False)

    async def get_ratios(self, symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        normalized_symbol = self._normalize_symbol(symbol)
        cache_key = self._cache_key("ratios", normalized_symbol)
        logger = logging.getLogger(__name__)

        if not force_refresh:
            cached_ratios = self._get_cached(cache_key)
            if cached_ratios is not None:
                logger.info("stocks ratios cache hit symbol=%s", normalized_symbol)
                return self._build_response(
                    action="stocks_ratios",
                    symbol=normalized_symbol,
                    data=dict(cached_ratios),
                    cached=True,
                )

        logger.info("stocks ratios cache miss symbol=%s force_refresh=%s", normalized_symbol, force_refresh)
        ratios = await self._fetch_first("/ratios-ttm", normalized_symbol)
        mapped = {
            "pe_ratio_ttm": self._pick(ratios, "peRatioTTM", "peRatio"),
            "peg_ratio_ttm": self._pick(ratios, "pegRatioTTM", "pegRatio"),
            "price_to_book_ttm": self._pick(ratios, "priceToBookRatioTTM", "priceToBookRatio"),
            "price_to_sales_ttm": self._pick(ratios, "priceToSalesRatioTTM", "priceToSalesRatio"),
            "roe_ttm": self._pick(ratios, "returnOnEquityTTM", "roeTTM", "roe"),
            "debt_to_equity_ttm": self._pick(
                ratios,
                "debtEquityRatioTTM",
                "debtToEquityTTM",
                "debtToEquity",
            ),
        }
        self._set_cache(cache_key, mapped)
        return self._build_response(action="stocks_ratios", symbol=normalized_symbol, data=mapped, cached=False)

    async def get_company(self, symbol: str, force_refresh: bool = False) -> dict[str, Any]:
        normalized_symbol = self._normalize_symbol(symbol)
        cache_key = self._cache_key("company", normalized_symbol)
        logger = logging.getLogger(__name__)

        if not force_refresh:
            cached_company = self._get_cached(cache_key)
            if cached_company is not None:
                logger.info("stocks company cache hit symbol=%s", normalized_symbol)
                return self._build_response(
                    action="stocks_company",
                    symbol=normalized_symbol,
                    data=dict(cached_company),
                    cached=True,
                )

        logger.info("stocks company cache miss symbol=%s force_refresh=%s", normalized_symbol, force_refresh)
        company = await self._fetch_first("/profile", normalized_symbol)
        mapped = {
            "name": self._pick(company, "companyName", "name"),
            "exchange": self._pick(company, "exchangeShortName", "exchange"),
            "industry": self._pick(company, "industry"),
            "sector": self._pick(company, "sector"),
            "website": self._pick(company, "website"),
            "ceo": self._pick(company, "ceo"),
            "country": self._pick(company, "country"),
            "description": self._pick(company, "description"),
            "market_cap": self._pick(company, "marketCap", "mktCap"),
            "beta": self._pick(company, "beta"),
        }
        self._set_cache(cache_key, mapped)
        return self._build_response(action="stocks_company", symbol=normalized_symbol, data=mapped, cached=False)
