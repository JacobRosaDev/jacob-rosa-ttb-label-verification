# TTB Label Verification Proof-of-Concept

A stateless FastAPI backend with a static HTML/JS frontend for verifying TTB label fields from images.

## Project Purpose

This project extracts text from a label image, compares it against user-submitted field values, and verifies whether the label matches expected data.

- **Government warning** is validated as an exact case-sensitive match after whitespace collapse.
- **All other fields** are verified with fuzzy/normalized comparison or tolerant numeric parsing.
- **Batch upload** is supported via a dedicated frontend page.
- No database is used; the service is stateless and in-memory.

## Live Demo

- **Live app URL:** https://ttb-label-verification-lwrd.onrender.com
- **Backend base URL:** https://ttb-label-verification-lwrd.onrender.com
- **Health URL:** https://ttb-label-verification-lwrd.onrender.com/health
- **Last verified:** July 12, 2026
- **Deployed vision model:** `gpt-4.1-nano`

## Verified Performance

Final live benchmark results:

- **Measurement timestamp:** `2026-07-12T21:55:45.613944+00:00`
- **Tested endpoint:** `POST https://ttb-label-verification-lwrd.onrender.com/verify`
- **Successful measured sample size:** 20
- **Excluded warm-up requests:** 1
- **Failed measured requests:** 0
- **Percentile method:** nearest-rank
- **p50 latency:** 4,166.5 ms
- **p95 latency:** 5,683.6 ms
- **Target:** under 5,000 ms
- **p50 meets target:** Yes
- **p95 meets target:** No
- **Benchmark script:** `backend/scripts/benchmark_live.py`

The p50 latency meets the five-second target. The p95 latency currently exceeds the target by 683.6 ms.

Reproducible benchmark command:

```powershell
uv run python scripts\benchmark_live.py --base-url https://ttb-label-verification-lwrd.onrender.com --image "<path-to-real-label-image>" --runs 20
```

## Local Setup

### Prerequisites

- Python 3.12+
- `pip`
- `uv` package manager (installed via `pip install uv`)

### Installation

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install uv
uv sync
```

### Environment Variables

Copy the example env file and set your API key:

```powershell
cd backend
copy .env.example .env
```

Then edit `backend/.env` to add your real API key:

```ini
OPENAI_API_KEY=your-real-key-here
```

**Security:**

- Do not commit `.env` or `.env.local`.
- `.env.example` may contain placeholder names only.
- API keys must live in environment variables only.

## Running Locally

Start the backend service:

```powershell
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open the frontend pages in your browser:

- Single-label verification: `http://127.0.0.1:8000/`
- Batch verification: `http://127.0.0.1:8000/batch.html`

## API Endpoints

The backend exposes these routes:

- `GET /health` — health check
- `POST /verify` — single image verification
- `POST /verify/batch` — batch verification

### Single-label verification

The frontend submits a multipart/form-data request to `/verify` with:

- `image` file
- `brand_name`
- `class_type`
- `producer`
- `country_of_origin`
- `abv`
- `net_contents`
- `government_warning`

### Batch verification

The batch frontend submits a multipart/form-data request to `/verify/batch` with:

- one or more `images`
- `metadata` JSON string containing an array of label field objects

Each metadata object must include the same seven required fields.

## Frontend Pages

- `backend/frontend/index.html` — single label upload and verification
- `backend/frontend/batch.html` — multiple label upload with per-item metadata

## Approach

1. Upload the label image(s).
2. The backend sends the image to a vision service for structured text extraction.
3. Extracted fields are compared against submitted data.
4. Results are returned, including per-field pass/fail details and latency.

## Verification Rules

- `government_warning` requires an exact text match after whitespace normalization.
- `brand_name`, `class_type`, and `producer` use fuzzy text matching.
- `country_of_origin` accepts synonyms like `USA` / `United States` / `US`.
- `abv` is parsed and compared within ±0.1%.
- `net_contents` is normalized to milliliters and compared within ±2%.

## Tools and Dependencies

- FastAPI
- Uvicorn
- Pydantic
- Pillow
- RapidFuzz
- OpenAI Python SDK
- python-multipart

## Assumptions

- Uploaded images are valid label photos (JPEG/PNG/WEBP).
- Vision API access is available via `OPENAI_API_KEY`.
- The service is stateless and does not persist data.

## Limitations

- No database or persistent storage.
- No user authentication.
- Results are not stored across requests.
- Performance depends on the vision model and network.
- Poor image quality may produce incomplete or failed extraction.

## Deployment

If deploying to Render or Railway, use the `backend` directory as the root and run:

```bash
pip install --upgrade pip && pip install uv && uv sync
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Security Notes

- `.env` and `.env.local` must never be committed.
- `.env.example` is safe and should contain only placeholder values.
- All secret keys must come from environment variables only.
