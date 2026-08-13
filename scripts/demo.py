"""
Uploads one or more images to a running instance of the API, polls until
each finishes processing, and prints the final results as JSON.

Doubles as the script used to generate the required test-output
screenshots against the 3 sample images.

Usage:
    python scripts/demo.py http://localhost:8000 sample1.jpg sample2.jpg sample3.jpg
"""
import sys
import time
import json

import requests


def upload_and_wait(base_url: str, path: str, poll_interval: float = 1.5, timeout: float = 60.0):
    with open(path, "rb") as f:
        resp = requests.post(
    f"{base_url}/images",
    files={"file": ("image.png", f, "image/png")}
)
    resp.raise_for_status()
    image_id = resp.json()["image_id"]
    print(f"[{path}] uploaded -> image_id={image_id}")

    start = time.time()
    while time.time() - start < timeout:
        status_resp = requests.get(f"{base_url}/images/{image_id}/status")
        status = status_resp.json()["status"]
        print(f"[{path}] status={status}")
        if status in ("completed", "failed"):
            break
        time.sleep(poll_interval)

    results_resp = requests.get(f"{base_url}/images/{image_id}/results")
    results = results_resp.json()
    print(f"[{path}] final results:")
    print(json.dumps(results, indent=2))
    print("-" * 60)
    return results


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/demo.py <base_url> <image1> [image2] [image3] ...")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")
    image_paths = sys.argv[2:]

    all_results = []
    for path in image_paths:
        all_results.append(upload_and_wait(base_url, path))

    print(f"Processed {len(all_results)} image(s).")
