from typing import Any

from domains.stocks.repository import StocksRepository

stocks_repository = StocksRepository()


async def get_quote(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
    return await stocks_repository.get_quote(symbol=symbol, force_refresh=force_refresh)


async def get_ratios(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
    return await stocks_repository.get_ratios(symbol=symbol, force_refresh=force_refresh)


async def get_company(symbol: str, force_refresh: bool = False) -> dict[str, Any]:
    return await stocks_repository.get_company(symbol=symbol, force_refresh=force_refresh)
