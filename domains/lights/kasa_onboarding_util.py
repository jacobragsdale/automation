import asyncio
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from kasa import Discover
from kasa.exceptions import KasaException

load_dotenv()


def _run_cmd(cmd: list[str], *, check: bool = True, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check, timeout=timeout)


def _get_default_gateway() -> str | None:
    result = _run_cmd(["route", "-n", "get", "default"], check=False)
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    match = re.search(r"gateway:\s+(\S+)", text)
    if not match:
        return None
    return match.group(1)


async def _discover_softap_device(preferred_host: str | None = None) -> tuple[str | None, Any]:
    candidates: list[str] = []
    if preferred_host:
        candidates.append(preferred_host)

    gateway = await asyncio.to_thread(_get_default_gateway)
    if gateway:
        candidates.append(gateway)

    candidates.extend(["192.168.0.1", "192.168.1.1", "192.168.8.1", "192.168.68.1"])

    seen: set[str] = set()
    for host in candidates:
        if host in seen:
            continue
        seen.add(host)
        try:
            dev = await Discover.discover_single(host, discovery_timeout=4, timeout=8)
        except Exception:
            dev = None
        if dev is not None:
            return host, dev

    try:
        discovered = await Discover.discover(discovery_timeout=4, timeout=8)
    except Exception:
        discovered = {}
    if discovered:
        host, dev = next(iter(discovered.items()))
        return host, dev
    return None, None


async def connect_new_bulb(
    home_ssid: str,
    home_password: str,
    *,
    host: str | None = None,
    key_type: str = "3",
    scan_home: bool = False,
) -> dict[str, Any]:
    if not home_ssid:
        raise ValueError("home_ssid is required")
    if not home_password:
        raise ValueError("home_password is required")

    resolved_host, dev = await _discover_softap_device(host)
    if dev is None:
        return {
            "status": "failed",
            "error": "Unable to discover a Kasa device. Connect to a TP-LINK bulb AP first, then rerun.",
        }

    result: dict[str, Any] = {
        "status": "failed",
        "device_host": resolved_host,
        "home_ssid": home_ssid,
    }

    try:
        await dev.update()
    except Exception:
        pass

    for attr in ("alias", "model", "mac", "device_id"):
        try:
            result[attr] = getattr(dev, attr, None)
        except Exception:
            result[attr] = None

    if scan_home:
        try:
            networks = await dev.wifi_scan()
            result["visible_network_count"] = len(networks)
            result["home_ssid_visible"] = any(network.ssid == home_ssid for network in networks)
        except Exception as exc:
            result["wifi_scan_error"] = str(exc)

    try:
        join_response = await dev.wifi_join(home_ssid, home_password, keytype=key_type)
        result["join_response"] = join_response
        # python-kasa strips err_code internally and may return {} on success.
        result["status"] = "success"
    except KasaException as exc:
        result["error"] = f"KasaException: {exc}"
    except Exception as exc:
        result["error"] = str(exc)

    return result


async def _run_from_env() -> int:
    home_ssid = os.getenv("KASA_HOME_SSID")
    home_password = os.getenv("KASA_HOME_PASSWORD")
    if not home_ssid:
        raise SystemExit("Missing KASA_HOME_SSID in .env")
    if not home_password:
        raise SystemExit("Missing KASA_HOME_PASSWORD in .env")

    result = await connect_new_bulb(home_ssid=home_ssid, home_password=home_password)

    output_path = Path(__file__).resolve().parent / "manual_provision_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps(result, indent=2))
    print(f"Saved result to {output_path}")
    return 0 if result.get("status") == "success" else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run_from_env()))


if __name__ == "__main__":
    main()
