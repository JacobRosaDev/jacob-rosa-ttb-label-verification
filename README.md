# TTB Label Verification Proof-of-Concept

A stateless FastAPI service with static HTML pages for checking whether distilled spirits label images match seven expected TTB label fields.

## Live Demo

- **Frontend URL:** https://ttb-label-verification-lwrd.onrender.com
- **Backend base URL:** https://ttb-label-verification-lwrd.onrender.com
- **Health URL:** https://ttb-label-verification-lwrd.onrender.com/health
- **Last verified:** July 12, 2026
- **Production vision model:** `gpt-4.1-nano`

## What The App Does

The app accepts one label image, or a batch of label images, plus expected application data. It sends each image to a vision extraction service, receives structured label text, and compares the extracted values against the submitted values.

- Government warning text is an exact, case-sensitive match after whitespace collapse.
- Brand name, class/type, and producer use fuzzy normalized text matching.
- Country of origin accepts known country synonyms.
- ABV supports percent values and proof values; net contents use unit-normalized comparison.
- The service uses no database and does not persist uploaded images or results.

## Architecture

- `backend/app/main.py`: FastAPI app, static frontend mount, request validation, `/health`, `/verify`, and `/verify/batch`.
- `backend/app/vision_service.py`: vision extraction interface, test mock, and `OpenAIVisionService`.
- `OpenAIVisionService._preprocess`: downsizes uploaded images to `MAX_IMAGE_DIMENSION` and re-encodes as JPEG using `JPEG_QUALITY` before sending to the model.
- `backend/app/comparison.py`: normalization, fuzzy matching, unit parsing, exact government warning comparison, and final verdict aggregation.
- `backend/app/models.py`: Pydantic request/response data contracts.
- `backend/frontend/index.html`: single-label upload page.
- `backend/frontend/batch.html`: batch upload page.
- `backend/scripts/benchmark_live.py`: live single-label performance benchmark against a deployed service.

## Tech Stack

- Python 3.12+
- FastAPI
- Uvicorn
- Pydantic
- Pillow
- RapidFuzz
- OpenAI Python SDK
- `python-multipart`
- Static HTML/CSS/JavaScript frontend
- Vision model: `gpt-4.1-nano`
- Render deployment config in `render.yaml`

## Environment Variables

| Name | Required | Code default | Purpose |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Yes | No default | API key used by `OpenAIVisionService`. |
| `VISION_MODEL` | No | `gpt-4.1-nano` | OpenAI vision-capable model used for extraction. |
| `MAX_IMAGE_DIMENSION` | No | `900` | Longest image side after preprocessing. |
| `JPEG_QUALITY` | No | `80` | JPEG quality used after preprocessing. |
| `MODEL_TIMEOUT_SECONDS` | No | `4` | OpenAI client timeout. |
| `MAX_BATCH_SIZE` | No | `8` | Maximum batch item count accepted by `/verify/batch`. |
| `BATCH_CONCURRENCY` | No | `4` | Maximum concurrent extraction jobs inside a batch request. |
| `ITEM_TIMEOUT_MS` | No | `3000` | Per-item extraction timeout for batch requests. |
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

- Single-label verification: `http://127.0.0.1:8000/`
- Batch verification: `http://127.0.0.1:8000/batch.html`
- Health check: `http://127.0.0.1:8000/health`

## API Endpoints

- `GET /health`
- `POST /verify`
- `POST /verify/batch`

### Single-Label Request

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

### Batch Request

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

## Response Shapes

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
- `brand_name`, `class_type`, `producer`: normalized with punctuation removed and whitespace collapsed, then compared with RapidFuzz `token_sort_ratio`; the pass threshold is 90.
- `country_of_origin`: synonym-aware match, including values such as `USA`, `US`, and `United States`.
- `abv`: parses numeric ABV values, percent values, and proof values by dividing proof by 2; comparison tolerance is plus or minus 0.1 percentage points.
- `net_contents`: parses supported units to milliliters and allows plus or minus 1 mL.
- Missing or unreadable extracted values fail the relevant field and produce `NEEDS_REVIEW`.

