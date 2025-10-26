import asyncio
import os

import httpx
from dotenv import load_dotenv

load_dotenv()


class NextDnsUtil:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        api_key = os.getenv("NEXTDNS_API_KEY")
        if not api_key:
            raise RuntimeError("NEXTDNS_API_KEY is not set")
        self._headers = {"X-Api-Key": api_key}
        self.profile_url = None
        self.profile_id = None
        self.profile = None
        self._profile_lock = None
        self._initialized = True

    async def _fetch_profile(self):
        async with httpx.AsyncClient(headers=self._headers, timeout=10) as client:
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

    async def ensure_profile_loaded(self, force_refresh: bool = False):
        if self._profile_lock is None:
            self._profile_lock = asyncio.Lock()
        async with self._profile_lock:
            if force_refresh or self.profile is None or self.profile_url is None:
                return await self._fetch_profile()
            return self.profile

    async def _toggle_lockdown(self, active: bool = True):
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
        async with httpx.AsyncClient(headers=self._headers, timeout=10) as client:
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

    async def toggle_lockdown(self, active: bool = True):
        await self._toggle_lockdown(active)

    async def _add_to_denylist(self, domain: str):
        if not domain:
            raise ValueError("Domain must be provided")
        await self.ensure_profile_loaded()
        async with httpx.AsyncClient(headers=self._headers, timeout=10) as client:
            response = await client.post(
                f"{self.profile_url}/denylist",
                json={"id": domain, "active": True},
            )
            response.raise_for_status()
        await self.ensure_profile_loaded(force_refresh=True)

    async def add_to_denylist(self, domain: str):
        await self._add_to_denylist(domain)


async def main():
    await NextDnsUtil().toggle_lockdown(active=False)


if __name__ == "__main__":
    util = NextDnsUtil()
    asyncio.run(main())
