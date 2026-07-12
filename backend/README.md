# Backend Service

This directory contains the FastAPI backend, static frontend pages, tests, and live benchmark tooling for the TTB Label Verification proof-of-concept. The root `README.md` is the canonical project documentation.

## Setup

```powershell
cd backend
python -m pip install --upgrade pip
python -m pip install uv
uv sync
```

`backend/.env.example` is reference documentation only. The application code does not load `.env` files automatically, so set `OPENAI_API_KEY` in your shell or deployment environment before running against the real vision service.

## Run

Set the API key for the current PowerShell session:

```powershell
$env:OPENAI_API_KEY = "your-api-key-here"
```

This value lasts only for the current PowerShell session. The real key must never be committed.

```powershell
cd backend
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`, `http://127.0.0.1:8000/batch.html`, or `http://127.0.0.1:8000/health`.

## Environment

Common backend variables:

- `OPENAI_API_KEY`: required for real extraction.
- `VISION_MODEL`: defaults to `gpt-4.1-nano`.
- `MAX_BATCH_SIZE`: defaults to `8`.
- `BATCH_CONCURRENCY`: defaults to `4`.
- `ITEM_TIMEOUT_MS`: defaults to `3000`.
- `VERIFY_TIMEOUT_MS`: defaults to `4500`.
- `MAX_IMAGE_DIMENSION`: defaults to `900`.
- `JPEG_QUALITY`: defaults to `80`.
- `MODEL_TIMEOUT_SECONDS`: defaults to `4`.

Render supplies `PORT` to the start command; the application code does not read it directly.

## Test

```powershell
cd backend
uv run pytest
```

Tests use `MockVisionService` or fake OpenAI clients and do not require a real API key.

## Benchmark

Run the committed live single-label benchmark against a deployed service with a real local image:

```powershell
cd backend
uv run python scripts\benchmark_live.py --base-url https://ttb-label-verification-lwrd.onrender.com --image "C:\labels\label.png" --runs 20
```

`scripts\benchmark_live.py` currently sends hardcoded Hennessy metadata, so the image must be the matching Hennessy label image.

Latest recorded live result:

- UTC measurement time: `2026-07-12T23:08:58.749129+00:00`
- host: `https://ttb-label-verification-lwrd.onrender.com`
- endpoint: `POST /verify`
- measured runs: 20
- successful runs: 20
- failed runs: 0
- excluded warm-up requests: 1
- percentile method: nearest-rank
- p50: 3,821.0 ms, meets the 5,000 ms target
- p95: 5,157.4 ms, does not meet the 5,000 ms target

The script sends one warm-up request, then reports p50 and p95 latency over measured requests. Exact cold-start latency was not recorded because the warm-up request was excluded.

## Smoke Checks

Health:

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

Single-label end-to-end check:

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
