import asyncio

import httpx
import requests
import os
from dotenv import load_dotenv

load_dotenv()


class NextDnsUtil:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        self._api_key = os.getenv("NEXTDNS_API_KEY")
        self._headers = {"X-Api-Key": self._api_key}

        # 1) Fetch the profile
        resp = requests.get("https://api.nextdns.io/profiles", headers=self._headers)
        resp.raise_for_status()
        profile_id = resp.json()["data"][0]["id"]

        # 2) Get the denylist entries
        self.deny_url = f"https://api.nextdns.io/profiles/{profile_id}/denylist"
        resp = requests.get(self.deny_url, headers=self._headers)
        resp.raise_for_status()
        self.entries = resp.json()["data"]

    async def _update_deny_list_item(self, entry: dict, active: bool):
        patch_url = f"{self.deny_url}/{entry['id']}"
        async with httpx.AsyncClient() as client:
            r = await client.patch(patch_url, headers=self._headers, json={"active": active})
            r.raise_for_status()
        print(f"Enabled {entry['id']}")

    async def update_deny_list(self, active: bool):
        tasks = [self._update_deny_list_item(entry, active) for entry in self.entries]
        await asyncio.gather(*tasks)
