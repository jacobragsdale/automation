from fastapi import APIRouter

router = APIRouter(tags=["System"])


@router.get("/")
async def root() -> dict[str, str]:
    return {"message": "API Service is running!"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
