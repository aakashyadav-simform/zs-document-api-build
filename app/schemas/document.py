from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Status(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class DocumentCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1, max_length=1_000_000)


class SubmitResponse(BaseModel):
    document_id: str
    status: Status


class DocumentDetail(BaseModel):
    document_id: str
    user_id: str
    title: str
    status: Status
    summary: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentListItem(BaseModel):
    document_id: str
    title: str
    status: Status
    created_at: datetime


class PaginatedDocuments(BaseModel):
    items: list[DocumentListItem]
    page: int
    page_size: int
    total: int


class HealthResponse(BaseModel):
    status: str
    mongo: bool
    redis: bool
