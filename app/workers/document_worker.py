import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db import clients as db
from app.repositories import cache_repository as cache
from app.repositories import document_repository as repository

logger = logging.getLogger(__name__)


def build_summary(content: str, limit: int) -> str:
    word_count = len(content.split())
    excerpt = content[:limit]
    return f"Summary ({word_count} words): {excerpt}"


async def _handle_failure(job: dict, document_id: str, error: str) -> None:
    settings = get_settings()
    attempts = job["attempts"]
    if attempts < settings.max_attempts:
        backoff = 2 ** attempts
        next_attempt = datetime.now(timezone.utc) + timedelta(seconds=backoff)
        await repository.requeue(document_id, next_attempt)
        logger.warning(
            "job failed; retrying",
            extra={
                "extra_fields": {
                    "document_id": document_id,
                    "attempt": attempts,
                    "backoff_s": backoff,
                }
            },
        )
    else:
        await repository.mark_failed(document_id, error)
        await cache.release_rate_slot(job["user_id"])
        logger.error(
            "job failed permanently",
            extra={"extra_fields": {"document_id": document_id, "attempts": attempts}},
        )


async def process_one() -> bool:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    stale_before = now - timedelta(seconds=settings.stale_timeout_seconds)

    job = await repository.claim_next_job(now, stale_before)
    if job is None:
        return False

    document_id = str(job["_id"])
    content_hash = job["content_hash"]
    logger.info(
        "job claimed",
        extra={"extra_fields": {"document_id": document_id, "attempt": job["attempts"]}},
    )

    # Concurrent-duplicate short-circuit: another submission may have cached it.
    cached = await cache.get_cached_summary(content_hash)
    if cached is not None:
        await repository.mark_completed(document_id, cached)
        await cache.release_rate_slot(job["user_id"])
        logger.info(
            "job completed from cache",
            extra={"extra_fields": {"document_id": document_id}},
        )
        return True

    delay = random.uniform(
        settings.worker_min_processing_seconds, settings.worker_max_processing_seconds
    )
    await asyncio.sleep(delay)

    if random.random() < settings.failure_rate:
        await _handle_failure(job, document_id, "simulated processing failure")
        return True

    summary = build_summary(job["content"], settings.summary_char_limit)
    await repository.mark_completed(document_id, summary)
    await cache.set_cached_summary(content_hash, summary)
    await cache.release_rate_slot(job["user_id"])
    logger.info(
        "job completed", extra={"extra_fields": {"document_id": document_id}}
    )
    return True


async def run_worker() -> None:
    settings = get_settings()
    logger.info("worker started")
    while True:
        try:
            processed = await process_one()
            if not processed:
                await asyncio.sleep(settings.worker_poll_interval)
        except Exception:
            logger.exception("worker loop error")
            await asyncio.sleep(settings.worker_poll_interval)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    await db.connect()
    try:
        await run_worker()
    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
