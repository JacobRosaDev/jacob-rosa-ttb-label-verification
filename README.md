# TTB Label Verification Proof-of-Concept

A stateless FastAPI service with static HTML pages for checking whether distilled spirits label images match seven expected TTB label fields.

## Live Demo

- **Frontend URL:** https://ttb-label-verification-lwrd.onrender.com
- **Backend base URL:** https://ttb-label-verification-lwrd.onrender.com
- **Health URL:** https://ttb-label-verification-lwrd.onrender.com/health
- **Last manually verified:** July 12, 2026
- **Production vision model:** `gpt-5.4-nano`

Verified live checks on July 12, 2026:

- Frontend loaded successfully.
- `GET /health` passed.
- `POST /verify` passed.
- `POST /verify/batch` passed.
- An earlier `POST /verify` smoke attempt returned HTTP 504, and the immediate retry passed all checks.

## What The App Does

The app accepts one label image, or a batch of label images, plus expected application data. It sends each image to a vision extraction service, receives structured label text, and compares the extracted values against the submitted values.

- Government warning text is an exact, case-sensitive match after whitespace collapse.
- Brand name, class/type, and producer use fuzzy normalized text matching.
- Country of origin accepts known country synonyms.
- ABV supports percent values and proof values; net contents use unit-normalized comparison.
- The service uses no database and does not persist uploaded images or results.

## Architecture At A Glance

Request flow:

```text
Browser or curl
  -> API layer: backend/app/main.py
  -> image preprocessing: OpenAIVisionService._preprocess
  -> vision extraction: backend/app/vision_service.py
  -> comparison engine: backend/app/comparison.py
  -> JSON verification result
```

- API layer: `backend/app/main.py` defines the FastAPI app, static frontend mount, request validation, `/health`, `/verify`, and `/verify/batch`.
- Image preprocessing: `OpenAIVisionService._preprocess` downsizes uploaded images to `MAX_IMAGE_DIMENSION` and re-encodes as JPEG using `JPEG_QUALITY` before sending to the model.
- Vision extraction: `backend/app/vision_service.py` defines the extraction interface, test mock, and `OpenAIVisionService`.
- Comparison engine: `backend/app/comparison.py` handles field normalization, fuzzy matching, unit parsing, exact government warning comparison, and final verdict aggregation.
- `backend/app/models.py`: Pydantic request/response data contracts.
- `frontend/index.html`: unified single-label and batch upload page.
- `backend/scripts/smoke_live.py`: live health, single-label, and batch smoke checks against a deployed service.
- `backend/scripts/benchmark_live.py`: live single-label performance benchmark against a deployed service.

## Tech Stack

- Python `>=3.12,<4.0`
- FastAPI
- Uvicorn
- Pydantic
- Pillow
- RapidFuzz
- OpenAI Python SDK
- `python-multipart`
- Static HTML/CSS/JavaScript frontend
- Vision model: `gpt-5.4-nano`
- Render deployment config in `render.yaml`

## Environment Variables

| Name | Required | Code default | Purpose |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Yes | No default | API key used by `OpenAIVisionService`. |
| `VISION_MODEL` | No | `gpt-5.4-nano` | OpenAI vision-capable model used for extraction. |
| `MAX_IMAGE_DIMENSION` | No | `900` | Longest image side after preprocessing. |
| `JPEG_QUALITY` | No | `80` | JPEG quality used after preprocessing. |
| `MODEL_TIMEOUT_SECONDS` | No | `4` | OpenAI client timeout. |
| `MAX_BATCH_SIZE` | No | `8` | Maximum batch item count accepted by `/verify/batch`. |
| `BATCH_CONCURRENCY` | No | `4` | Maximum concurrent extraction jobs inside a batch request. |
| `ITEM_TIMEOUT_MS` | No | `8000` | Per-item extraction timeout for batch requests. |
| `VERIFY_TIMEOUT_MS` | No | `4500` | Extraction timeout for single-label requests. |

`PORT` is supplied by Render to the start command. The application code does not read `PORT` directly.

Secrets must come from environment variables. Do not commit `.env` or `.env.local`.

## Local Setup

From the repository root:

```powershell
cd backend
python -m pip install --upgrade pip
python -m pip install uv
uv sync
```

`backend/.env.example` is reference documentation only. The application code does not load `.env` files automatically, so set `OPENAI_API_KEY` in your shell or deployment environment before using the real vision service.

## Run Locally

Set the API key for the current PowerShell session:

```powershell
$env:OPENAI_API_KEY = "your-api-key-here"
```

This value lasts only for the current PowerShell session. The real key must never be committed.

```powershell
cd backend
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

- Single-label and batch verification: `http://127.0.0.1:8000/`
- Health check: `http://127.0.0.1:8000/health`

## API Endpoints

- `GET /health`
- `POST /verify`
- `POST /verify/batch`

### POST /verify

`POST /verify` expects `multipart/form-data`:

- `image`: JPEG, JPG, PNG, or WEBP file, under 8 MB
- `brand_name`
- `class_type`
- `producer`
- `country_of_origin`
- `abv`
- `net_contents`
- `government_warning`

