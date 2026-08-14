# gOGig Vehicle Image Analysis Pipeline

A backend system that accepts vehicle images uploaded from the field, analyzes them asynchronously for common quality and authenticity issues, and provides status and analysis results through APIs.

## Features

- Asynchronous image processing
- FastAPI backend
- Redis + RQ background jobs
- PostgreSQL database
- Dockerized services
- Vehicle image quality checks
- Blur detection
- Brightness detection
- Screenshot detection
- Tamper detection
- Indian number plate format detection
- Duplicate image detection
- Confidence scores for every check
- Overall `accept`, `needs_review`, or `reject` recommendation
- Web dashboard for uploading and viewing results
- Rate limiting
- Background job retry handling

---

## Architecture

```text
Client
   |
   | POST /images
   v
FastAPI API
   |
   | Save image + create DB record
   |
   v
Redis / RQ Queue
   |
   v
Background Worker
   |
   | Run 6 analysis checks
   |
   v
PostgreSQL
   |
   v
Results API / Dashboard
```

The API does not wait for image processing to finish.

Instead, it immediately returns an image ID and the worker processes the image in the background.

---

## Processing Flow

```text
Upload Image
     |
     v
Validate Image
     |
     v
Save Image
     |
     v
Create DB Record
     |
     v
Add Job to Redis Queue
     |
     v
Worker Picks Job
     |
     v
Run Image Analysis
     |
     +--> Blur
     |
     +--> Brightness
     |
     +--> Screenshot
     |
     +--> Tamper
     |
     +--> Plate Format
     |
     +--> Duplicate
     |
     v
Store Results
     |
     v
Generate Overall Verdict
     |
     v
Completed
```

---

## Image Analysis Checks

| Check | Method |
|---|---|
| Blur | Laplacian variance of grayscale image |
| Brightness | Mean grayscale pixel intensity |
| Screenshot | Missing EXIF + common screen resolution |
| Tamper | Error Level Analysis (ELA) |
| Plate Format | Tesseract OCR + Indian plate regex |
| Duplicate | Perceptual hashing (pHash) |

---

## 1. Blur Detection

The image is converted to grayscale and Laplacian variance is calculated.

A low variance indicates that the image may be blurry.

```text
Image
  ↓
Grayscale
  ↓
Laplacian Variance
  ↓
Blur Confidence
```

---

## 2. Brightness Detection

The average grayscale pixel intensity is calculated.

Images that are too dark or too bright can be flagged for review.

---

## 3. Screenshot Detection

The system checks for:

- Missing camera EXIF metadata
- Common screen resolutions

Both conditions are considered together to reduce false positives.

---

## 4. Tamper Detection

Error Level Analysis (ELA) is used to identify unusual compression differences that may indicate image manipulation.

The implementation was tested and tuned against the provided sample images to reduce false positives.

---

## 5. Plate Format Detection

Tesseract OCR is used to extract text from the vehicle image.

The extracted text is then checked against supported Indian vehicle number formats.

Example:

```text
MH12AB1234
```

BH-series format is also supported:

```text
22BH1234AA
```

Diplomatic, defense, and temporary dealer plate formats are outside the scope of this assignment.

---

## 6. Duplicate Detection

Duplicate images are detected using perceptual hashing (`pHash`).

The hash of the uploaded image is compared with hashes of previously uploaded images.

A Hamming distance of `<= 5` is considered a duplicate.

This allows the system to detect when the same image is uploaded again.

---

## Overall Verdict

After all six checks are completed, the results are combined into one overall recommendation.

Possible recommendations are:

```text
ACCEPT
NEEDS REVIEW
REJECT
```

The system is intentionally conservative.

High-confidence failures in critical checks such as tampering or duplicate detection can result in `REJECT`.

Other failures are generally sent to `NEEDS REVIEW` so that a human reviewer can make the final decision.

---

## Example Result

```text
Status: Completed

Checks Passed: 4/6
Average Confidence: 75%

Recommendation: Needs Review
```

The results API also provides a reasoning message explaining why the image received the recommendation.

---

## Database

### `images`

Stores uploaded image information.

```text
id
filename
storage_path
phash
status
failure_reason
uploaded_at
processed_at
```

### `analysis_results`

Stores individual check results.

```text
id
image_id
check_name
passed
confidence
details
created_at
```

---

## Failure Handling

Each analysis check runs independently.

If one check fails, the remaining checks can still continue.

```text
Check 1 → Pass
Check 2 → Pass
Check 3 → Error
Check 4 → Pass
Check 5 → Fail
Check 6 → Pass
```

The failed check is stored with its error details instead of stopping the complete analysis.

RQ also retries transient worker failures up to two times.

---

## Rate Limiting

The upload API is protected with rate limiting.

```text
10 uploads / minute / IP
```

This prevents excessive uploads from consuming worker resources.

---

## Technology Stack

