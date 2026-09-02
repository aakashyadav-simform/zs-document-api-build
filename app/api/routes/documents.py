from fastapi import APIRouter, HTTPException, Query

from app.schemas.document import (
    DocumentCreate,
    DocumentDetail,
    PaginatedDocuments,
    Status,
    SubmitResponse,
)
from app.services import document_service as service

router = APIRouter()


@router.post("/documents", status_code=201, response_model=SubmitResponse)
async def submit_document(payload: DocumentCreate):
    return await service.submit_document(payload)


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str):
    doc = await service.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/users/{user_id}/documents", response_model=PaginatedDocuments)
async def list_user_documents(
    user_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Status | None = None,
):
    return await service.list_documents(user_id, status, page, page_size)
