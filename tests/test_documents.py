async def test_submit_returns_201_queued(client):
    r = await client.post(
        "/documents", json={"user_id": "u1", "title": "t", "content": "hello world"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "queued"
    assert body["document_id"]


async def test_poll_returns_status(client):
    r = await client.post(
        "/documents", json={"user_id": "u1", "title": "t", "content": "hello world"}
    )
    doc_id = r.json()["document_id"]
    r2 = await client.get(f"/documents/{doc_id}")
    assert r2.status_code == 200
    assert r2.json()["status"] == "queued"


async def test_poll_unknown_returns_404(client):
    r = await client.get("/documents/000000000000000000000000")
    assert r.status_code == 404


async def test_poll_malformed_id_returns_404(client):
    r = await client.get("/documents/not-a-real-id")
    assert r.status_code == 404


async def test_list_is_paginated(client):
    for i in range(3):
        await client.post(
            "/documents",
            json={"user_id": "u2", "title": f"t{i}", "content": f"content number {i}"},
        )
    r = await client.get("/users/u2/documents?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1


async def test_list_status_filter(client):
    await client.post(
        "/documents", json={"user_id": "u3", "title": "t", "content": "abc"}
    )
    r = await client.get("/users/u3/documents?status=queued")
    assert r.status_code == 200
    assert r.json()["total"] == 1
    r2 = await client.get("/users/u3/documents?status=completed")
    assert r2.json()["total"] == 0


async def test_submit_empty_content_returns_422(client):
    r = await client.post(
        "/documents", json={"user_id": "u1", "title": "t", "content": ""}
    )
    assert r.status_code == 422
