import logging
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import asyncio
import json

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.comparison import verify_label
from app.models import ApplicationData, VerificationResult
from app.vision_service import OpenAIVisionService, VisionService
from app.models import BatchItemResult, BatchResponse

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_BATCH_SIZE = int(__import__("os").environ.get("MAX_BATCH_SIZE", 8))
BATCH_CONCURRENCY = int(__import__("os").environ.get("BATCH_CONCURRENCY", 4))
ITEM_TIMEOUT_MS = int(__import__("os").environ.get("ITEM_TIMEOUT_MS", 3000))
VERIFY_TIMEOUT_MS = int(__import__("os").environ.get("VERIFY_TIMEOUT_MS", 4500))

app = FastAPI(title="ttb-label-verification")


class VerificationResponse(VerificationResult):
    latency_ms: float


def get_vision_service() -> VisionService:
    return OpenAIVisionService()


def _format_validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid request."

    first = errors[0]
    loc = first.get("loc", [])
    msg = first.get("msg", "Invalid value.")
    field = loc[-1] if loc else None

    if field == "image":
        return "Image file is required."

    if field == "abv":
        return "abv must be a number between 0 and 100."

    if "ensure this value has at least 1 characters" in msg.lower():
        return f"{field or 'Field'} must not be empty."

    if "field required" in msg.lower():
        return f"{field or 'Field'} is required."

    return msg.capitalize()


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "Invalid request", "message": _format_validation_message(exc)},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Invalid request."
    error_type = "Invalid request" if 400 <= exc.status_code < 500 else "Verification failed"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error_type, "message": message},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception during verification")
    return JSONResponse(
        status_code=500,
        content={
            "error": "Verification failed",
            "message": "An unexpected error occurred while verifying the label.",
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/verify", response_model=VerificationResponse)
async def verify(
    image: UploadFile = File(...),
    brand_name: str = Form(...),
    class_type: str = Form(...),
    producer: str = Form(...),
    country_of_origin: str = Form(...),
    abv: float = Form(...),
    net_contents: str = Form(...),
    government_warning: str = Form(...),
    vision_service: VisionService = Depends(get_vision_service),
):
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload JPEG, PNG, or WEBP.",
        )

    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Image file is required.")

    if len(contents) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Image file must be smaller than {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
        )

    start = perf_counter()
    submitted = ApplicationData(
        brand_name=brand_name,
        class_type=class_type,
        producer=producer,
        country_of_origin=country_of_origin,
        abv=abv,
        net_contents=net_contents,
        government_warning=government_warning,
    )

    try:
        # Run extraction in thread if blocking and enforce a timeout for live requests
        extracted = await asyncio.wait_for(
            asyncio.to_thread(vision_service.extract, contents),
            VERIFY_TIMEOUT_MS / 1000,
        )
    except asyncio.TimeoutError:
        logger.exception("Vision extraction timed out")
        raise HTTPException(
            status_code=504,
            detail="Label extraction timed out. Please try a smaller, clearer image.",
        )
    except Exception:
        logger.exception("Vision extraction failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to extract label text from the uploaded image. Please try another image.",
        )

    result = verify_label(extracted, submitted)
    latency_ms = round((perf_counter() - start) * 1000, 3)

    logger.info(
        "Verify request completed in %.3fms with verdict=%s",
        latency_ms,
        result.overall_verdict,
    )

    payload = result.model_dump()
    payload["latency_ms"] = latency_ms
    return payload


@app.post("/verify/batch", response_model=BatchResponse)
async def verify_batch(
    images: list[UploadFile] | None = File(None),
    metadata: str = Form(...),
    vision_service: VisionService = Depends(get_vision_service),
):
    # Validate metadata JSON
    try:
        meta_list = json.loads(metadata)
        if not isinstance(meta_list, list):
            raise ValueError("metadata must be a JSON array")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid metadata: {e}")

    images = images or []

    total_items = max(len(images), len(meta_list))
    if total_items == 0:
        raise HTTPException(status_code=400, detail="No images or metadata provided.")

    if total_items > MAX_BATCH_SIZE:
        raise HTTPException(status_code=400, detail=f"Batch size exceeds MAX_BATCH_SIZE ({MAX_BATCH_SIZE}).")

    # Prepare pairs by index
    pairs = []
    for i in range(total_items):
        img = images[i] if i < len(images) else None
        meta = meta_list[i] if i < len(meta_list) else None
        pairs.append((i, img, meta))

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def process_item(index: int, upload: UploadFile | None, meta: dict | None):
        filename = upload.filename if upload is not None else ""
        start = perf_counter()
        errors: list[str] = []
        verification = None
        match = "error"
        confidence = None

        # Validate upload
        if upload is None:
            errors.append("missing image")
            duration = round((perf_counter() - start) * 1000, 3)
            return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

        if upload.content_type not in ALLOWED_IMAGE_TYPES:
            errors.append("unsupported file type")
            duration = round((perf_counter() - start) * 1000, 3)
            return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

        contents = await upload.read()
        if not contents:
            errors.append("empty file")
            duration = round((perf_counter() - start) * 1000, 3)
            return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            errors.append("file too large")
            duration = round((perf_counter() - start) * 1000, 3)
            return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

        # Validate metadata presence and fields
        if not isinstance(meta, dict):
            errors.append("missing metadata for item")
            duration = round((perf_counter() - start) * 1000, 3)
            return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

        required_fields = [
            "brand_name",
            "class_type",
            "producer",
            "country_of_origin",
            "abv",
            "net_contents",
            "government_warning",
        ]
        for f in required_fields:
            if f not in meta:
                errors.append(f"metadata missing field: {f}")

        if errors:
            duration = round((perf_counter() - start) * 1000, 3)
            return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

        # Run extraction and verification with concurrency limit and timeout
        async with semaphore:
            try:
                extracted = await asyncio.wait_for(asyncio.to_thread(vision_service.extract, contents), ITEM_TIMEOUT_MS / 1000)
            except asyncio.TimeoutError:
                errors.append("extraction timeout")
                duration = round((perf_counter() - start) * 1000, 3)
                return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)
            except Exception as e:
                logger.exception("Vision extraction failed for batch item %s", index)
                errors.append("extraction failed")
                duration = round((perf_counter() - start) * 1000, 3)
                return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

            # Build ApplicationData from meta
            try:
                submitted = ApplicationData(
                    brand_name=meta["brand_name"],
                    class_type=meta["class_type"],
                    producer=meta["producer"],
                    country_of_origin=meta["country_of_origin"],
                    abv=float(meta["abv"]),
                    net_contents=meta["net_contents"],
                    government_warning=meta["government_warning"],
                )
            except ValidationError as exc:
                errors.extend(
                    f"invalid metadata {err.get('loc', [''])[-1]}: {err.get('msg', 'invalid value')}"
                    for err in exc.errors()
                )
                duration = round((perf_counter() - start) * 1000, 3)
                return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)
            except Exception:
                duration = round((perf_counter() - start) * 1000, 3)
                return BatchItemResult(index=index, filename=filename, verification=None, match=match, confidence=confidence, errors=errors, duration_ms=duration)

            result = verify_label(extracted, submitted)
            verification = result
            match = "passed" if result.overall_verdict == "APPROVED" else "needs-review"
            duration = round((perf_counter() - start) * 1000, 3)
            return BatchItemResult(index=index, filename=filename, verification=verification, match=match, confidence=confidence, errors=errors or None, duration_ms=duration)

    # Spawn tasks
    tasks = [process_item(i, img, meta) for (i, img, meta) in pairs]
    results = await asyncio.gather(*tasks)

    passed = sum(1 for r in results if r.match == "passed")
    needs_review = sum(1 for r in results if r.match == "needs-review")
    errors_count = sum(1 for r in results if r.match == "error")

    return BatchResponse(total=len(results), passed=passed, needs_review=needs_review, errors=errors_count, results=results)


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
