# Repository Guidelines

This repository orchestrates smart-light automations and DNS lockdown routines using FastAPI, APScheduler, and TP-Link Kasa utilities. The goal of this guide is to keep contributions predictable, testable, and aligned with the automation runtime already in production.

## Project Structure & Module Organization
- `app.py` hosts the FastAPI service, configures the scheduler lifespan, and exposes automation endpoints.
- `scheduler.py` runs a stand-alone AsyncIO scheduler when the API is not needed.
- `handlers.py` contains coroutine entry points that delegate to utilities.
- `util/` stores shared integrations (`kasa_util.py`, `next_dns_util.py`) and assets such as `devices.json`.
- Shell helpers (`deploy.sh`, `server_setup.sh`, `Dockerfile`) support deployment workflows; update them when changing runtime expectations.

## Build, Test, and Development Commands
- `uv sync` installs runtime dependencies from `pyproject.toml`.
- `uv run uvicorn app:app --reload` starts the API service with auto-reload for local development.
- `uv run scheduler.py` launches the headless scheduler loop; use `Ctrl+C` to stop.
- `docker build -t automation .` produces the container image defined by `Dockerfile`.

## Coding Style & Naming Conventions
- Use 4-space indentation, type hints for new functions, and snake_case for modules, functions, and async coroutines.
- Prefer explicit async workflows; keep blocking IO off the event loop (wrap in `asyncio.to_thread` if needed).
- Reuse `KasaUtil`/`NextDnsUtil` singletons; avoid new global state.
- Maintain descriptive log messages, and guard network calls with exception handling that mirrors existing patterns.

## Testing Guidelines
- Repository currently lacks automated tests; add `pytest` suites under `tests/` when contributing significant logic.
- Name test modules `test_<target>.py` and favor async test cases via `pytest.mark.asyncio`.
- Run `pytest` before requesting review; include fixtures for external services (mock Kasa and NextDNS).
- Capture new fixtures or seed data alongside tests to keep the happy path reproducible.

## Commit & Pull Request Guidelines
- Follow the existing concise, present-tense message style (`<scope> <action>`), e.g., `lights adjust evening hue`.
- Group related changes per commit; avoid bundling refactors with feature work.
- Pull requests should summarize behavior changes, list verification steps (commands run, logs reviewed), and link any tracking issues.
- Provide screenshots or log excerpts when touching observability or dashboard outputs.

## Environment & Security Notes
- Secrets such as `NEXTDNS_API_KEY` live in a local `.env`; never commit real credentials or generated `devices.json`.
- Document new environment variables in `README.md` and reference their use in scripts.
- When introducing additional services, update firewall and DNS considerations alongside configuration scripts.
