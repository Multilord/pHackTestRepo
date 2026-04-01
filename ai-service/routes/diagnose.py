"""
routes/diagnose.py
POST /ai/diagnose
"""

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.helpers import (
    clamp_confidence,
    extract_base64_data,
    load_prompt,
    parse_json_safe,
    strip_json_fences,
)
from utils.db import get_db

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_VALID_SEVERITIES = frozenset({"Low", "Moderate", "High"})


# ---------------------------------------------------------------------------
# Pydantic request model
# ---------------------------------------------------------------------------


class DiagnoseRequest(BaseModel):
    image: str = Field(
        ...,
        description="Base64-encoded plant image. Accepts raw base64 or data URL (data:image/jpeg;base64,...).",
    )
    cropType: Optional[str] = Field(None, description="Plant type e.g. 'Tomato', 'Chilli'")
    growthStage: Optional[str] = Field(None, description="Growth stage e.g. 'Seedling', 'Flowering'")
    issue: Optional[str] = Field(None, description="Reported symptom e.g. 'Yellowing leaves'")
    userId: Optional[str] = Field(None, description="MongoDB user _id (optional, for saving to diagnoses collection)")


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class AIResult(BaseModel):
    problem: str
    cause: str
    severity: str
    solution: str
    confidenceScore: int


class DiagnoseResponse(BaseModel):
    aiResult: AIResult
    flaggedForReview: bool


# ---------------------------------------------------------------------------
# Fallback — returned when Gemini is unavailable or response is unparseable
# ---------------------------------------------------------------------------

_FALLBACK = DiagnoseResponse(
    aiResult=AIResult(
        problem="Unable to Determine",
        cause="The AI could not analyse the image at this time.",
        severity="Low",
        solution=(
            "Retake the photo in good natural light with the affected area clearly visible. "
            "If symptoms persist, consult a local plant nursery or agricultural officer."
        ),
        confidenceScore=20,
    ),
    flaggedForReview=True,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitise_diagnosis(data: dict) -> DiagnoseResponse:
    ai_raw = data.get("aiResult", {})
    if not isinstance(ai_raw, dict):
        ai_raw = {}

    severity = str(ai_raw.get("severity", "Low")).strip().capitalize()
    if severity not in _VALID_SEVERITIES:
        logger.warning(f"Invalid severity '{severity}'. Defaulting to 'Low'.")
        severity = "Low"

    raw_score = ai_raw.get("confidenceScore", 50)
    try:
        confidence = clamp_confidence(int(raw_score))
    except (TypeError, ValueError):
        confidence = 50

    ai_result = AIResult(
        problem=str(ai_raw.get("problem", "Unknown Issue")),
        cause=str(ai_raw.get("cause", "Unknown cause.")),
        severity=severity,
        solution=str(ai_raw.get("solution", "Monitor the plant closely.")),
        confidenceScore=confidence,
    )

    return DiagnoseResponse(aiResult=ai_result, flaggedForReview=confidence < 75)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose_plant(request: DiagnoseRequest) -> DiagnoseResponse:
    """
    Analyse a plant image using Gemini Vision and return a structured diagnosis.
    Person D's backend wraps the result into the diagnoses document and saves to MongoDB.
    """
    try:
        system_prompt = load_prompt("diagnose_system.txt")
    except RuntimeError as e:
        logger.error(f"Could not load diagnose prompt: {e}")
        raise HTTPException(status_code=500, detail="AI service configuration error: missing prompt file.")

    if not request.image or not request.image.strip():
        raise HTTPException(status_code=400, detail="image field is required and must not be empty.")

    try:
        media_type, b64_data = extract_base64_data(request.image)
    except Exception as e:
        logger.error(f"Failed to extract base64 image data: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid image format: {str(e)}")

    if not b64_data:
        raise HTTPException(status_code=400, detail="Image data is empty after parsing.")

    try:
        image_bytes = base64.b64decode(b64_data)
    except Exception as e:
        logger.error(f"Failed to decode base64 image: {e}")
        raise HTTPException(status_code=400, detail=f"Could not decode image: {str(e)}")

    user_message = (
        f"Crop Type: {request.cropType or 'Unknown'}\n"
        f"Growth Stage: {request.growthStage or 'Unknown'}\n"
        f"Reported Issue: {request.issue or 'None reported'}\n\n"
        f"Analyse the image and return your diagnosis strictly as JSON following the schema in your instructions."
    )

    try:
        logger.info(
            f"Calling Gemini ({GEMINI_MODEL}) for plant diagnosis. "
            f"Crop: {request.cropType or 'Unknown'}, Stage: {request.growthStage or 'Unknown'}"
        )
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1024,
            ),
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                user_message,
            ],
        )
        raw_text = response.text

    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            logger.warning(f"Gemini rate limit hit: {err[:100]}")
            return _FALLBACK
        if "403" in err or "401" in err or "API_KEY" in err.upper():
            logger.error(f"Gemini auth error: {err[:100]}")
            raise HTTPException(status_code=502, detail="AI service authentication error.")
        logger.error(f"Unexpected Gemini error: {err[:200]}")
        return _FALLBACK

    cleaned_text = strip_json_fences(raw_text)
    parsed = parse_json_safe(cleaned_text)

    if not parsed:
        logger.warning(f"Gemini returned unparseable JSON. Raw (first 300): {raw_text[:300]!r}")
        return _FALLBACK

    try:
        result = _sanitise_diagnosis(parsed)
        logger.info(
            f"Diagnosis complete. Problem: '{result.aiResult.problem}', "
            f"Severity: {result.aiResult.severity}, "
            f"Confidence: {result.aiResult.confidenceScore}, "
            f"Flagged: {result.flaggedForReview}"
        )
        return result
    except Exception as e:
        logger.error(f"Failed to sanitise Gemini diagnosis output: {e}")
        return _FALLBACK
