import asyncio
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.core.config import Settings
from app.db import clients as db
from app.workers import document_worker as worker


async def test_concurrent_workers_claim_each_job_once(client):
    """Two workers racing for one queued job: exactly one claims it."""
    r = await client.post(
        "/documents", json={"user_id": "race", "title": "t", "content": "only one"}
    )
    assert r.json()["status"] == "queued"

    # Two process_one calls race for the single queued document.
    results = await asyncio.gather(worker.process_one(), worker.process_one())

    # Exactly one claimed and processed the job; the other found nothing.
    assert sorted(results) == [False, True]


async def test_cache_hit_bypasses_rate_limit(client):
    """A cached resubmit returns immediately even when the user is at capacity."""
    content = "cache me if you can"

    # Compute and cache a summary for `content`.
    r1 = await client.post(
        "/documents", json={"user_id": "cap", "title": "first", "content": content}
    )
    assert r1.json()["status"] == "queued"
    assert await worker.process_one() is True  # completes + caches

    # Fill all three active slots with distinct new content.
    for i in range(3):
        r = await client.post(
            "/documents",
            json={"user_id": "cap", "title": f"f{i}", "content": f"filler {i}"},
        )
        assert r.status_code == 201
        assert r.json()["status"] == "queued"

    # A distinct 4th submission is rejected (at capacity)...
    over = await client.post(
        "/documents", json={"user_id": "cap", "title": "over", "content": "filler 4"}
    )
    assert over.status_code == 429

    # ...but resubmitting the cached content is served immediately, no 429.
    cached = await client.post(
        "/documents", json={"user_id": "cap", "title": "again", "content": content}
    )
    assert cached.status_code == 201
    assert cached.json()["status"] == "completed"


async def test_failed_job_is_requeued_with_backoff(client, monkeypatch):
    """A failed attempt with retries left is requeued (not failed) and holds its slot."""
    forced = Settings(
        mongodb_db="document_insights_test",
        failure_rate=1.0,
        max_attempts=3,
        worker_min_processing_seconds=0,
        worker_max_processing_seconds=0,
    )
    monkeypatch.setattr("app.workers.document_worker.get_settings", lambda: forced)

    r = await client.post(
        "/documents", json={"user_id": "retry", "title": "t", "content": "flaky"}
    )
    doc_id = r.json()["document_id"]

    # First attempt fails; attempts (1) < max (3) -> requeued with backoff.
    assert await worker.process_one() is True

    d = await client.get(f"/documents/{doc_id}")
    assert d.json()["status"] == "queued"  # requeued, not failed
    assert d.json()["summary"] is None

    # Backoff has not elapsed, so an immediate second poll finds no due job.
    assert await worker.process_one() is False

    # The slot is still held during retry (counter not decremented).
    assert await db.get_redis().get("ratelimit:retry") == "1"


async def test_stale_processing_job_is_reclaimed_and_slot_released(client):
    """A job left in 'processing' by a crashed worker is reclaimed by a healthy
    worker, completed, and its rate-limit slot released exactly once (no leak,
    no double-charge)."""
    r = await client.post(
        "/documents", json={"user_id": "stale", "title": "t", "content": "stuck job"}
    )
    doc_id = r.json()["document_id"]
    # Submitting acquired one rate-limit slot.
    assert await db.get_redis().get("ratelimit:stale") == "1"

    # Simulate a crashed worker: leave the doc 'processing' with a
    # processing_started_at older than STALE_TIMEOUT_SECONDS (default 120s).
    stale_ts = datetime.now(timezone.utc) - timedelta(seconds=10_000)
    await db.get_documents().update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": {"status": "processing", "processing_started_at": stale_ts,
                  "attempts": 1}},
    )

    # A healthy worker reclaims it via the claim query's stale branch and finishes.
    assert await worker.process_one() is True
    d = await client.get(f"/documents/{doc_id}")
    assert d.json()["status"] == "completed"

    # Released exactly once on recovery: counter back to 0 — not stuck at 1 (leak)
    # and not driven negative (double release).
    assert await db.get_redis().get("ratelimit:stale") == "0"