PowerShell example:

```powershell
$BASE_URL = "https://ttb-label-verification-lwrd.onrender.com"
$IMAGE_PATH = "C:\labels\label.png"

curl.exe -X POST "$BASE_URL/verify" `
  -F "image=@$IMAGE_PATH;type=image/png" `
  -F "brand_name=Ketel One" `
  -F "class_type=Vodka" `
  -F "producer=Ketel Distillery" `
  -F "country_of_origin=Netherlands" `
  -F "abv=40.0" `
  -F "net_contents=750 mL" `
  -F "government_warning=GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."
```

### POST /verify/batch

`POST /verify/batch` expects `multipart/form-data`:

- repeated `images` fields
- `metadata`: JSON array with one object per image

Each metadata object must include:

- `brand_name`
- `class_type`
- `producer`
- `country_of_origin`
- `abv`
- `net_contents`
- `government_warning`

PowerShell example:

```powershell
$BASE_URL = "https://ttb-label-verification-lwrd.onrender.com"
$IMAGE_1 = "C:\labels\label-1.png"
$IMAGE_2 = "C:\labels\label-2.png"
$METADATA = @'
[
  {
    "brand_name": "Ketel One",
    "class_type": "Vodka",
    "producer": "Ketel Distillery",
    "country_of_origin": "Netherlands",
    "abv": 40.0,
    "net_contents": "750 mL",
    "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."
  },
  {
    "brand_name": "Ketel One",
    "class_type": "Vodka",
    "producer": "Ketel Distillery",
    "country_of_origin": "Netherlands",
    "abv": 40.0,
    "net_contents": "750 mL",
    "government_warning": "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems."
  }
]
'@

curl.exe -X POST "$BASE_URL/verify/batch" `
  -F "images=@$IMAGE_1;type=image/png" `
  -F "images=@$IMAGE_2;type=image/png" `
  -F "metadata=$METADATA"
```

## Expected Success JSON And Error JSON

Successful `POST /verify` response:

```json
{
  "overall_verdict": "APPROVED",
  "field_results": [
    {
      "field": "brand_name",
      "match_type": "fuzzy",
      "expected": "Ketel One",
      "found": "Ketel One",
      "status": "PASS",
      "reason": "Fuzzy match at 100.0%"
    }
  ],
  "timestamp": "2026-07-12T21:55:45.613944Z",
  "latency_ms": 4166.5
}
```

Successful `POST /verify/batch` response:

```json
{
  "items": [
    {
      "overall_verdict": "APPROVED",
      "field_results": [
        {
          "field": "brand_name",
          "match_type": "fuzzy",
          "expected": "Ketel One",
          "found": "Ketel One",
          "status": "PASS",
          "reason": "Fuzzy match at 100.0%"
        }
      ],
      "timestamp": "2026-07-12T21:55:45.613944Z",
      "latency_ms": 4166.5
    }
  ],
  "summary": {
    "passed": 1,
    "needs_review": 0,
    "total": 1
  }
}
```

Validation or request error response:

```json
{
  "error": "Invalid request",
  "message": "Image file is required."
}
```

Vision or server error response:

```json
{
  "error": "Verification failed",
  "message": "Label extraction service is temporarily unavailable. Please try again later."
}
```

Batch item-level problems can return HTTP 200 with an item marked `NEEDS_REVIEW` and a failing `field_results` entry.

## Comparison Rules

- `government_warning`: both extracted and submitted text are stripped and internal whitespace runs are collapsed to single spaces, then compared exactly with case sensitivity preserved. The comparison does not lowercase, canonicalize, paraphrase, or substitute a warning template.
- `brand_name`, `class_type`, `producer`: `None` is treated as an empty string, otherwise each value is stripped of leading/trailing whitespace, lowercased, and compared with RapidFuzz `token_sort_ratio`; the pass threshold is 90.
- `country_of_origin`: exact match after uppercase normalization, or synonym-aware match for currently mapped values such as `USA`, `US`, `United States`, `GB`, `UK`, `United Kingdom`, `NL`, `Netherlands`, `FR`, `France`, `DE`, and `Germany`.
- `abv`: parses numeric ABV values, percent values, and proof values by dividing proof by 2; comparison tolerance is plus or minus 0.1 percentage points.
- `net_contents`: parses `mL`, `L`, `FL OZ`, `FLOZ`, and `OZ` to milliliters and allows plus or minus 1 mL.
- Missing or unreadable extracted values fail the relevant field and produce `NEEDS_REVIEW`.

## Performance

Verified live benchmark results for the deployed service:

- **Script:** `backend/scripts/benchmark_live.py`
- **Model:** `gpt-5.4-nano`
- **Endpoint:** `/verify`
- **Measurement date:** July 14, 2026
- **Benchmark client:** local Windows laptop using PowerShell
- **Requested runs:** 20
- **Successful runs:** 20
- **Failed runs:** 0
- **Timed-out runs:** 0
- **First-request latency:** 4,200.1 ms
- **Percentile method:** nearest-rank over successful requests
- **p50 latency:** 3,460.8 ms
- **p95 latency:** 4,200.1 ms
- **Successful requests at or below 5 seconds:** 19/20
- **All successful requests met the 5-second target:** No
- **Target:** single-label result under 5,000 ms

The p50 and p95 were below 5 seconds, but not every request met the target. The first-request latency is a first-request measurement only; it does not prove a cold start.

Run the benchmark from `backend` with a real local image and a matching metadata JSON object:

```powershell
uv run python scripts\benchmark_live.py --base-url https://ttb-label-verification-lwrd.onrender.com --image "C:\labels\label.png" --metadata-file "C:\labels\metadata.json" --runs 20
```

## Running Tests

```powershell
cd backend
uv run python -m pytest
```

The automated tests use `MockVisionService` or fake OpenAI clients. They do not require a real API key.

## Live Smoke Check

Health check:

```powershell
curl.exe https://ttb-label-verification-lwrd.onrender.com/health
```

Expected output shape:

```json
{
  "status": "ok",
  "ts": "<current UTC timestamp>"
}
```

End-to-end smoke check with a real local image and matching metadata JSON:

```powershell
cd backend
uv run python scripts\smoke_live.py --base-url https://ttb-label-verification-lwrd.onrender.com --image "C:\labels\label.png" --metadata-file "C:\labels\metadata.json"
```

Required arguments:

- `--base-url`: deployed API base URL.
- `--image`: real local JPEG, PNG, or WEBP label image.
- `--metadata-file`: JSON object with exactly the seven submitted label fields.

The metadata JSON must contain exactly:

- `brand_name`
- `class_type`
- `producer`
- `country_of_origin`
- `abv`
- `net_contents`
- `government_warning`

The chosen image must match the metadata submitted in the JSON file. The smoke script checks `GET /health`, `POST /verify`, and `POST /verify/batch`. For the single `/verify` request, it also requires a valid verdict, all seven field results exactly once, and `latency_ms` strictly under 5,000 ms.

The smoke test is a single-request deployment gate and fails when that request reports `latency_ms >= 5000`. The benchmark script remains a multi-run reporting tool: it reports successful requests over 5 seconds instead of rejecting the whole benchmark solely for those latencies.

## Deployment

`render.yaml` defines the Render web service:

- build command: `cd backend && pip install --upgrade pip && pip install uv && uv sync --frozen`
- start command: `cd backend && uv run --frozen python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- health check path: `/health`
- environment variables: `OPENAI_API_KEY` and `VISION_MODEL=gpt-5.4-nano`

