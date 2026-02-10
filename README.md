# Home Automation API

FastAPI service and scheduler for Kasa lighting routines and NextDNS controls.

## Project layout

- `app.py`: FastAPI app, scheduler startup, and all API routes.
- `handlers.py`: route handlers for light scenes and lockdown toggles.
- `scheduler.py`: optional standalone scheduler process.
- `util/kasa_util.py`: shared Kasa device discovery + light command execution.
- `util/next_dns_util.py`: shared NextDNS profile operations.
- `util/kasa_onboarding_util.py`: utility function + runnable entrypoint for onboarding a reset bulb.
- `deploy.sh`: rsync + remote restart deploy helper.
- `automation.service`: systemd unit for running the API.

## Environment variables

Set these in `.env`:

- `NEXTDNS_API_KEY`: required for NextDNS endpoints.
- `WIFI_SSID`: used by `util/kasa_onboarding_util.py`.
- `WIFI_PASSWORD`: used by `util/kasa_onboarding_util.py`.

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

### Light controls

- `GET /morning_lights` - run morning scene.
- `GET /night_lights` - run night scene (only if lights are already on).
- `GET /lights_on` - turn all discovered lights on.
- `GET /lights_off` - turn all discovered lights off.
- `GET /lights_color?color=<value>` - set lights to a supported color.
- `GET /kasa/devices?force_refresh=<bool>` - return discovered Kasa inventory.

Supported colors:
`red`, `orange`, `yellow`, `green`, `blue`, `indigo`, `violet`, `white`, `candle light`

### NextDNS controls

- `GET /toggle_lockdown/{active}` - enable/disable lockdown behavior.
- `POST /add_to_denylist?domain=<domain>` - add denylist entry.
- `GET /nextdns/settings` - profile settings summary.
- `GET /nextdns/parental_controls` - parental controls payload.
- `GET /nextdns/blocklist` - denylist payload.

## New bulb onboarding

This project keeps a single onboarding utility path:

```bash
uv run python util/kasa_onboarding_util.py
```

The command expects you are connected to the bulb's reset TP-LINK/Kasa soft AP.

## Deploy

Run:

```bash
./deploy.sh
```

The script syncs files, runs `uv sync`, restarts `uvicorn`, and checks `/health`.
