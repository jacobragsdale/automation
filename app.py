from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from handlers import run_night_lights_handler, run_morning_lights_handler, update_deny_list_handler
from util.kasa_util import KasaUtil
from util.next_dns_util import NextDnsUtil


@asynccontextmanager
async def lifespan(app: FastAPI):
    await KasaUtil().discover_devices()
    NextDnsUtil()
    scheduler = AsyncIOScheduler()

    scheduler.add_job(run_morning_lights_handler, trigger="cron", day_of_week="mon-fri", hour=6, minute=45)
    scheduler.add_job(run_night_lights_handler, trigger="cron", hour=20, minute=0)

    scheduler.add_job(update_deny_list_handler, trigger="cron", day_of_week="mon-fri", hour=1, minute=0, args=[True])
    scheduler.add_job(update_deny_list_handler, trigger="cron", day_of_week="mon-fri", hour=16, minute=0, args=[False])
    scheduler.add_job(update_deny_list_handler, trigger="cron", day_of_week="mon-fri", hour=21, args=[True])

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

@app.get("/update_deny_list/{active}")
async def update_deny_list(active: bool):
    await update_deny_list_handler(active)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

# nohup uv run app.py > uvicorn.log 2>&1 & disown
# kill 23247