| Component | Technology |
|---|---|
| Backend | FastAPI |
| Background Jobs | RQ |
| Queue | Redis |
| Database | PostgreSQL |
| ORM | SQLAlchemy |
| OCR | Tesseract |
| Image Processing | Pillow / OpenCV |
| Duplicate Detection | imagehash / pHash |
| Containerization | Docker |
| Testing | Pytest |
| Dashboard | HTML, CSS, JavaScript |

---

## Project Architecture

```text
gogig-assignment/
│
├── api/
│
├── worker/
│
├── common/
│   ├── models.py
│   ├── checks/
│   └── verdict.py
│
├── tests/
│
├── scripts/
│   └── demo.py
│
├── test_output/
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

---

## Running the Project

Start the complete application using Docker:

```bash
docker compose up --build
```

The API will be available at:

```text
http://localhost:8000
```

---

## Dashboard

Open:

```text
http://localhost:8000/dashboard
```

The dashboard allows you to:

- Upload vehicle images
- Track processing status
- Look up submissions
- View analysis results
- View confidence scores
- View the final recommendation

---

## API Documentation

FastAPI interactive documentation:

```text
http://localhost:8000/docs
```

---

## API Endpoints

### Upload Image

```http
POST /images
```

Example:

```bash
curl -F "file=@sample1.jpg" http://localhost:8000/images
```

---

### Check Status

```http
GET /images/{image_id}/status
```

Example:

```bash
curl http://localhost:8000/images/<image_id>/status
```

---

### Get Results

```http
GET /images/{image_id}/results
```

Example:

```bash
curl http://localhost:8000/images/<image_id>/results
```

---

## Running Tests

Install dependencies:

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Run tests:

```bash
pytest tests/ -v
```

The tests use an in-memory SQLite database and mock the queue, so Docker, Redis, and PostgreSQL do not need to be running for the unit tests.

---

## Running the Demo

Start the application:

```bash
docker compose up
```

Then run:

```bash
pip install -r requirements-dev.txt
```

Run the demo script:

```bash
python scripts/demo.py http://localhost:8000 sample1.jpg sample2.jpg sample3.jpg
```

This uploads the sample images and prints their analysis results.

---

## Testing

The system was tested using the provided vehicle images.

Testing included:

- Genuine vehicle images
- Different image qualities
- Duplicate image uploads
- Blur detection
- Brightness detection
- Screenshot detection
- Tamper detection
- Number plate detection
- Overall verdict generation

The same image was also uploaded again to verify duplicate detection.

When the same image is uploaded again, the perceptual hash matches the previously stored image and the duplicate check flags it accordingly.

---

## AI Usage Disclosure

Claude was used during development for:

- Initial FastAPI/RQ/SQLAlchemy project scaffolding
- API endpoint boilerplate
- Initial Error Level Analysis implementation
- Initial screenshot detection implementation

The generated approaches were manually tested and modified.

For example, the initial screenshot detection relied only on missing EXIF metadata. This caused false positives because some genuine camera images do not contain EXIF metadata.

The logic was improved to consider both missing EXIF metadata and common screen resolutions.

The tamper detection implementation was also tested against the provided sample images and adjusted to reduce false positives.

The database schema and Docker Compose networking were implemented directly.

---

## Trade-offs

The following areas were intentionally simplified for the assignment:

### Local Storage

Images are stored on local disk instead of cloud storage such as Amazon S3.

### Duplicate Search

Duplicate detection currently compares the new pHash against all stored hashes.

This is:

```text
O(n)
```

per upload.

### Authentication

Authentication and authorization are not implemented.

### Plate OCR

Plate OCR uses a single Tesseract pass without advanced plate-region detection or preprocessing.

---

## Future Improvements

Possible production improvements include:

- Move image storage to S3 or another object-storage service
- Use an indexed similarity search for duplicate detection
- Add authentication and authorization
- Improve number plate detection
- Crop and preprocess the number plate before OCR
- Add advanced image tamper detection
- Add autoscaling for workers
- Improve monitoring and logging
- Add production-grade queue infrastructure

---

## Scalability

Workers are stateless and communicate through Redis.

Multiple workers can be started using:

```bash
docker compose up --scale worker=3
```

The main scalability concern is the current linear duplicate search.

At large image volumes, duplicate detection should be replaced with a proper similarity/hash index.

---

## Assumptions

- Supported image formats are JPEG, PNG, and WebP.
- Maximum image size is 15 MB.
- Indian vehicle number plates are validated against supported standard and BH-series formats.
- Diplomatic, defense, and temporary dealer plates are outside the scope.
- Local disk storage is sufficient for this assignment.
- Automated results are intended to assist human review rather than replace it.

---

## Conclusion

The gOGig Vehicle Image Analysis Pipeline provides an asynchronous system for processing vehicle images uploaded from the field.

It combines six independent image checks:

```text
Blur
Brightness
Screenshot
Tamper
Plate Format
Duplicate
```

The results are combined into a conservative recommendation:

```text
ACCEPT
NEEDS REVIEW
REJECT
```

The system provides confidence scores and structured analysis results so that reviewers can understand why an image was flagged.

The architecture is lightweight for the assignment while providing a clear path toward production scalability.
