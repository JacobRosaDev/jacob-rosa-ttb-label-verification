import logging
from functools import lru_cache
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
from app.models import ApplicationData, BatchResult, FieldResult, VerificationResult
from app.vision_service import (
    MockVisionService,
    OpenAIVisionService,
    VisionAuthError,
    VisionInvalidResponseError,
    VisionModelValidationError,
    VisionService,
    VisionTimeoutError,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
UNSUPPORTED_IMAGE_TYPE_MESSAGE = "Unsupported file type. Please upload JPEG, PNG, or WEBP."
MAX_BATCH_SIZE = int(__import__("os").environ.get("MAX_BATCH_SIZE", 8))
BATCH_CONCURRENCY = int(__import__("os").environ.get("BATCH_CONCURRENCY", 4))
ITEM_TIMEOUT_MS = int(__import__("os").environ.get("ITEM_TIMEOUT_MS", 3000))
VERIFY_TIMEOUT_MS = int(__import__("os").environ.get("VERIFY_TIMEOUT_MS", 4500))

app = FastAPI(title="ttb-label-verification")


@lru_cache(maxsize=1)
def get_vision_service() -> VisionService:
    return OpenAIVisionService()


def _get_startup_vision_service() -> VisionService:
    override = app.dependency_overrides.get(get_vision_service)
    if override is not None:
        return override()
    return get_vision_service()


def _is_allowed_image_type(content_type: str | None) -> bool:
    return content_type in ALLOWED_IMAGE_TYPES


@app.on_event("startup")
def validate_startup_vision_model() -> None:
    vision_service = _get_startup_vision_service()

    if isinstance(vision_service, MockVisionService):
        return

    if isinstance(vision_service, OpenAIVisionService):
        logger.info("Configured VISION_MODEL=%s", vision_service.VISION_MODEL)
        try:
            vision_service.validate_model_available()
        except VisionModelValidationError:
            raise
        except Exception:
            raise VisionModelValidationError(
                f"Vision model '{vision_service.VISION_MODEL}' is unavailable or could not be validated."
            ) from None


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


@app.post("/verify", response_model=VerificationResult)
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
    if not _is_allowed_image_type(image.content_type):
        raise HTTPException(
            status_code=400,
            detail=UNSUPPORTED_IMAGE_TYPE_MESSAGE,
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
    except (asyncio.TimeoutError, VisionTimeoutError):
        logger.warning("Vision extraction timed out")
        raise HTTPException(
            status_code=504,
            detail="Label extraction timed out. Please try a smaller, clearer image.",
        )
    except VisionAuthError:
        logger.warning("Vision extraction authentication failed")
        raise HTTPException(
            status_code=502,
            detail="Label extraction service is temporarily unavailable. Please try again later.",
        )
    except VisionInvalidResponseError:
        logger.warning("Vision extraction returned invalid output")
        raise HTTPException(
            status_code=502,
            detail="The image could not be read by the extraction service. Please try another image.",
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

    return result.model_copy(update={"latency_ms": latency_ms})


def _batch_failure_result(
    message: str,
    latency_ms: float,
    *,
    field: str = "batch_item",
    expected: str = "processable batch item",
    unreadable_image: bool = False,
) -> VerificationResult:
    found = ""
    reason = message
    if unreadable_image:
        field = "raw_text"
        expected = "readable label photo"
        found = None

    return VerificationResult(
        overall_verdict="NEEDS_REVIEW",
        field_results=[
            FieldResult(
                field=field,
                match_type="exact",
                expected=expected,
                found=found,
                status="FAIL",
                reason=reason,
            )
        ],
        timestamp=datetime.now(timezone.utc),
        latency_ms=latency_ms,
    )


@app.post("/verify/batch", response_model=BatchResult)
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

    async def process_item(index: int, upload: UploadFile | None, meta: dict | None) -> VerificationResult:
        start = perf_counter()

        # Validate upload
        if upload is None:
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result("Missing image.", duration)

        if not _is_allowed_image_type(upload.content_type):
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result(UNSUPPORTED_IMAGE_TYPE_MESSAGE, duration)

        contents = await upload.read()
        if not contents:
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result("Image file is empty.", duration, unreadable_image=True)

        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result("Image file is too large.", duration)

        # Validate metadata presence and fields
        if not isinstance(meta, dict):
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result("Missing metadata for item.", duration)

        required_fields = [
            "brand_name",
            "class_type",
            "producer",
            "country_of_origin",
            "abv",
            "net_contents",
            "government_warning",
        ]
        missing_fields = []
        for f in required_fields:
            if f not in meta:
                missing_fields.append(f)

        if missing_fields:
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result(
                f"Metadata missing fields: {', '.join(missing_fields)}.",
                duration,
            )

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
            messages = [
                f"{err.get('loc', [''])[-1]}: {err.get('msg', 'invalid value')}"
                for err in exc.errors()
            ]
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result(
                f"Invalid metadata: {'; '.join(messages)}.",
                duration,
            )
        except Exception:
            duration = round((perf_counter() - start) * 1000, 3)
            return _batch_failure_result("Invalid metadata.", duration)

        # Run extraction and verification with concurrency limit and timeout
        async with semaphore:
            try:
                extracted = await asyncio.wait_for(asyncio.to_thread(vision_service.extract, contents), ITEM_TIMEOUT_MS / 1000)
            except (asyncio.TimeoutError, VisionTimeoutError):
                duration = round((perf_counter() - start) * 1000, 3)
                return _batch_failure_result(
                    "The photo could not be read before the extraction timeout.",
                    duration,
                    unreadable_image=True,
                )
            except VisionInvalidResponseError:
                duration = round((perf_counter() - start) * 1000, 3)
                return _batch_failure_result(
                    "The photo could not be read by the extraction service.",
                    duration,
                    unreadable_image=True,
                )
            except VisionAuthError:
                duration = round((perf_counter() - start) * 1000, 3)
                return _batch_failure_result(
                    "Label extraction service is temporarily unavailable.",
                    duration,
                )
            except Exception:
                logger.exception("Vision extraction failed for batch item %s", index)
                duration = round((perf_counter() - start) * 1000, 3)
                return _batch_failure_result(
                    "The photo could not be read by the extraction service.",
                    duration,
                    unreadable_image=True,
                )

            result = verify_label(extracted, submitted)
            duration = round((perf_counter() - start) * 1000, 3)
            return result.model_copy(update={"latency_ms": duration})

    # Spawn tasks
    tasks = [process_item(i, img, meta) for (i, img, meta) in pairs]
    items = await asyncio.gather(*tasks)

    passed = sum(1 for item in items if item.overall_verdict == "APPROVED")
    needs_review = sum(1 for item in items if item.overall_verdict != "APPROVED")

    return BatchResult(
        items=items,
        summary={
            "passed": passed,
            "needs_review": needs_review,
            "total": len(items),
        },
    )


frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
