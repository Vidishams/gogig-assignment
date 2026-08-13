"""
API-level tests. Uses an in-memory SQLite DB (swapped in for Postgres)
and monkeypatches the queue so these run without Docker/Redis/Postgres.
"""
import io
import sys
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.database import Base, get_db
from common import models  # noqa: ensures models are registered on Base
from api.app.main import app

TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_queue(monkeypatch):
    """Prevent tests from needing a real Redis connection."""
    monkeypatch.setattr("api.app.main.image_queue.enqueue", lambda *a, **kw: None)


def _tiny_png_bytes():
    # 1x1 transparent PNG
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000100e221bc330000000049454e44ae"
        "426082"
    )


def test_upload_rejects_bad_content_type():
    resp = client.post(
        "/images",
        files={"file": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_accepts_valid_image_and_returns_id():
    resp = client.post(
        "/images",
        files={"file": ("test.png", io.BytesIO(_tiny_png_bytes()), "image/png")},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert "image_id" in body


def test_status_404_for_unknown_id():
    fake_id = uuid.uuid4()
    resp = client.get(f"/images/{fake_id}/status")
    assert resp.status_code == 404


def test_results_404_for_unknown_id():
    fake_id = uuid.uuid4()
    resp = client.get(f"/images/{fake_id}/results")
    assert resp.status_code == 404


def test_upload_rejects_empty_file():
    resp = client.post(
        "/images",
        files={"file": ("empty.png", io.BytesIO(b""), "image/png")},
    )
    assert resp.status_code == 400
