import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.routes import documents, health
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db import clients as db
from app.services.document_service import RateLimitExceeded

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(get_settings().log_level)
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Document Insights API", lifespan=lifespan)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded: too many active documents"},
    )


app.include_router(documents.router)
app.include_router(health.router)
