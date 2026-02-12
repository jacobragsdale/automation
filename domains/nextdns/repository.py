import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

import httpx
from dotenv import load_dotenv


class NextDnsRepository:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._headers: dict[str, str] | None = None
        self.profile_url: str | None = None
        self.profile_id: str | None = None
        self.profile: dict[str, Any] | None = None
        self._profile_lock: asyncio.Lock | None = None
        self._focus_lock: asyncio.Lock | None = None
        self._focus_sessions: dict[str, dict[str, Any]] = {}
        self._focus_tasks: dict[str, asyncio.Task] = {}
        self._initialized = True

    def _ensure_headers(self) -> dict[str, str]:
        if self._headers is not None:
            return self._headers

        load_dotenv()
        api_key = os.getenv("NEXTDNS_API_KEY")
        if not api_key:
            raise RuntimeError("NEXTDNS_API_KEY is not set")

        self._headers = {"X-Api-Key": api_key}
        return self._headers

    async def _fetch_profile(self) -> dict[str, Any]:
        headers = self._ensure_headers()
        async with httpx.AsyncClient(headers=headers, timeout=10) as client:
            profiles_response = await client.get("https://api.nextdns.io/profiles")
            profiles_response.raise_for_status()
            profiles = profiles_response.json()
            profile_data = profiles.get("data") or []
            if not profile_data:
                raise RuntimeError("No NextDNS profiles returned")

            self.profile_id = profile_data[0]["id"]
            self.profile_url = f"https://api.nextdns.io/profiles/{self.profile_id}"

            profile_response = await client.get(self.profile_url)
            profile_response.raise_for_status()
            self.profile = profile_response.json()
            return self.profile

    async def ensure_profile_loaded(self, force_refresh: bool = False) -> dict[str, Any]:
        if self._profile_lock is None:
            self._profile_lock = asyncio.Lock()

        async with self._profile_lock:
            if force_refresh or self.profile is None or self.profile_url is None:
                return await self._fetch_profile()
            return self.profile

    async def _get_focus_lock(self) -> asyncio.Lock:
        if self._focus_lock is None:
            self._focus_lock = asyncio.Lock()
        return self._focus_lock

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        return domain.strip().lower().rstrip(".")

    @staticmethod
    def _error_payload_text(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "Unknown error"
        errors = payload.get("errors")
        if errors:
            return str(errors)
        return str(payload)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.ensure_profile_loaded()
        headers = self._ensure_headers()
        if not self.profile_url:
            raise RuntimeError("NextDNS profile URL is unavailable")

        async with httpx.AsyncClient(headers=headers, timeout=10) as client:
            response = await client.request(
                method=method,
                url=f"{self.profile_url}{path}",
                json=json,
                params=params,
            )
            if response.status_code >= 400:
                detail = self._error_payload_text(response)
                raise RuntimeError(f"NextDNS request failed ({response.status_code}) on {path}: {detail}")
            if response.text:
                try:
                    return response.json()
                except ValueError:
                    return {"raw": response.text}
            return {}

    async def _toggle_lockdown(self, active: bool = True) -> None:
        profile = await self.ensure_profile_loaded(force_refresh=True)
        data = profile.get("data", {})

        parental_control = data.get("parentalControl", {})
        categories = parental_control.get("categories", [])
        parental_control_payload = {
            "safeSearch": active,
            "categories": [
                {"id": entry["id"], "active": active}
                for entry in categories
                if "id" in entry
            ],
        }

        headers = self._ensure_headers()
        if not self.profile_url:
            raise RuntimeError("NextDNS profile URL is unavailable")

        async with httpx.AsyncClient(headers=headers, timeout=10) as client:
            parental_control_response = await client.patch(
                f"{self.profile_url}/parentalControl",
                json=parental_control_payload,
            )
            parental_control_response.raise_for_status()

            deny_list = data.get("denylist", [])
            for entry in deny_list:
                rule_id = entry.get("id")
                if not rule_id:
                    continue
                response = await client.patch(
                    f"{self.profile_url}/denylist/{rule_id}",
                    json={"active": active},
                )
                response.raise_for_status()

        await self.ensure_profile_loaded(force_refresh=True)

    async def toggle_lockdown(self, active: bool = True) -> None:
        await self._toggle_lockdown(active)

    async def _add_to_denylist(self, domain: str) -> None:
        if not domain:
            raise ValueError("Domain must be provided")

        await self.ensure_profile_loaded()
        headers = self._ensure_headers()
        if not self.profile_url:
            raise RuntimeError("NextDNS profile URL is unavailable")

        async with httpx.AsyncClient(headers=headers, timeout=10) as client:
            response = await client.post(
                f"{self.profile_url}/denylist",
                json={"id": domain, "active": True},
            )
            response.raise_for_status()

        await self.ensure_profile_loaded(force_refresh=True)

    async def add_to_denylist(self, domain: str) -> None:
        await self._add_to_denylist(domain)

    async def update_parental_controls(self, updates: dict[str, Any]) -> dict[str, Any]:
        profile = await self.ensure_profile_loaded(force_refresh=True)
        parental_control = profile.get("data", {}).get("parentalControl", {})

        payload: dict[str, Any] = {}
        scalar_fields = {
            "safeSearch": "safeSearch",
            "youtubeRestrictedMode": "youtubeRestrictedMode",
            "blockBypass": "blockBypass",
        }
        for source_key, target_key in scalar_fields.items():
            if source_key in updates and updates[source_key] is not None:
                payload[target_key] = bool(updates[source_key])

        for group in ("categories", "services"):
            group_updates = updates.get(group)
            if not group_updates:
                continue
            existing_entries = parental_control.get(group, [])
            existing_ids = {entry.get("id") for entry in existing_entries if entry.get("id")}
            unknown_ids = [entry_id for entry_id in group_updates if entry_id not in existing_ids]
            if unknown_ids:
                raise ValueError(f"Unknown {group} ids: {', '.join(sorted(unknown_ids))}")
            payload[group] = [
                {"id": entry_id, "active": bool(group_updates[entry_id])}
                for entry_id in group_updates
            ]

        if not payload:
            raise ValueError("No parental control updates provided")

        await self._request("PATCH", "/parentalControl", json=payload)
        refreshed_profile = await self.ensure_profile_loaded(force_refresh=True)
        return refreshed_profile.get("data", {}).get("parentalControl", {})

    async def toggle_parental_filter(self, entry_type: str, entry_id: str, active: bool) -> dict[str, Any]:
        normalized_type = entry_type.strip().lower()
        mapping = {"category": "categories", "service": "services"}
        if normalized_type not in mapping:
            raise ValueError("entry_type must be 'category' or 'service'")
        return await self.update_parental_controls({mapping[normalized_type]: {entry_id: active}})

    async def update_privacy(self, updates: dict[str, Any]) -> dict[str, Any]:
        if not updates:
            raise ValueError("No privacy updates provided")
        await self._request("PATCH", "/privacy", json=updates)
        refreshed_profile = await self.ensure_profile_loaded(force_refresh=True)
        return refreshed_profile.get("data", {}).get("privacy", {})

    async def get_filters_state(self) -> dict[str, Any]:
        profile = await self.ensure_profile_loaded(force_refresh=True)
        data = profile.get("data", {})
        now = datetime.now(timezone.utc)
        active_sessions = []

        lock = await self._get_focus_lock()
        async with lock:
            for session in self._focus_sessions.values():
                if session.get("status") != "active":
                    continue
                expires_at = session["expires_at"]
                remaining_seconds = max(0, int((expires_at - now).total_seconds()))
                active_sessions.append(
                    {
                        "session_id": session["id"],
                        "expires_at": expires_at.isoformat(),
                        "duration_minutes": session["duration_minutes"],
                        "remaining_seconds": remaining_seconds,
                        "targets": session["targets"],
                    }
                )

        return {
            "profile": {"id": self.profile_id, "name": data.get("name")},
            "parentalControl": data.get("parentalControl", {}),
            "privacy": data.get("privacy", {}),
            "denylist": data.get("denylist", []),
            "allowlist": data.get("allowlist", []),
            "focusSessions": sorted(active_sessions, key=lambda item: item["expires_at"]),
        }

    async def create_focus_session(
        self,
        *,
        duration_minutes: int,
        domains: list[str] | None = None,
        category_ids: list[str] | None = None,
        service_ids: list[str] | None = None,
        safe_search: bool = True,
        youtube_restricted_mode: bool = True,
        block_bypass: bool = True,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if duration_minutes < 5 or duration_minutes > 1440:
            raise ValueError("duration_minutes must be between 5 and 1440")

        normalized_domains = []
        for domain in domains or []:
            normalized = self._normalize_domain(domain)
            if normalized:
                normalized_domains.append(normalized)
        normalized_domains = sorted(set(normalized_domains))

        profile = await self.ensure_profile_loaded(force_refresh=True)
        data = profile.get("data", {})
        parental_control = data.get("parentalControl", {})
        current_categories = {
            entry.get("id"): bool(entry.get("active", False))
            for entry in parental_control.get("categories", [])
            if entry.get("id")
        }
        current_services = {
            entry.get("id"): bool(entry.get("active", False))
            for entry in parental_control.get("services", [])
            if entry.get("id")
        }

        requested_categories = sorted(set(category_ids or []))
        requested_services = sorted(set(service_ids or []))
        unknown_categories = [entry_id for entry_id in requested_categories if entry_id not in current_categories]
        unknown_services = [entry_id for entry_id in requested_services if entry_id not in current_services]
        if unknown_categories:
            raise ValueError(f"Unknown categories: {', '.join(unknown_categories)}")
        if unknown_services:
            raise ValueError(f"Unknown services: {', '.join(unknown_services)}")

        parental_payload: dict[str, Any] = {
            "safeSearch": safe_search,
            "youtubeRestrictedMode": youtube_restricted_mode,
            "blockBypass": block_bypass,
        }
        if requested_categories:
            parental_payload["categories"] = [{"id": entry_id, "active": True} for entry_id in requested_categories]
        if requested_services:
            parental_payload["services"] = [{"id": entry_id, "active": True} for entry_id in requested_services]

        rollback: dict[str, Any] = {
            "parentalControl": {
                "safeSearch": bool(parental_control.get("safeSearch", False)),
                "youtubeRestrictedMode": bool(parental_control.get("youtubeRestrictedMode", False)),
                "blockBypass": bool(parental_control.get("blockBypass", False)),
            },
            "categories": {entry_id: current_categories[entry_id] for entry_id in requested_categories},
            "services": {entry_id: current_services[entry_id] for entry_id in requested_services},
            "denylist": [],
        }

        try:
            if parental_payload:
                await self._request("PATCH", "/parentalControl", json=parental_payload)

            refreshed_profile = await self.ensure_profile_loaded(force_refresh=True)
            deny_entries = refreshed_profile.get("data", {}).get("denylist", [])
            current_denylist = {
                self._normalize_domain(entry.get("id", "")): entry
                for entry in deny_entries
                if entry.get("id")
            }

            for domain in normalized_domains:
                existing_entry = current_denylist.get(domain)
                if existing_entry:
                    was_active = bool(existing_entry.get("active", False))
                    rollback["denylist"].append({"domain": domain, "existed": True, "active": was_active})
                    if not was_active:
                        await self._request("PATCH", f"/denylist/{quote_plus(domain)}", json={"active": True})
                else:
                    rollback["denylist"].append({"domain": domain, "existed": False, "active": False})
                    await self._request("POST", "/denylist", json={"id": domain, "active": True})
        except Exception as exc:
            try:
                await self._apply_rollback(rollback)
            except Exception:
                pass
            raise RuntimeError(f"Failed to create focus session: {exc}") from exc

        now = datetime.now(timezone.utc)
        session_id = uuid4().hex
        expires_at = now + timedelta(minutes=duration_minutes)
        session = {
            "id": session_id,
            "status": "active",
            "created_at": now,
            "expires_at": expires_at,
            "duration_minutes": duration_minutes,
            "reason": reason,
            "targets": {
                "domains": normalized_domains,
                "category_ids": requested_categories,
                "service_ids": requested_services,
                "safeSearch": safe_search,
                "youtubeRestrictedMode": youtube_restricted_mode,
                "blockBypass": block_bypass,
            },
            "rollback": rollback,
        }

        lock = await self._get_focus_lock()
        async with lock:
            self._focus_sessions[session_id] = session
            self._focus_tasks[session_id] = asyncio.create_task(self._expire_focus_session(session_id))

        return {
            "session_id": session_id,
            "status": "active",
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "duration_minutes": duration_minutes,
            "targets": session["targets"],
        }

    async def _expire_focus_session(self, session_id: str) -> None:
        lock = await self._get_focus_lock()
        async with lock:
            session = self._focus_sessions.get(session_id)
            if not session:
                return
            expires_at = session.get("expires_at")

        if not expires_at:
            return

        delay = max(0, (expires_at - datetime.now(timezone.utc)).total_seconds())
        if delay > 0:
            await asyncio.sleep(delay)

        await self._rollback_focus_session(session_id)

    async def _rollback_focus_session(self, session_id: str) -> None:
        lock = await self._get_focus_lock()
        async with lock:
            session = self._focus_sessions.get(session_id)
            if not session or session.get("status") != "active":
                return
            session["status"] = "rolling_back"

        try:
            await self._apply_rollback(session["rollback"])
        except Exception as exc:
            async with lock:
                if session_id in self._focus_sessions:
                    self._focus_sessions[session_id]["status"] = "rollback_failed"
                    self._focus_sessions[session_id]["error"] = str(exc)
                self._focus_tasks.pop(session_id, None)
            return

        async with lock:
            self._focus_sessions.pop(session_id, None)
            self._focus_tasks.pop(session_id, None)

        await self.ensure_profile_loaded(force_refresh=True)

    async def _apply_rollback(self, rollback: dict[str, Any]) -> None:
        parental_payload: dict[str, Any] = {}
        parent_rollbacks = rollback.get("parentalControl", {})
        if parent_rollbacks:
            parental_payload.update(parent_rollbacks)

        categories_rollbacks = rollback.get("categories", {})
        if categories_rollbacks:
            parental_payload["categories"] = [
                {"id": entry_id, "active": active}
                for entry_id, active in categories_rollbacks.items()
            ]

        services_rollbacks = rollback.get("services", {})
        if services_rollbacks:
            parental_payload["services"] = [
                {"id": entry_id, "active": active}
                for entry_id, active in services_rollbacks.items()
            ]

        if parental_payload:
            await self._request("PATCH", "/parentalControl", json=parental_payload)

        for deny_item in rollback.get("denylist", []):
            domain = deny_item["domain"]
            if deny_item.get("existed"):
                await self._request(
                    "PATCH",
                    f"/denylist/{quote_plus(domain)}",
                    json={"active": bool(deny_item.get("active", False))},
                )
            else:
                await self._request("DELETE", f"/denylist/{quote_plus(domain)}")

    async def get_settings(self) -> dict[str, Any]:
        profile = await self.ensure_profile_loaded()
        data = profile.get("data", {})
        return {
            "name": data.get("name"),
            "security": data.get("security", {}),
            "privacy": data.get("privacy", {}),
            "performance": data.get("performance", {}),
            "settings": data.get("settings", {}),
        }

    async def get_parental_controls(self) -> dict[str, Any]:
        profile = await self.ensure_profile_loaded()
        data = profile.get("data", {})
        return data.get("parentalControl", {})

    async def get_blocklist(self) -> list[dict[str, Any]]:
        profile = await self.ensure_profile_loaded()
        data = profile.get("data", {})
        blocklist = data.get("denylist", [])
        if isinstance(blocklist, list):
            return blocklist
        return []
