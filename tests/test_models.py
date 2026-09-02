import pytest
from pydantic import ValidationError

from app.schemas.document import DocumentCreate, Status


def test_valid_document_create():
    doc = DocumentCreate(user_id="u1", title="Report", content="some text")
    assert doc.user_id == "u1"


def test_empty_content_rejected():
    with pytest.raises(ValidationError):
        DocumentCreate(user_id="u1", title="t", content="")


def test_empty_user_id_rejected():
    with pytest.raises(ValidationError):
        DocumentCreate(user_id="", title="t", content="hello")


def test_status_values():
    assert Status.queued.value == "queued"
    assert Status.completed.value == "completed"
