from app.core.config import Settings
from app.workers import document_worker as worker


async def test_identical_content_returns_completed_immediately(client):
    content = "the quick brown fox jumps over the lazy dog"
    r1 = await client.post(
        "/documents", json={"user_id": "cu", "title": "first", "content": content}
    )
    assert r1.json()["status"] == "queued"

    # Drive the worker directly (processing time 0, failure_rate 0 from conftest env).
    assert await worker.process_one() is True

    first_id = r1.json()["document_id"]
    d = await client.get(f"/documents/{first_id}")
    assert d.json()["status"] == "completed"
    summary = d.json()["summary"]

    # Resubmit identical content -> immediate completed from cache, no new job.
    r2 = await client.post(
        "/documents", json={"user_id": "cu", "title": "second", "content": content}
    )
    assert r2.status_code == 201
    assert r2.json()["status"] == "completed"
    d2 = await client.get(f"/documents/{r2.json()['document_id']}")
    assert d2.json()["summary"] == summary


async def test_permanent_failure_marks_document_failed(client, monkeypatch):
    # Force every processing attempt to fail, with no retries left.
    forced = Settings(
        mongodb_db="document_insights_test",
        failure_rate=1.0,
        max_attempts=0,
        worker_min_processing_seconds=0,
        worker_max_processing_seconds=0,
    )
    monkeypatch.setattr("app.workers.document_worker.get_settings", lambda: forced)

    r = await client.post(
        "/documents", json={"user_id": "fu", "title": "t", "content": "will fail"}
    )
    doc_id = r.json()["document_id"]

    assert await worker.process_one() is True

    d = await client.get(f"/documents/{doc_id}")
    assert d.json()["status"] == "failed"
    assert d.json()["error"]


async def test_cross_user_identical_content_served_from_cache(client):
    """Two different users submitting identical content: the second is served
    from the shared (content-only) cache, owned by its submitter, un-rate-limited."""
    content = "content shared across two different users"

    # User A submits; the worker processes it -> completed and cached.
    a = await client.post(
        "/documents", json={"user_id": "alice", "title": "a", "content": content}
    )
    assert a.json()["status"] == "queued"
    assert await worker.process_one() is True
    a_detail = await client.get(f"/documents/{a.json()['document_id']}")
    assert a_detail.json()["status"] == "completed"
    summary = a_detail.json()["summary"]

    # User B submits the SAME content -> immediate completed from cache.
    b = await client.post(
        "/documents", json={"user_id": "bob", "title": "b", "content": content}
    )
    assert b.status_code == 201
    assert b.json()["status"] == "completed"

    b_detail = (await client.get(f"/documents/{b.json()['document_id']}")).json()
    # Cache is keyed by content only, so the summary is reused verbatim...
    assert b_detail["summary"] == summary
    # ...but the document belongs to the submitting user, not to user A.
    assert b_detail["user_id"] == "bob"

    # The cache hit did not consume Bob's rate-limit slot: he can still queue the
    # full RATE_LIMIT_MAX (3) of fresh documents.
    for i in range(3):
        r = await client.post(
            "/documents",
            json={"user_id": "bob", "title": f"n{i}", "content": f"bob unique {i}"},
        )
        assert r.status_code == 201
        assert r.json()["status"] == "queued"
