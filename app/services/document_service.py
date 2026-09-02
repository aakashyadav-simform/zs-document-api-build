import hashlib
import logging
from datetime import datetime, timezone

from app.repositories import cache_repository as cache
from app.repositories import document_repository as repository
from app.schemas.document import DocumentCreate, Status

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    """Raised when a user already has the maximum active documents."""


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _new_doc(
    payload: DocumentCreate, content_hash: str, status: str, summary: str | None = None
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "user_id": payload.user_id,
        "title": payload.title,
        "content": payload.content,
        "content_hash": content_hash,
        "status": status,
        "summary": summary,
        "error": None,
        "attempts": 0,
        "next_attempt_at": now if status == Status.queued.value else None,
        "created_at": now,
        "updated_at": now,
        "processing_started_at": None,
        "completed_at": now if status == Status.completed.value else None,
    }


def _to_detail(doc: dict) -> dict:
    return {
        "document_id": str(doc["_id"]),
        "user_id": doc["user_id"],
        "title": doc["title"],
        "status": doc["status"],
        "summary": doc.get("summary"),
        "error": doc.get("error"),
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


def _to_list_item(doc: dict) -> dict:
    return {
        "document_id": str(doc["_id"]),
        "title": doc["title"],
        "status": doc["status"],
        "created_at": doc["created_at"],
    }


async def submit_document(payload: DocumentCreate) -> dict:
    content_hash = _hash(payload.content)

    # Content-based cache: Redis first, then durable Mongo lookup.
    cached_summary = await cache.get_cached_summary(content_hash)
    if cached_summary is None:
        prior = await repository.find_completed_by_hash(content_hash)
        if prior is not None:
            cached_summary = prior["summary"]
            await cache.set_cached_summary(content_hash, cached_summary)

    if cached_summary is not None:
        doc_id = await repository.insert_document(
            _new_doc(payload, content_hash, Status.completed.value, cached_summary)
        )
        logger.info(
            "submit cache hit",
            extra={"extra_fields": {"document_id": doc_id, "user_id": payload.user_id}},
        )
        return {"document_id": doc_id, "status": Status.completed.value}

    # Rate limit: only queued/processing docs count.
    if not await cache.try_acquire_rate_slot(payload.user_id):
        logger.info(
            "submit rate limited", extra={"extra_fields": {"user_id": payload.user_id}}
        )
        raise RateLimitExceeded()

    try:
        doc_id = await repository.insert_document(
            _new_doc(payload, content_hash, Status.queued.value)
        )
    except Exception:
        await cache.release_rate_slot(payload.user_id)
        raise

    logger.info(
        "submit queued",
        extra={"extra_fields": {"document_id": doc_id, "user_id": payload.user_id}},
    )
    return {"document_id": doc_id, "status": Status.queued.value}


async def get_document(document_id: str) -> dict | None:
    doc = await repository.get_document(document_id)
    return _to_detail(doc) if doc else None


async def list_documents(user_id, status, page: int, page_size: int) -> dict:
    status_value = status.value if status else None
    docs, total = await repository.list_documents(user_id, status_value, page, page_size)
    return {
        "items": [_to_list_item(d) for d in docs],
        "page": page,
        "page_size": page_size,
        "total": total,
    }
