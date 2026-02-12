# Home Automation API

FastAPI service and scheduler for Kasa lighting routines and NextDNS controls.

## Project layout

- `app.py`: FastAPI app composition (routers + lifespan + scheduler bootstrap).
- `schedules.py`: centralized APScheduler registration; jobs call handlers only.
- `scheduler.py`: optional standalone scheduler process that uses `schedules.py`.
- `domains/system/controller.py`: system routes (`/`, `/health`).
- `domains/lights/`: layered lights modules (`controller.py`, `handler.py`, `repository.py`).
- `domains/lights/devices.json`: cached Kasa host targets for faster rediscovery.
- `domains/lights/devices_inventory.json`: latest discovered Kasa inventory snapshot.
- `domains/lights/kasa_onboarding_util.py`: utility function + runnable entrypoint for onboarding a reset bulb.
- `domains/weather/`: layered weather modules (`controller.py`, `handler.py`, `repository.py`).
- `domains/nextdns/`: layered NextDNS modules (`controller.py`, `handler.py`, `repository.py`).
- `deploy.sh`: rsync + remote restart deploy helper.
- `automation.service`: systemd unit for running the API.

## Environment variables

Set these in `.env`:

- `NEXTDNS_API_KEY`: required for NextDNS endpoints.
- `WIFI_SSID`: used by `domains/lights/kasa_onboarding_util.py`.
- `WIFI_PASSWORD`: used by `domains/lights/kasa_onboarding_util.py`.

## Development

Install dependencies:

```bash
uv sync
```

Run API locally:

```bash
uv run uvicorn app:app --reload
```

Run standalone scheduler:

```bash
uv run scheduler.py
```

## API endpoints

### Health / status

- `GET /` - API liveness message.
- `GET /health` - health status.

### Weather

- `GET /weather` - current weather + today's high/low (defaults to `Nashville, TN`).
- `GET /weather?location=Austin,TX` - weather for a custom location.
- `GET /weather?location=London&units=metric` - weather in metric units.

Weather notes:
- Default units are imperial (`F`, `mph`); set `units=metric` for `C`, `km/h`.
- If a requested location cannot be resolved, the endpoint falls back to `Nashville, TN`.
- Response includes structured weather fields and a plain-English `summary`.

### Light controls

- `POST /lights/scenes/morning` - run morning scene.
- `POST /lights/scenes/night` - run night scene (only if lights are already on).
- `POST /lights/power/on` - turn all discovered lights on.
- `POST /lights/power/off` - turn all discovered lights off.
- `POST /lights/color` - set lights to a supported color.
  - Body example: `{"color":"red"}`
- `GET /lights/devices?force_refresh=<bool>` - return discovered Kasa inventory.

Supported colors:
`red`, `orange`, `yellow`, `green`, `blue`, `indigo`, `violet`, `white`, `candle light`

### NextDNS controls

- `POST /nextdns/lockdown` - enable/disable lockdown behavior.
  - Body example: `{"active": true}`
- `POST /nextdns/denylist` - add denylist entry.
  - Body example: `{"domain":"example.com"}`
- `GET /nextdns/settings` - profile settings summary.
- `GET /nextdns/parental_controls` - parental controls payload.
- `GET /nextdns/blocklist` - denylist payload.
- `PATCH /nextdns/filters/parental-controls` - update parental-control flags and batch category/service states.
  - Body example: `{"safeSearch": true, "youtubeRestrictedMode": true, "blockBypass": true, "categories": {"porn": true}, "services": {"tiktok": true}}`
- `PATCH /nextdns/filters/parental-controls/{entry_type}/{entry_id}` - toggle one category/service (`entry_type` is `category` or `service`).
  - Body example: `{"active": true}`
- `PATCH /nextdns/filters/privacy` - patch privacy settings as a raw key/value object.
  - Body example: `{"updates": {"blockDisguisedTrackers": true}}`
- `POST /nextdns/focus-sessions` - start a temporary self-control session and auto-rollback at expiry.
  - Body example: `{"duration_minutes": 90, "domains": ["youtube.com"], "categoryIds": ["social-networks"], "serviceIds": ["reddit"], "safeSearch": true, "youtubeRestrictedMode": true, "blockBypass": true, "reason": "deep work"}`
- `GET /nextdns/filters/state` - consolidated view of parental controls, privacy, deny/allow lists, and active focus sessions.

## New bulb onboarding

This project keeps a single onboarding utility path:

```bash
uv run python domains/lights/kasa_onboarding_util.py
```

The command expects you are connected to the bulb's reset TP-LINK/Kasa soft AP.

## Deploy

Run:

```bash
./deploy.sh
```

Preview actions without making remote changes:

```bash
./deploy.sh --dry-run
```

`--dry-run` validates local planning and prints remote scripts/commands, but does not run remote restart or health checks.

Deploy behavior:

- Uses `systemd` first (`automation.service` by default). If the system service is missing, deploy attempts to auto-install and enable it before falling back to `nohup` + `app.pid`.
- Runs `uv sync --frozen` only when `pyproject.toml` / `uv.lock` fingerprint changes (or when forced).
- Fallback mode waits for port release before restart and starts `.venv/bin/uvicorn` directly when available.
- Fallback mode also verifies the app survives SSH disconnect before reporting success.
- Fails fast on sync/restart/health failures and prints remote diagnostics when health checks fail.

Optional deploy env overrides:

- `SERVICE_NAME` (default: `automation.service`)
- `SERVICE_RUN_AS_USER` (default: value of `SERVER_USER`)
- `AUTO_INSTALL_SYSTEMD_SERVICE=1` (default; auto-install missing system service when possible)
- `ALLOW_SYSTEMD_USER=1` (opt in to `systemctl --user`; default is disabled for stability)
- `FORCE_DEPS_SYNC=1` (always run dependency sync)
- `DEPLOY_RSYNC_COMPRESS=1` (enable `rsync -z`)
- `HEALTH_RETRIES`, `HEALTH_INTERVAL`, `HEALTH_TIMEOUT`
- `SERVER_HOST`, `SERVER_USER`, `REMOTE_PROJECT_DIR`, `APP_PORT`, `APP_MODULE`
