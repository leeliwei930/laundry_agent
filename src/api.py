"""
FastAPI HTTP wrapper for the laundry monitoring agent.

Exposes the Lambda handler (src/laundry_monitoring_agent.py:handler) as a
local HTTP service so it can be called from Home Assistant or other
systems without AWS Lambda. The agent code is untouched — this module only
adapts HTTP requests to handler events and maps error codes to HTTP status
codes, preserving the handler's exact JSON response shape.

Run with: uvicorn api:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from laundry_monitoring_agent import handler, _INITIALIZATION_ERROR

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Laundry Monitoring Agent API",
    description="Analyzes security camera images for laundry in open air areas "
                "and returns weather-aware bilingual recommendations.",
)


def _status_for_error(error: dict) -> int:
    """Map a handler error_code to an HTTP status code."""
    error_code = error.get("error_code", "")
    message = error.get("message", "")

    if error_code == "INPUT_VALIDATION_ERROR":
        return 422
    if error_code == "CONFIGURATION_ERROR":
        return 503
    if error_code == "STORAGE_ERROR":
        return 404 if "not found" in message else 502
    if error_code == "IMAGE_PROCESSING_ERROR":
        return 422
    if error_code.startswith("BEDROCK_") or error_code == "VALIDATION_ERROR":
        return 502
    return 500


@app.post("/analyze")
async def analyze(request: Request) -> Response:
    """
    Run the laundry analysis for one camera snapshot.

    Body is the same JSON structure as the Lambda event:
    {
        "file_key": "camera_snapshot/20251110/120000_porch.jpg",
        "current_time": "2025-10-12T02:00:00+00:00",
        "weather_forecast": { "<entity_id>": { "forecast": [ ... ] } }
    }

    The handler performs all input validation; its response body is
    returned verbatim with an HTTP status mapped from the error_code.
    """
    try:
        event = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "errors": [{
                    "message": "Invalid request body",
                    "details": "Request body must be valid JSON",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            },
        )

    if not isinstance(event, dict):
        return JSONResponse(
            status_code=422,
            content={
                "errors": [{
                    "message": "Invalid request body",
                    "details": "Request body must be a JSON object",
                    "error_code": "INPUT_VALIDATION_ERROR"
                }]
            },
        )

    # The handler is blocking (boto3 + model inference can take ~60s),
    # so run it off the event loop.
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, handler, event, None)

    if "errors" in result:
        status = _status_for_error(result["errors"][0]) if result["errors"] else 500
        return JSONResponse(status_code=status, content=result)

    return JSONResponse(status_code=200, content=result)


@app.get("/healthz")
async def healthz() -> Response:
    """
    Liveness probe. Reports whether the agent's environment validated.

    Always 200 — liveness only. Configuration problems are surfaced as
    503 CONFIGURATION_ERROR on /analyze.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "configured": _INITIALIZATION_ERROR is None,
        },
    )


@app.get("/", include_in_schema=False)
async def root() -> Response:
    return RedirectResponse(url="/docs")
