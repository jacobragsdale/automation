from fastapi import APIRouter, HTTPException

from domains.stocks import handler

router = APIRouter(prefix="/stocks", tags=["Stocks"])


@router.get("/quote")
async def get_quote(symbol: str, force_refresh: bool = False) -> dict[str, object]:
    try:
        return await handler.get_quote(symbol=symbol, force_refresh=force_refresh)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/ratios")
async def get_ratios(symbol: str, force_refresh: bool = False) -> dict[str, object]:
    try:
        return await handler.get_ratios(symbol=symbol, force_refresh=force_refresh)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/company")
async def get_company(symbol: str, force_refresh: bool = False) -> dict[str, object]:
    try:
        return await handler.get_company(symbol=symbol, force_refresh=force_refresh)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
