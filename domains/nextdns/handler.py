from typing import Any

from domains.nextdns.repository import NextDnsRepository

nextdns_repository = NextDnsRepository()


async def ensure_profile_loaded(force_refresh: bool = False) -> dict[str, Any]:
    return await nextdns_repository.ensure_profile_loaded(force_refresh=force_refresh)


async def toggle_lockdown(active: bool) -> None:
    await nextdns_repository.toggle_lockdown(active=active)


async def add_to_denylist(domain: str) -> None:
    normalized_domain = domain.strip()
    if not normalized_domain:
        raise ValueError("Domain must be provided")
    await nextdns_repository.add_to_denylist(domain=normalized_domain)


async def get_settings() -> dict[str, Any]:
    return await nextdns_repository.get_settings()


async def get_parental_controls() -> dict[str, Any]:
    return await nextdns_repository.get_parental_controls()


async def get_blocklist() -> list[dict[str, Any]]:
    return await nextdns_repository.get_blocklist()


async def update_parental_controls(updates: dict[str, Any]) -> dict[str, Any]:
    return await nextdns_repository.update_parental_controls(updates=updates)


async def toggle_parental_filter(entry_type: str, entry_id: str, active: bool) -> dict[str, Any]:
    return await nextdns_repository.toggle_parental_filter(entry_type=entry_type, entry_id=entry_id, active=active)


async def update_privacy(updates: dict[str, Any]) -> dict[str, Any]:
    return await nextdns_repository.update_privacy(updates=updates)


async def create_focus_session(
    duration_minutes: int,
    domains: list[str],
    category_ids: list[str],
    service_ids: list[str],
    safe_search: bool,
    youtube_restricted_mode: bool,
    block_bypass: bool,
    reason: str | None,
) -> dict[str, Any]:
    return await nextdns_repository.create_focus_session(
        duration_minutes=duration_minutes,
        domains=domains,
        category_ids=category_ids,
        service_ids=service_ids,
        safe_search=safe_search,
        youtube_restricted_mode=youtube_restricted_mode,
        block_bypass=block_bypass,
        reason=reason,
    )


async def get_filters_state() -> dict[str, Any]:
    return await nextdns_repository.get_filters_state()
