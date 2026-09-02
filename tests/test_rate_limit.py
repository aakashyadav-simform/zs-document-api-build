async def test_fourth_active_document_returns_429(client):
    for i in range(3):
        r = await client.post(
            "/documents",
            json={"user_id": "ru", "title": f"t{i}", "content": f"unique content {i}"},
        )
        assert r.status_code == 201, r.text
    r4 = await client.post(
        "/documents",
        json={"user_id": "ru", "title": "t4", "content": "unique content 4"},
    )
    assert r4.status_code == 429
