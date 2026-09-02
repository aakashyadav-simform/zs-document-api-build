import logging

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING
from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_mongo_client: AsyncIOMotorClient | None = None
_redis_client: Redis | None = None


async def connect() -> None:
    global _mongo_client, _redis_client
    settings = get_settings()
    _mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    await ensure_indexes()
    logger.info("connected", extra={"extra_fields": {"db": settings.mongodb_db}})


async def disconnect() -> None:
    global _mongo_client, _redis_client
    if _mongo_client is not None:
        _mongo_client.close()
    if _redis_client is not None:
        await _redis_client.aclose()
    _mongo_client = None
    _redis_client = None


def get_db():
    assert _mongo_client is not None, "call connect() before using the database"
    return _mongo_client[get_settings().mongodb_db]


def get_documents():
    return get_db()["documents"]


def get_redis() -> Redis:
    assert _redis_client is not None, "call connect() before using redis"
    return _redis_client


async def ensure_indexes() -> None:
    coll = get_documents()
    await coll.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    await coll.create_index([("user_id", ASCENDING), ("status", ASCENDING)])
    await coll.create_index([("content_hash", ASCENDING)])
    # Worker claim query: queued jobs due for (re)processing.
    await coll.create_index([("status", ASCENDING), ("next_attempt_at", ASCENDING)])
    # Worker claim query: stale-job reclaim branch.
    await coll.create_index(
        [("status", ASCENDING), ("processing_started_at", ASCENDING)]
    )
    logger.info("indexes ensured")


async def ping_mongo() -> bool:
    if _mongo_client is None:
        return False
    try:
        await _mongo_client.admin.command("ping")
        return True
    except Exception:
        logger.warning("mongo ping failed", exc_info=True)
        return False


async def ping_redis() -> bool:
    if _redis_client is None:
        return False
    try:
        return bool(await _redis_client.ping())
    except Exception:
        logger.warning("redis ping failed", exc_info=True)
        return False
