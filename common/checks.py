"""
Image analysis checks for the vehicle-photo pipeline.

Each check function takes an image path (and sometimes a DB session for
cross-image lookups like duplicate detection) and returns a dict:
    {"check_name": str, "passed": bool, "confidence": float, "details": Any}

"passed" means "no issue found" (e.g. blur_check passed=True means NOT blurry).
confidence is 0.0-1.0: how sure the heuristic is about its verdict.
"""
import re
import io

import cv2
import numpy as np
from PIL import Image as PILImage
from PIL.ExifTags import TAGS
import imagehash
import pytesseract

# Common screen resolutions - a strong signal of "screenshot" rather than
# a camera photo, when combined with missing EXIF.
COMMON_SCREEN_RESOLUTIONS = {
    (1920, 1080), (1080, 1920), (1366, 768), (768, 1366),
    (1280, 720), (720, 1280), (2340, 1080), (1080, 2340),
}

INDIAN_PLATE_REGEX = re.compile(r"^[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4}$")
# BH-series (Bharat series), e.g. 22BH1234AA - year + BH + number + 2 letters
BH_SERIES_PLATE_REGEX = re.compile(r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$")


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def check_blur(image_path: str) -> dict:
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"check_name": "blur", "passed": False, "confidence": 1.0,
                 "details": {"error": "could not read image"}}

    variance = cv2.Laplacian(img, cv2.CV_64F).var()
    threshold = 100.0
    is_sharp = variance >= threshold
    # confidence: how far from the threshold, scaled
    confidence = _clamp(abs(variance - threshold) / threshold)
    return {
        "check_name": "blur",
        "passed": bool(is_sharp),
        "confidence": round(confidence, 3),
        "details": {"laplacian_variance": round(float(variance), 2), "threshold": threshold},
    }


def check_brightness(image_path: str) -> dict:
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return {"check_name": "brightness", "passed": False, "confidence": 1.0,
                 "details": {"error": "could not read image"}}

    mean_brightness = float(np.mean(img))
    low_threshold, high_threshold = 50.0, 235.0
    is_ok = low_threshold <= mean_brightness <= high_threshold
    if mean_brightness < low_threshold:
        confidence = _clamp((low_threshold - mean_brightness) / low_threshold)
        reason = "too dark"
    elif mean_brightness > high_threshold:
        confidence = _clamp((mean_brightness - high_threshold) / (255 - high_threshold))
        reason = "overexposed"
    else:
        confidence = _clamp(1 - abs(mean_brightness - 140) / 140)
        reason = "ok"
    return {
        "check_name": "brightness",
        "passed": bool(is_ok),
        "confidence": round(confidence, 3),
        "details": {"mean_brightness": round(mean_brightness, 2), "reason": reason},
    }


def check_duplicate(image_path: str, db_session, exclude_image_id=None) -> dict:
    from common.models import Image  # local import avoids circulars in worker context

    phash = str(imagehash.phash(PILImage.open(image_path)))

    query = db_session.query(Image).filter(Image.phash.isnot(None))
    if exclude_image_id is not None:
        query = query.filter(Image.id != exclude_image_id)

    closest_distance = None
    for existing in query.all():
        try:
            dist = imagehash.hex_to_hash(phash) - imagehash.hex_to_hash(existing.phash)
        except ValueError:
            continue
        if closest_distance is None or dist < closest_distance:
            closest_distance = dist

    is_duplicate = closest_distance is not None and closest_distance <= 5
    confidence = _clamp(1 - (closest_distance / 10)) if closest_distance is not None else 0.0
    return {
        "check_name": "duplicate",
        "passed": not is_duplicate,
        "confidence": round(confidence, 3),
        "details": {"phash": phash, "closest_hamming_distance": closest_distance},
    }, phash


