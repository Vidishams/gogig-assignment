"""
Unit tests for check functions and verdict aggregation. These don't need
a running DB/Redis/Docker stack - they test the pure logic directly.
"""
import io
import numpy as np
from PIL import Image as PILImage

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.checks import check_blur, check_brightness, INDIAN_PLATE_REGEX, BH_SERIES_PLATE_REGEX
from common.verdict import compute_verdict


def _make_test_image(path, color=(120, 120, 120), size=(200, 200), sharp=True):
    """Creates a synthetic test image. sharp=True draws a checkerboard
    pattern (high edge variance); sharp=False writes a flat blurred image."""
    if sharp:
        arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        arr[::10, :] = 255  # stripes -> high Laplacian variance
        arr[:, ::10] = 255
        img = PILImage.fromarray(arr)
    else:
        img = PILImage.new("RGB", size, color)
    img.save(path)


def test_blur_check_flags_flat_image_as_blurry(tmp_path):
    path = tmp_path / "flat.jpg"
    _make_test_image(str(path), sharp=False)
    result = check_blur(str(path))
    assert result["check_name"] == "blur"
    assert result["passed"] is False  # flat image has near-zero variance -> blurry


def test_blur_check_passes_sharp_image(tmp_path):
    path = tmp_path / "sharp.jpg"
    _make_test_image(str(path), sharp=True)
    result = check_blur(str(path))
    assert result["passed"] is True


def test_brightness_check_flags_dark_image(tmp_path):
    path = tmp_path / "dark.jpg"
    _make_test_image(str(path), color=(5, 5, 5), sharp=False)
    result = check_brightness(str(path))
    assert result["passed"] is False
    assert result["details"]["reason"] == "too dark"


def test_brightness_check_passes_normal_image(tmp_path):
    path = tmp_path / "normal.jpg"
    _make_test_image(str(path), color=(130, 130, 130), sharp=False)
    result = check_brightness(str(path))
    assert result["passed"] is True


def test_plate_regex_accepts_valid_format():
    assert INDIAN_PLATE_REGEX.match("MH12AB1234")
    assert INDIAN_PLATE_REGEX.match("KA05MH1234")


def test_bh_series_plate_regex_accepts_valid_format():
    assert BH_SERIES_PLATE_REGEX.match("22BH1234AA")
    assert BH_SERIES_PLATE_REGEX.match("23BH5678A")


def test_plate_regex_rejects_invalid_format():
    assert not INDIAN_PLATE_REGEX.match("HELLO")
    assert not INDIAN_PLATE_REGEX.match("MH12")


def test_verdict_accepts_when_all_pass():
    results = [
        {"check_name": "blur", "passed": True, "confidence": 0.9},
        {"check_name": "tamper", "passed": True, "confidence": 0.9},
    ]
    v = compute_verdict(results)
    assert v["recommendation"] == "accept"


def test_verdict_rejects_on_high_confidence_tamper_failure():
    results = [
        {"check_name": "blur", "passed": True, "confidence": 0.9},
        {"check_name": "tamper", "passed": False, "confidence": 0.85},
    ]
    v = compute_verdict(results)
    assert v["recommendation"] == "reject"


def test_verdict_needs_review_on_noncritical_failure():
    results = [
        {"check_name": "plate_format", "passed": False, "confidence": 0.4},
        {"check_name": "tamper", "passed": True, "confidence": 0.9},
    ]
    v = compute_verdict(results)
    assert v["recommendation"] == "needs_review"
