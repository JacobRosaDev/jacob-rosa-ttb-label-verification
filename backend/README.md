# Backend Service

This directory contains the FastAPI backend, tests, and live smoke/benchmark tooling for the TTB Label Verification proof-of-concept. The static frontend lives in the repository-level `frontend/` directory.

The root `README.md` is the canonical project documentation. Use this file as a short backend-specific quick reference.

## Setup

```powershell
cd backend
python -m pip install --upgrade pip
python -m pip install uv
uv sync
```

The backend declares Python `>=3.12,<4.0` in `pyproject.toml`.

## Run

Set `OPENAI_API_KEY` in your shell or deployment environment before running against the real vision service. The application code does not load `.env` files automatically.

```powershell
$env:OPENAI_API_KEY = "your-api-key-here"
uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` for single-label or batch verification, or `http://127.0.0.1:8000/health`.

## Backend Variables

- `OPENAI_API_KEY`: required for real extraction; no code default.
- `VISION_MODEL`: defaults to `gpt-4.1-nano`.
- `MAX_IMAGE_DIMENSION`: defaults to `900`.
- `JPEG_QUALITY`: defaults to `80`.
- `MODEL_TIMEOUT_SECONDS`: defaults to `4`.
- `MAX_BATCH_SIZE`: defaults to `8`.
- `BATCH_CONCURRENCY`: defaults to `4`.
- `ITEM_TIMEOUT_MS`: defaults to `3000`.
- `VERIFY_TIMEOUT_MS`: defaults to `4500`.

Render supplies `PORT` to the start command; the application code does not read it directly.

## Test

```powershell
uv run python -m pytest
```

Tests use `MockVisionService` or fake OpenAI clients and do not require a real API key.

## Live Scripts

Run live smoke checks only when you have a real local label image and a matching metadata JSON object:

```powershell
uv run python scripts\smoke_live.py --base-url https://ttb-label-verification-lwrd.onrender.com --image "C:\labels\label.png" --metadata-file "C:\labels\metadata.json"
```

Required smoke arguments are `--base-url`, `--image`, and `--metadata-file`; `--timeout-seconds` is optional. The metadata JSON must contain exactly `brand_name`, `class_type`, `producer`, `country_of_origin`, `abv`, `net_contents`, and `government_warning`.

The smoke script checks `/health`, `/verify`, and `/verify/batch`. The single `/verify` smoke check fails unless the response includes all seven field results exactly once and reports `latency_ms` strictly under 5,000 ms.

Run the live single-label benchmark with the same kind of matching image and metadata:

```powershell
uv run python scripts\benchmark_live.py --base-url https://ttb-label-verification-lwrd.onrender.com --image "C:\labels\label.png" --metadata-file "C:\labels\metadata.json" --runs 20
```

The benchmark is different from smoke: it reports multi-run latency results, and successful requests over 5 seconds may continue to be reported rather than rejected solely for that latency. Latest verified live benchmark facts are recorded in the root `README.md`.
