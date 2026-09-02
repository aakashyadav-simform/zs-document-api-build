from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import clients as db
from app.schemas.document import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health():
    mongo_ok = await db.ping_mongo()
    redis_ok = await db.ping_redis()
    healthy = mongo_ok and redis_ok
    body = HealthResponse(
        status="ok" if healthy else "degraded", mongo=mongo_ok, redis=redis_ok
    )
    if not healthy:
        return JSONResponse(status_code=503, content=body.model_dump())
    return body