## Performance

Final live benchmark results already recorded for the deployed service:

- **Measurement timestamp:** `2026-07-12T23:08:58.749129+00:00`
- **Host:** `https://ttb-label-verification-lwrd.onrender.com`
- **Tested endpoint:** `POST /verify`
- **Measured runs:** 20
- **Successful measured runs:** 20
- **Excluded cold-start/warm-up requests:** 1
- **Failed measured requests:** 0
- **Percentile method:** nearest-rank
- **p50 latency:** 3,821.0 ms
- **p95 latency:** 5,157.4 ms
- **Target:** single-label result under 5,000 ms
- **p50 vs target:** Meets target
- **p95 vs target:** Does not meet target
- **Benchmark script:** `backend/scripts/benchmark_live.py`

The benchmark script sends one warm-up request before the measured runs. The exact cold-start latency was not recorded because the warm-up request was excluded. These results do not claim that all requests complete under 5 seconds; the recorded p95 is above the target.

`backend/scripts/benchmark_live.py` currently sends hardcoded Hennessy metadata: `HENNESSY COGNAC`, `COGNAC`, `JAS HENNESSY & CO.`, `FRANCE`, `40`, `200 ml`, and the matching warning text. Run it from `backend` with the matching Hennessy label image:

```powershell
uv run python scripts\benchmark_live.py --base-url https://ttb-label-verification-lwrd.onrender.com --image "C:\labels\label.png" --runs 20
```

## Running Tests

```powershell
cd backend
uv run pytest
```

The automated tests use `MockVisionService` or fake OpenAI clients. They do not require a real API key.

## Live Smoke Checks

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

End-to-end single-label check with a real local image:

The chosen image must match the metadata submitted in the form fields.

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

## Deployment

`render.yaml` defines the Render web service:

- `rootDir`: `backend`
- build command: `pip install --upgrade pip && pip install uv && uv sync --frozen`
- start command: `uv run --frozen python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- health check path: `/health`
- environment variables: `OPENAI_API_KEY` and `VISION_MODEL=gpt-4.1-nano`

## Assumptions

- Uploaded files are label photos in JPEG, JPG, PNG, or WEBP format.
- Operators provide the seven expected fields for every label.
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

## Tradeoffs

- The app prioritizes stateless proof-of-concept simplicity over persistence, audit trails, and user management.
- Batch upload is supported, but capped at 8 items to keep latency and resource use bounded; this proof-of-concept intentionally does not implement the 300-item target from the broader brief.
- There is no `USE_MOCK_VISION` environment switch; tests inject `MockVisionService` through FastAPI dependency overrides.
- Image preprocessing reduces payload size and latency, but may discard some visual detail.
- p50 live latency met the 5-second target in the recorded benchmark; p95 did not.

## Secret Handling

- Store `OPENAI_API_KEY` only in environment variables or local ignored `.env` files.
- Do not hardcode API keys in code, docs, scripts, tests, or deployment config.
- Do not commit `.env` or `.env.local`.
- `render.yaml` marks `OPENAI_API_KEY` with `sync: false`.

## Approach And Tools

- Codex is used to draft plans, documentation, code changes, and verification commands.
- Working cadence: PLAN -> REVIEW -> EXECUTE -> TEST -> COMMIT -> PUSH.
- The developer reviews diffs, corrects assumptions, and approves scope before commits.
- Tests are run before commits when code or contract-sensitive documentation changes.
- Live benchmarking is run by the developer against the deployed service with a real matching label image; recorded benchmark facts are preserved rather than invented.
- The developer made a reviewed decision to align the application default, Render config, and production deployment on `gpt-4.1-nano`.
- Scope stays limited to the current approved phase.
