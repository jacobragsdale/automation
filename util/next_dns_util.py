import asyncio
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
        self._headers = {"X-Api-Key": os.getenv("NEXTDNS_API_KEY")}
        self.profile_url = None
        self.profile_id = None
        self.profile = None
        self.get_profile()

    def get_profile(self):
        response = requests.get("https://api.nextdns.io/profiles", headers=self._headers).json()
        self.profile_id = response["data"][0]["id"]
        self.profile_url = f"https://api.nextdns.io/profiles/{self.profile_id}"
        self.profile = requests.get(self.profile_url, headers=self._headers).json()
        return self.profile

    async def toggle_lockdown(self, active=True):
        # Toggle parental controls
        parental_control_payload = {
            "safeSearch": active,
            "categories": [
                {"id": entry["id"], "active": active}
                for entry in self.profile['data']['parentalControl']['categories']
            ]
        }
        response = requests.patch(f"{self.profile_url}/parentalControl", headers=self._headers, json=parental_control_payload)
        response.raise_for_status()

        # toggle denylist
        deny_list = self.profile['data']['denylist']
        for entry in deny_list:
            rule_payload = {"active": active}
            rule_id = entry['id']
            response = requests.patch(f"{self.profile_url}/denylist/{rule_id}", headers=self._headers, json=rule_payload)
            response.raise_for_status()

    def add_to_denylist(self, domain: str):
        request = {"id": domain, "active": True}
        response = requests.post(f"{self.profile_url}/denylist", headers=self._headers, json=request)
        response.raise_for_status()


async def main():
    await NextDnsUtil().toggle_lockdown(active=False)

if __name__ == "__main__":
    util = NextDnsUtil()
    asyncio.run(main())
