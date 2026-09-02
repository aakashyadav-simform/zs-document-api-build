import logging
from typing import cast

from app.core.config import get_settings
from app.db import clients as db
from app.repositories import document_repository as repository

logger = logging.getLogger(__name__)

_CONTENT_KEY = "cache:summary:{}"
_RATE_KEY = "ratelimit:{}"


async def get_cached_summary(content_hash: str) -> str | None:
    try:
        # decode_responses=True means the client returns str, not bytes.
        value = await db.get_redis().get(_CONTENT_KEY.format(content_hash))
        return cast("str | None", value)
    except Exception:
        logger.warning("cache read failed; treating as miss", exc_info=True)
        return None


async def set_cached_summary(content_hash: str, summary: str) -> None:
    try:
        await db.get_redis().set(
            _CONTENT_KEY.format(content_hash),
            summary,
            ex=get_settings().cache_ttl_seconds,
        )
    except Exception:
        logger.warning("cache write failed; skipping", exc_info=True)


async def try_acquire_rate_slot(user_id: str) -> bool:
    settings = get_settings()
    key = _RATE_KEY.format(user_id)
    try:
        redis = db.get_redis()
        current = await redis.incr(key)
        # Refresh the TTL on every acquire so an actively-submitting user's
        # counter never expires mid-lifetime (which would let them exceed
        # the limit). The TTL is a safety net against leaked counters, not a
        # rate window.
        await redis.expire(key, settings.rate_limit_ttl_seconds)
        if current > settings.rate_limit_max:
            await redis.decr(key)
            return False
        return True
    except Exception:
        logger.warning(
            "rate-limit via redis failed; falling back to mongo count", exc_info=True
        )
        active = await repository.count_active(user_id)
        return active < settings.rate_limit_max


async def release_rate_slot(user_id: str) -> None:
    key = _RATE_KEY.format(user_id)
    try:
        current = await db.get_redis().decr(key)
        if current < 0:
            # Guard against underflow; keep the safety TTL on the key.
            await db.get_redis().set(
                key, 0, ex=get_settings().rate_limit_ttl_seconds
            )
    except Exception:
        logger.warning("rate-limit release failed", exc_info=True)
