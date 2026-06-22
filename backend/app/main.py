import logging
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.comparison import verify_label
from app.models import ApplicationData, VerificationResult
from app.vision_service import OpenAIVisionService, VisionService

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}

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
        extracted = vision_service.extract(contents)
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


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
