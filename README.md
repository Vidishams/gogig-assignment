# gOGig Vehicle Image Analysis Pipeline

Backend system that accepts vehicle images uploaded from the field, analyzes
them asynchronously for common quality/authenticity issues, and exposes
status + results APIs.

## Architecture

**Service flow**
1. Client `POST`s an image to the API.
2. API validates the file, saves it to disk, writes a DB row with
   `status=pending`, enqueues a job on Redis/RQ, and returns the image ID
   immediately (does not wait for analysis).
3. A separate worker process pulls the job off the queue, sets
   `status=processing`, runs 6 checks, writes results to the DB, and sets
   `status=completed` or `status=failed`.
4. Client polls `GET /images/{id}/status` and `GET /images/{id}/results`
   at any point after upload.

**Processing flow (worker)**
Each check runs independently and is wrapped in its own try/except, so one
check erroring out doesn't abort the whole job or crash the worker — it's
recorded as a failed check with an error detail instead. Checks run:
`blur -> brightness -> screenshot -> tamper -> plate_format -> duplicate`.

**Queue strategy**
Redis + RQ was chosen over Celery/SQS/RabbitMQ because it needed zero
infra beyond a Redis container, and RQ's built-in `Retry(max=2,
interval=[10, 30])` covers transient failures (e.g. a momentary DB
connection blip) without hand-rolling retry logic. At gOGig's actual
scale (many workers uploading concurrently) this would need to move to
something with better horizontal scaling guarantees (SQS/Celery +
autoscaled workers), but for this assignment's scope RQ is the right
size.

**Major design decisions**
- Upload API and worker are separate Docker services so they scale
  independently (add worker replicas without touching the API).
- `common/` is a shared package (DB models, checks) imported by both
  api and worker, so there is one source of truth for the schema and
  no duplicated check logic between services.
- Every check returns a confidence score + structured details, not just
  pass/fail, so a human reviewer downstream can triage by how *sure* the
  system is, not just what it flagged. Individual check results are then
  aggregated into one overall `recommendation` (`accept` /
  `needs_review` / `reject`) with a `reasoning` string — see
  `common/verdict.py`. Critical checks (tamper, duplicate) failing with
  high confidence trigger an outright reject; everything else that fails
  routes to `needs_review` rather than auto-rejecting, since the
  assignment explicitly does not expect perfect ML accuracy.
- Duplicate detection uses perceptual hashing (`imagehash.phash`)
  compared against every existing image's stored hash. This is O(n) per
  upload — fine for a take-home, but noted as a scalability concern below.
- Rate limiting (10 uploads/minute per IP, via `slowapi`) protects the
  upload endpoint from being flooded, since bad/duplicate uploads
  directly cost worker time.
- A minimal static dashboard (`/dashboard`) polls the results endpoint
  and renders check results + the overall verdict as a table, so a
  reviewer can see the pipeline work without running curl commands.

## Database schema
- `images`: id, filename, storage_path, phash, status, failure_reason,
  uploaded_at, processed_at
- `analysis_results`: id, image_id (FK), check_name, passed, confidence,
  details (JSON), created_at

## Overall verdict
`GET /images/{id}/results` includes `recommendation` (`accept` /
`needs_review` / `reject`) and `reasoning`, computed by aggregating all
6 check results (`common/verdict.py`) once processing completes. This
is deliberately conservative: only high-confidence failures on critical
checks (tamper, duplicate) auto-reject; everything else routes to
`needs_review` for a human to decide, matching the assignment's framing
that the goal is "structuring uncertainty," not pretending to be
perfectly accurate.

## The 6 checks
| Check | Method |
|---|---|
| Blur | Laplacian variance of grayscale image |
| Brightness | Mean grayscale pixel intensity |
| Screenshot / photo-of-photo | Missing camera EXIF + common screen resolution |
| Tamper | Error Level Analysis (JPEG resave diff) |
| Plate format | Tesseract OCR + Indian plate regex |
| Duplicate | Perceptual hash (pHash) vs. all stored images, Hamming distance <= 5 |

## AI Usage Disclosure

- Used Claude to scaffold the initial FastAPI/RQ/SQLAlchemy project
  structure and the boilerplate for the three endpoints.
- Used Claude to draft the Error Level Analysis (tamper) check. The
  first version resaved at JPEG quality 95 and flagged almost every real
  photo as tampered because the ELA score baseline was too close to
  natural JPEG re-compression noise — lowered quality to 90 and raised
  the threshold from 3.0 to 8.0 after testing against the sample images,
  which brought false positives on genuine (untampered) photos to zero
  in local testing.
- Used Claude to draft the screenshot-detection heuristic. Initial
  version only checked for missing EXIF, which flagged too many genuine
  camera photos (many phones strip EXIF metadata by default) —
  corrected by requiring *both* missing EXIF *and* a common screen
  resolution match before flagging, reducing false positives.
- Manually validated every check by running it against the 3 provided
  sample images before wiring it into the worker pipeline (see
  `test_output/` for raw results).
- Did not use AI-generated code for the DB schema or Docker Compose
  networking — wrote those directly since correctness there is easy to
  verify by just running `docker compose up`.

## Trade-offs

**Intentionally simplified**
- Local disk storage instead of S3/cloud storage.
- Duplicate detection scans all stored hashes linearly instead of using
  an indexed similarity search.
- No authentication/authorization on the API.
- Plate OCR uses a single Tesseract pass with no image preprocessing
  (deskew, contrast enhancement) beyond grayscale conversion.

**Would improve with more time**
- Move duplicate detection to a proper vector/hash index (e.g. FAISS or
  a locality-sensitive hashing table) so it doesn't degrade linearly
  with dataset size.
- Add a lightweight status dashboard (bonus item) so results are
  browsable without hitting the API directly.
- Preprocess plates before OCR (crop to plate region via a small
  detector, deskew) — current OCR confidence is capped at 0.7 precisely
  because a full-frame OCR pass on a whole vehicle photo is noisy.

**Scalability concerns**
- Single worker replica by default in docker-compose; horizontal scale
  is just `docker compose up --scale worker=N` since workers are
  stateless and coordinate purely through the Redis queue.
- Duplicate check's linear scan becomes the bottleneck first as image
  volume grows — flagged above as the top scalability fix.

**Failure handling**
- Per-check try/except means partial results are always available even
  if one check fails.
- RQ retries transient job failures twice with backoff before marking
  the image `failed` with a stored reason string.
- Upload validation (content-type, size, non-empty) happens synchronously
  at the API layer, before a job is ever enqueued, so bad uploads never
  reach the queue.

## Running instructions

```bash
docker compose up --build
```

- API available at `http://localhost:8000`
- Interactive API docs (auto-generated): `http://localhost:8000/docs`
- Results dashboard (no curl needed): `http://localhost:8000/dashboard`
- `POST /images` (multipart form, field name `file`) — upload an image
- `GET /images/{image_id}/status` — check processing status
- `GET /images/{image_id}/results` — fetch check results, verdict, or failure reason

Example:
```bash
curl -F "file=@sample1.jpg" http://localhost:8000/images
curl http://localhost:8000/images/<image_id>/status
curl http://localhost:8000/images/<image_id>/results
```

### Running tests
```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```
Tests run against an in-memory SQLite DB with the queue mocked out, so
they don't require Docker/Redis/Postgres to be running.

### Running the demo/seed script
With the stack up (`docker compose up`), upload the 3 sample images and
print full results for each — this is what generates the required test
output:
```bash
pip install -r requirements-dev.txt
python scripts/demo.py http://localhost:8000 sample1.jpg sample2.jpg sample3.jpg
```

## Assumptions
- "Indian vehicle number format" validated against the standard
  `SS DD LLL DDDD` pattern (e.g. `MH12AB1234`) and the newer BH-series
  format (e.g. `22BH1234AA`); diplomatic, defense, and temporary dealer
  plate formats are out of scope for this assignment.
- Images are JPEG/PNG/WebP, max 15MB.
