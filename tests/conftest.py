import logging
import os

os.environ.setdefault("MONGODB_DB", "document_insights_test")
os.environ.setdefault("WORKER_MIN_PROCESSING_SECONDS", "0")
os.environ.setdefault("WORKER_MAX_PROCESSING_SECONDS", "0")
os.environ.setdefault("FAILURE_RATE", "0")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db import clients as db
from app.main import app


@pytest_asyncio.fixture
async def client():
    await db.connect()
    await db.get_documents().delete_many({})
    try:
        await db.get_redis().flushdb()
    except Exception:
        logging.getLogger("tests").warning(
            "could not flush redis before test", exc_info=True
        )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await db.disconnect()