## Assumptions

- Uploaded files are label photos in JPEG, JPG, PNG, or WEBP format.
- Uploaded files are under 8 MB.
- Operators provide the seven expected fields for every label.
- Batch metadata order matches image order.
- Vision extraction may be incomplete when the image is blurry, cropped, low contrast, or otherwise hard to read.
- API access is available through `OPENAI_API_KEY` in the runtime environment.

## Limitations

- No database or persistent storage.
- No user accounts or authentication.
- No saved audit history.
- No retry queue for failed vision extraction.
- Performance depends on image size, image quality, model latency, host cold starts, and network conditions.
- Batch requests are capped at 8 items by default.
- The implemented batch cap is 8 items, not the broader brief's 300-item target.
- Live benchmark p50 and p95 were below 5 seconds, but 1 of 20 successful requests exceeded 5 seconds.

## Tradeoffs

- The app prioritizes stateless proof-of-concept simplicity over persistence, audit trails, and user management.
- Batch upload is supported, but capped at 8 items to keep latency and resource use bounded; this proof-of-concept intentionally does not implement the 300-item target from the broader brief.
- There is no `USE_MOCK_VISION` environment switch; tests inject `MockVisionService` through FastAPI dependency overrides.
- Image preprocessing reduces payload size and latency, but may discard some visual detail.
- The single-label path uses a 4,500 ms extraction timeout to keep the API close to the under-5-second requirement; slower extraction can return HTTP 504.

## Secret Handling

- Store `OPENAI_API_KEY` only in environment variables or local ignored `.env` files.
- Do not hardcode API keys in code, docs, scripts, tests, or deployment config.
- Do not commit `.env` or `.env.local`.
- `render.yaml` marks `OPENAI_API_KEY` with `sync: false`.

## Approach / Tools

- Working cadence: PLAN → REVIEW → EXECUTE → TEST → COMMIT → PUSH.
- Codex-assisted work: plans, proposed edits, local tests, validation commands, and documentation drafts.
- Human work: scope approval, diff review, live deployment verification, real smoke checks, benchmark execution, measured results, commits, and pushes.
- Example of human correction: in this documentation pass, the human corrected the stale AI assumption that the benchmark used a warm-up or hardcoded metadata and required the verified benchmark results instead.
- Local tests are run before commits when code or contract-sensitive documentation changes.
- Live smoke checks and benchmarking are run by the human against the deployed service with a real matching label image and metadata file; recorded live facts are preserved rather than invented.
- The developer made a reviewed decision to align the application default, Render config, and production deployment on `gpt-5.4-nano`.
- Scope stays limited to the current approved phase.
