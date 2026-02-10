from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from handlers import (
    run_night_lights_handler,
    run_morning_lights_handler,
    run_all_lights_off_handler,
    run_all_lights_on_handler,
    run_color_lights_handler,
    toggle_lockdown_handler,
)
from util.kasa_util import KasaUtil
from util.next_dns_util import NextDnsUtil


@asynccontextmanager
async def lifespan(app: FastAPI):
    await KasaUtil().discover_devices()
    next_dns_util = NextDnsUtil()
    await next_dns_util.ensure_profile_loaded()
    scheduler = AsyncIOScheduler()

    scheduler.add_job(run_morning_lights_handler, trigger="cron", day_of_week="mon-fri", hour=6, minute=30)
    scheduler.add_job(run_night_lights_handler, trigger="cron", hour=20, minute=0)

    # scheduler.add_job(toggle_lockdown_handler, trigger="cron", day_of_week="mon-fri", hour=6, minute=0, args=[False])
    # scheduler.add_job(toggle_lockdown_handler, trigger="cron", day_of_week="mon-fri", hour=8, minute=0, args=[True])
    # scheduler.add_job(toggle_lockdown_handler, trigger="cron", day_of_week="mon-fri", hour=11, minute=0, args=[False])
    # scheduler.add_job(toggle_lockdown_handler, trigger="cron", day_of_week="mon-fri", hour=13, minute=0, args=[True])
    # scheduler.add_job(toggle_lockdown_handler, trigger="cron", day_of_week="mon-fri", hour=16, minute=0, args=[False])
    # scheduler.add_job(toggle_lockdown_handler, trigger="cron", day_of_week="mon-thu", hour=21, args=[True])

    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "API Service is running!"}


@app.get("/morning_lights")
async def run_morning_lights():
    await run_morning_lights_handler()
    return {"action": "morning_lights", "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/night_lights")
async def run_night_lights():
    await run_night_lights_handler()
    return {"action": "night_lights", "status": "ok"}


@app.get("/lights_on")
async def run_all_lights_on():
    await run_all_lights_on_handler()
    return {"action": "lights_on", "status": "ok"}


@app.get("/lights_off")
async def run_all_lights_off():
    await run_all_lights_off_handler()
    return {"action": "lights_off", "status": "ok"}


@app.get("/lights_color")
async def run_color_lights(color: str):
    ok = await run_color_lights_handler(color)
    if not ok:
        raise HTTPException(status_code=400, detail="Unsupported color value.")
    return {"action": "lights_color", "color": color, "status": "ok"}


@app.get("/toggle_lockdown/{active}")
async def toggle_lockdown(active: bool):
    await toggle_lockdown_handler(active)
    return {"action": "toggle_lockdown", "active": active, "status": "ok"}


@app.post("/add_to_denylist")
async def add_to_denylist(domain: str):
    await NextDnsUtil().add_to_denylist(domain)
    return {"action": "add_to_denylist", "domain": domain, "status": "ok"}


@app.get("/nextdns/settings")
async def get_nextdns_settings():
    settings = await NextDnsUtil().get_settings()
    return {"action": "get_settings", "data": settings, "status": "ok"}


@app.get("/nextdns/parental_controls")
async def get_nextdns_parental_controls():
    parental_controls = await NextDnsUtil().get_parental_controls()
    return {"action": "get_parental_controls", "data": parental_controls, "status": "ok"}


@app.get("/nextdns/blocklist")
async def get_nextdns_blocklist():
    blocklist = await NextDnsUtil().get_blocklist()
    return {"action": "get_blocklist", "data": blocklist, "status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
