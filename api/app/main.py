import uuid
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from rq import Retry
import os

from common.database import Base, engine, get_db
from common.models import Image, AnalysisResult, ImageStatus
from common.verdict import compute_verdict
from .schemas import UploadResponse, StatusResponse, ResultsResponse, CheckResult
from .queue import image_queue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gogig-api")

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="gOGig Vehicle Image Analysis Pipeline",
    lifespan=lifespan
)


@app.get("/")
def root():
    return RedirectResponse(url="/dashboard/")


app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/dashboard", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/images", response_model=UploadResponse, status_code=202)
@limiter.limit("10/minute")
async def upload_image(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"Unsupported content type: {file.content_type}")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(400, "File too large (max 15MB)")
    if len(contents) == 0:
        raise HTTPException(400, "Empty file")

    image_id = uuid.uuid4()

    # Bytes stored in the row itself - api and worker are separate
    # Render services with no shared disk, so a local file path would
    # never be visible to the worker.
    image = Image(
        id=image_id,
        filename=file.filename,
        content_type=file.content_type,
        image_data=contents,
        status=ImageStatus.pending,
    )
    db.add(image)
    db.commit()

    # Enqueue by string - the worker resolves and imports this itself,
    # inside its own container. Do NOT import process_image here.
    image_queue.enqueue(
        "worker.tasks.process_image",
        str(image_id),
        job_timeout=120,
        retry=Retry(max=2, interval=[10, 30]),
    )
    logger.info(f"Enqueued image {image_id} for analysis")

    return UploadResponse(image_id=image_id, status=image.status.value)


@app.get("/images/{image_id}/status", response_model=StatusResponse)
def get_status(image_id: uuid.UUID, db: Session = Depends(get_db)):
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(404, "Image not found")
    return StatusResponse(
        image_id=image.id,
        status=image.status.value,
        uploaded_at=image.uploaded_at,
        processed_at=image.processed_at,
    )


@app.get("/images/{image_id}/results", response_model=ResultsResponse)
def get_results(image_id: uuid.UUID, db: Session = Depends(get_db)):
    image = db.query(Image).filter(Image.id == image_id).first()
    if not image:
        raise HTTPException(404, "Image not found")

    results = db.query(AnalysisResult).filter(AnalysisResult.image_id == image_id).all()
    checks = [
        CheckResult(check_name=r.check_name, passed=r.passed, confidence=r.confidence, details=r.details)
        for r in results
    ]

    verdict = {"recommendation": None, "reasoning": None}
    if image.status == ImageStatus.completed:
        raw = [{"check_name": r.check_name, "passed": r.passed, "confidence": r.confidence} for r in results]
        verdict = compute_verdict(raw)

    return ResultsResponse(
        image_id=image.id,
        status=image.status.value,
        failure_reason=image.failure_reason,
        recommendation=verdict["recommendation"],
        reasoning=verdict["reasoning"],
        checks=checks,
    )