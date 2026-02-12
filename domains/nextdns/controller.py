from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from domains.nextdns import handler

router = APIRouter(prefix="/nextdns", tags=["NextDNS"])


class LockdownToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


class DenylistAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1)


class ParentalControlsUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    safe_search: bool | None = Field(default=None, alias="safeSearch")
    youtube_restricted_mode: bool | None = Field(default=None, alias="youtubeRestrictedMode")
    block_bypass: bool | None = Field(default=None, alias="blockBypass")
    categories: dict[str, bool] | None = None
    services: dict[str, bool] | None = None

    def to_updates(self) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if self.safe_search is not None:
            updates["safeSearch"] = self.safe_search
        if self.youtube_restricted_mode is not None:
            updates["youtubeRestrictedMode"] = self.youtube_restricted_mode
        if self.block_bypass is not None:
            updates["blockBypass"] = self.block_bypass
        if self.categories:
            updates["categories"] = self.categories
        if self.services:
            updates["services"] = self.services
        return updates


class ParentFilterToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool


class PrivacyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updates: dict[str, Any]


class FocusSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    duration_minutes: int = Field(default=60, ge=5, le=1440)
    domains: list[str] = Field(default_factory=list)
    category_ids: list[str] = Field(default_factory=list, alias="categoryIds")
    service_ids: list[str] = Field(default_factory=list, alias="serviceIds")
    safe_search: bool = Field(default=True, alias="safeSearch")
    youtube_restricted_mode: bool = Field(default=True, alias="youtubeRestrictedMode")
    block_bypass: bool = Field(default=True, alias="blockBypass")
    reason: str | None = None


@router.post("/lockdown")
async def toggle_lockdown(payload: LockdownToggleRequest) -> dict[str, object]:
    try:
        await handler.toggle_lockdown(payload.active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "toggle_lockdown", "active": payload.active, "status": "ok"}


@router.post("/denylist")
async def add_to_denylist(payload: DenylistAddRequest) -> dict[str, object]:
    try:
        await handler.add_to_denylist(payload.domain)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "add_to_denylist", "domain": payload.domain, "status": "ok"}


@router.get("/settings")
async def get_settings() -> dict[str, object]:
    try:
        settings = await handler.get_settings()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "get_settings", "data": settings, "status": "ok"}


@router.get("/parental_controls")
async def get_parental_controls() -> dict[str, object]:
    try:
        parental_controls = await handler.get_parental_controls()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "get_parental_controls", "data": parental_controls, "status": "ok"}


@router.get("/blocklist")
async def get_blocklist() -> dict[str, object]:
    try:
        blocklist = await handler.get_blocklist()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "get_blocklist", "data": blocklist, "status": "ok"}


@router.patch("/filters/parental-controls")
async def update_parental_controls(payload: ParentalControlsUpdateRequest) -> dict[str, object]:
    try:
        parental_controls = await handler.update_parental_controls(payload.to_updates())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "update_parental_controls", "data": parental_controls, "status": "ok"}


@router.patch("/filters/parental-controls/{entry_type}/{entry_id}")
async def toggle_parental_filter(
    entry_type: Literal["category", "service"],
    entry_id: str,
    payload: ParentFilterToggleRequest,
) -> dict[str, object]:
    try:
        parental_controls = await handler.toggle_parental_filter(
            entry_type=entry_type,
            entry_id=entry_id,
            active=payload.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "action": "toggle_parental_filter",
        "entry_type": entry_type,
        "entry_id": entry_id,
        "active": payload.active,
        "data": parental_controls,
        "status": "ok",
    }


@router.patch("/filters/privacy")
async def update_privacy(payload: PrivacyUpdateRequest) -> dict[str, object]:
    try:
        privacy = await handler.update_privacy(payload.updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "update_privacy", "data": privacy, "status": "ok"}


@router.post("/focus-sessions")
async def create_focus_session(payload: FocusSessionRequest) -> dict[str, object]:
    try:
        session = await handler.create_focus_session(
            duration_minutes=payload.duration_minutes,
            domains=payload.domains,
            category_ids=payload.category_ids,
            service_ids=payload.service_ids,
            safe_search=payload.safe_search,
            youtube_restricted_mode=payload.youtube_restricted_mode,
            block_bypass=payload.block_bypass,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "create_focus_session", "data": session, "status": "ok"}


@router.get("/filters/state")
async def get_filters_state() -> dict[str, object]:
    try:
        state = await handler.get_filters_state()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"action": "get_filters_state", "data": state, "status": "ok"}
