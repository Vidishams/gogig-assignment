import logging
from datetime import datetime, timezone

from common.database import SessionLocal
from common.models import Image, AnalysisResult, ImageStatus
from common.checks import run_all_checks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gogig-worker")


def process_image(image_id: str):
    """Entry point invoked by RQ. Runs all checks against the image and
    writes results back to the database. Wrapped so that any unexpected
    exception marks the job 'failed' with a reason instead of crashing
    the worker or leaving the image stuck in 'processing'."""
    db = SessionLocal()
    try:
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image:
            logger.error(f"Image {image_id} not found in DB")
            return

        image.status = ImageStatus.processing
        db.commit()
        logger.info(f"Processing image {image_id}")

        results, phash = run_all_checks(image.storage_path, db, image.id)

        for r in results:
            db.add(AnalysisResult(
                image_id=image.id,
                check_name=r["check_name"],
                passed=r["passed"],
                confidence=r["confidence"],
                details=r.get("details"),
            ))

        image.phash = phash
        image.status = ImageStatus.completed
        image.processed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Completed image {image_id}")

    except Exception as e:
        logger.exception(f"Failed processing image {image_id}: {e}")
        db.rollback()
        image = db.query(Image).filter(Image.id == image_id).first()
        if image:
            image.status = ImageStatus.failed
            image.failure_reason = str(e)
            image.processed_at = datetime.now(timezone.utc)
            db.commit()
        raise  # re-raise so RQ's retry mechanism can kick in
    finally:
        db.close()
