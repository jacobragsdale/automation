from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from handlers import run_night_lights_handler, run_morning_lights_handler, toggle_lockdown_handler
from util.kasa_util import KasaUtil
from util.next_dns_util import NextDnsUtil


@asynccontextmanager
async def lifespan(app: FastAPI):
    await KasaUtil().discover_devices()
    NextDnsUtil()
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
    yield

app = FastAPI(lifespan=lifespan)

# Configure CORS
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"message": "API Service is running!"}

@app.get("/morning_lights")
async def run_morning_lights():
    await run_morning_lights_handler()

@app.get("/night_lights")
async def run_night_lights():
    await run_night_lights_handler()

@app.get("/toggle_lockdown/{active}")
async def toggle_lockdown(active: bool):
    await toggle_lockdown_handler(active)

@app.post("/add_to_denylist")
async def add_to_denylist(domain: str):
    NextDnsUtil().add_to_denylist(domain)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

