import pytest

from domains.nextdns.repository import NextDnsRepository


@pytest.mark.asyncio
async def test_add_to_denylist_sets_existing_entry_active(monkeypatch):
    repository = NextDnsRepository()
    request_calls: list[tuple[str, str, dict[str, object] | None]] = []

    async def fake_ensure_profile_loaded(force_refresh: bool = False) -> dict[str, object]:
        return {"data": {"denylist": [{"id": "example.com", "active": False}]}}

    async def fake_request(
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        request_calls.append((method, path, json))
        return {}

    monkeypatch.setattr(repository, "ensure_profile_loaded", fake_ensure_profile_loaded)
    monkeypatch.setattr(repository, "_request", fake_request)

    await repository._add_to_denylist(" Example.COM. ")

    assert request_calls == [("PATCH", "/denylist/example.com", {"active": True})]


@pytest.mark.asyncio
async def test_add_to_denylist_creates_new_active_entry(monkeypatch):
    repository = NextDnsRepository()
    request_calls: list[tuple[str, str, dict[str, object] | None]] = []

    async def fake_ensure_profile_loaded(force_refresh: bool = False) -> dict[str, object]:
        return {"data": {"denylist": []}}

    async def fake_request(
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        request_calls.append((method, path, json))
        return {}

    monkeypatch.setattr(repository, "ensure_profile_loaded", fake_ensure_profile_loaded)
    monkeypatch.setattr(repository, "_request", fake_request)

    await repository._add_to_denylist("newsite.com")

    assert request_calls == [("POST", "/denylist", {"id": "newsite.com", "active": True})]


@pytest.mark.asyncio
async def test_add_to_denylist_patches_when_post_conflicts(monkeypatch):
    repository = NextDnsRepository()
    request_calls: list[tuple[str, str, dict[str, object] | None]] = []

    async def fake_ensure_profile_loaded(force_refresh: bool = False) -> dict[str, object]:
        return {"data": {"denylist": []}}

    async def fake_request(
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        request_calls.append((method, path, json))
        if method == "POST":
            raise RuntimeError("NextDNS request failed (409) on /denylist: conflict")
        return {}

    monkeypatch.setattr(repository, "ensure_profile_loaded", fake_ensure_profile_loaded)
    monkeypatch.setattr(repository, "_request", fake_request)

    await repository._add_to_denylist("existing.com")

    assert request_calls == [
        ("POST", "/denylist", {"id": "existing.com", "active": True}),
        ("PATCH", "/denylist/existing.com", {"active": True}),
    ]


@pytest.mark.asyncio
async def test_add_to_denylist_raises_non_conflict_post_error(monkeypatch):
    repository = NextDnsRepository()

    async def fake_ensure_profile_loaded(force_refresh: bool = False) -> dict[str, object]:
        return {"data": {"denylist": []}}

    async def fake_request(
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        params: dict[str, object] | None = None,
    ) -> dict[str, object]:
        if method == "POST":
            raise RuntimeError("NextDNS request failed (400) on /denylist: bad request")
        return {}

    monkeypatch.setattr(repository, "ensure_profile_loaded", fake_ensure_profile_loaded)
    monkeypatch.setattr(repository, "_request", fake_request)

    with pytest.raises(RuntimeError, match=r"\(400\)"):
        await repository._add_to_denylist("bad domain")