def check_screenshot(image_path: str) -> dict:
    try:
        pil_img = PILImage.open(image_path)
        exif_raw = pil_img._getexif()
    except Exception:
        exif_raw = None

    has_camera_exif = False
    if exif_raw:
        tags = {TAGS.get(k, k): v for k, v in exif_raw.items()}
        has_camera_exif = any(k in tags for k in ("Make", "Model", "DateTimeOriginal"))

    dims = PILImage.open(image_path).size
    is_common_screen_res = dims in COMMON_SCREEN_RESOLUTIONS

    looks_like_screenshot = (not has_camera_exif) and is_common_screen_res
    confidence = 0.8 if looks_like_screenshot else (0.3 if not has_camera_exif else 0.1)
    return {
        "check_name": "screenshot",
        "passed": not looks_like_screenshot,
        "confidence": round(confidence, 3),
        "details": {"has_camera_exif": has_camera_exif, "dimensions": dims,
                     "matches_common_screen_resolution": is_common_screen_res},
    }


def check_tamper(image_path: str) -> dict:
    """Error Level Analysis: resave at known JPEG quality and diff against
    the original. Regions that were edited compress differently and show
    up as bright patches in the ELA diff."""
    try:
        original = PILImage.open(image_path).convert("RGB")
        buffer = io.BytesIO()
        original.save(buffer, "JPEG", quality=90)
        buffer.seek(0)
        resaved = PILImage.open(buffer)

        diff = np.array(original, dtype=np.int16) - np.array(resaved, dtype=np.int16)
        ela_score = float(np.mean(np.abs(diff)))
    except Exception as e:
        return {"check_name": "tamper", "passed": False, "confidence": 1.0,
                 "details": {"error": str(e)}}

    threshold = 8.0
    looks_tampered = ela_score > threshold
    confidence = _clamp(abs(ela_score - threshold) / threshold)
    return {
        "check_name": "tamper",
        "passed": not looks_tampered,
        "confidence": round(confidence, 3),
        "details": {"ela_score": round(ela_score, 2), "threshold": threshold},
    }


def check_plate(image_path: str) -> dict:
    img = cv2.imread(image_path)
    if img is None:
        return {"check_name": "plate_format", "passed": False, "confidence": 1.0,
                 "details": {"error": "could not read image"}}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    raw_text = pytesseract.image_to_string(gray, config="--psm 7")
    cleaned = re.sub(r"[^A-Z0-9]", "", raw_text.upper())

    match = INDIAN_PLATE_REGEX.match(cleaned) or BH_SERIES_PLATE_REGEX.match(cleaned)
    is_valid = match is not None
    matched_format = "standard" if (is_valid and INDIAN_PLATE_REGEX.match(cleaned)) else (
        "bh_series" if is_valid else None
    )
    return {
        "check_name": "plate_format",
        "passed": bool(is_valid),
        "confidence": 0.7 if is_valid else 0.4,  # OCR is noisy, keep confidence modest
        "details": {"ocr_raw_text": raw_text.strip(), "cleaned_candidate": cleaned,
                     "matched_format": matched_format},
    }


def run_all_checks(image_path: str, db_session, image_id) -> list[dict]:
    """Runs every check, isolating failures so one bad check doesn't kill
    the whole job. Returns list of result dicts. Also updates the image's
    stored phash as a side effect of the duplicate check."""
    results = []

    for fn in (check_blur, check_brightness, check_screenshot, check_tamper, check_plate):
        try:
            results.append(fn(image_path))
        except Exception as e:
            results.append({"check_name": fn.__name__.replace("check_", ""),
                             "passed": False, "confidence": 1.0, "details": {"error": str(e)}})

    try:
        dup_result, phash = check_duplicate(image_path, db_session, exclude_image_id=image_id)
        results.append(dup_result)
    except Exception as e:
        phash = None
        results.append({"check_name": "duplicate", "passed": False, "confidence": 1.0,
                         "details": {"error": str(e)}})

    return results, phash
