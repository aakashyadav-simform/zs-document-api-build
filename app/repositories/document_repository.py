from datetime import datetime, timezone

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from app.db.clients import get_documents


async def insert_document(doc: dict) -> str:
    result = await get_documents().insert_one(doc)
    return str(result.inserted_id)


async def get_document(document_id: str) -> dict | None:
    if not ObjectId.is_valid(document_id):
        return None
    return await get_documents().find_one({"_id": ObjectId(document_id)})


async def list_documents(
    user_id: str, status: str | None, page: int, page_size: int
) -> tuple[list[dict], int]:
    query: dict = {"user_id": user_id}
    if status:
        query["status"] = status
    coll = get_documents()
    total = await coll.count_documents(query)
    cursor = (
        coll.find(query)
        .sort("created_at", DESCENDING)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    docs = await cursor.to_list(length=page_size)
    return docs, total


async def find_completed_by_hash(content_hash: str) -> dict | None:
    return await get_documents().find_one(
        {"content_hash": content_hash, "status": "completed"}
    )


async def count_active(user_id: str) -> int:
    return await get_documents().count_documents(
        {"user_id": user_id, "status": {"$in": ["queued", "processing"]}}
    )


async def claim_next_job(now: datetime, stale_before: datetime) -> dict | None:
    return await get_documents().find_one_and_update(
        {
            "$or": [
                {"status": "queued", "next_attempt_at": {"$lte": now}},
                {"status": "processing", "processing_started_at": {"$lt": stale_before}},
            ]
        },
        {
            "$set": {
                "status": "processing",
                "processing_started_at": now,
                "updated_at": now,
            },
            "$inc": {"attempts": 1},
        },
        sort=[("created_at", ASCENDING)],
        return_document=ReturnDocument.AFTER,
    )


async def mark_completed(document_id: str, summary: str) -> None:
    now = datetime.now(timezone.utc)
    await get_documents().update_one(
        {"_id": ObjectId(document_id)},
        {
            "$set": {
                "status": "completed",
                "summary": summary,
                "error": None,
                "completed_at": now,
                "updated_at": now,
            }
        },
    )


async def mark_failed(document_id: str, error: str) -> None:
    now = datetime.now(timezone.utc)
    await get_documents().update_one(
        {"_id": ObjectId(document_id)},
        {"$set": {"status": "failed", "error": error, "updated_at": now}},
    )


async def requeue(document_id: str, next_attempt_at: datetime) -> None:
    now = datetime.now(timezone.utc)
    await get_documents().update_one(
        {"_id": ObjectId(document_id)},
        {
            "$set": {
                "status": "queued",
                "next_attempt_at": next_attempt_at,
                "processing_started_at": None,
                "updated_at": now,
            }
        },
    )
