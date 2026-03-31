from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # pyright: ignore[reportMissingTypeStubs]
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from domains.lights import lights_handler
from domains.lights.lights_controller import router as lights_router
from domains.nextdns import nextdns_handler
from domains.nextdns.nextdns_controller import router as nextdns_router
from domains.system.system_controller import router as system_router
from schedules import register_schedules

OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "System", "description": "Service health and status endpoints."},
    {"name": "Lights", "description": "Kasa light control and device endpoints."},
    {"name": "NextDNS", "description": "NextDNS configuration and control endpoints."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    await lights_handler.initialize_lights()
    await nextdns_handler.ensure_profile_loaded()

    scheduler = AsyncIOScheduler()
    register_schedules(scheduler)

    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan, openapi_tags=OPENAPI_TAGS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router)
app.include_router(lights_router)
app.include_router(nextdns_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
