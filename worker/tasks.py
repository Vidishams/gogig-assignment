import os
import logging
import tempfile
from datetime import datetime, timezone

from common.database import SessionLocal
from common.models import Image, AnalysisResult, ImageStatus
from common.checks import run_all_checks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gogig-worker")

CONTENT_TYPE_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def process_image(image_id: str):
    db = SessionLocal()
    tmp_path = None
    try:
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image:
            logger.error(f"Image {image_id} not found in DB")
            return

        image.status = ImageStatus.processing
        db.commit()
        logger.info(f"Processing image {image_id}")

        ext = CONTENT_TYPE_EXT.get(image.content_type, ".jpg")
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(image.image_data)
            tmp_path = tmp.name

        results, phash = run_all_checks(tmp_path, db, image.id)

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
        raise
    finally:
        db.close()
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)