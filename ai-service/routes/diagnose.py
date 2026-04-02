"""
routes/diagnose.py
POST /api/diagnose

Architecture: FastAPI -> Gemini Vision AI -> MongoDB Atlas
- Analyses plant image with Gemini Vision
- Saves diagnosis to MongoDB diagnoses collection
- Returns the saved diagnosis document
"""

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from utils.db import get_db
from utils.helpers import (
    clamp_confidence,
    extract_base64_data,
    load_prompt,
    parse_json_safe,
    strip_json_fences,
)

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_VALID_SEVERITIES = frozenset({"Low", "Moderate", "High"})


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class DiagnoseRequest(BaseModel):
    userId: Optional[str] = Field(None, description="MongoDB user _id (optional)")
    image: Optional[str] = Field(
        None,
        description="Base64-encoded plant image. Accepts raw base64 or data URL.",
    )
    imageUrl: Optional[str] = Field(None, description="Public URL of the image (stored in DB)")
    cropType: Optional[str] = Field(None, description="Plant type e.g. 'Tomato', 'Chilli'")
    growthStage: Optional[str] = Field(None, description="Growth stage e.g. 'Seedling', 'Flowering'")
    symptoms: Optional[str] = Field(None, description="Reported symptom description")


# ---------------------------------------------------------------------------
# Fallback diagnosis (when AI is unavailable or response is unparseable)
# ---------------------------------------------------------------------------


_FALLBACK_AI_RESULT = {
    "problem": "Unable to Determine",
    "cause": "The AI could not analyse the image at this time.",
    "severity": "Low",
    "solution": (
        "Retake the photo in good natural light with the affected area clearly visible. "
        "If symptoms persist, consult a local plant nursery or agricultural officer."
    ),
    "confidenceScore": 20,
}

_FALLBACK_CROP = {
    "name": "Unknown Plant",
    "botanicalName": "",
    "description": "Could not identify the crop from the provided image.",
    "growthStage": "Unknown",
    "growthStageNote": "",
}

_FALLBACK_ALTERNATIVES = [
    {
        "problem": "Environmental Stress",
        "cause": "Suboptimal watering, light, or temperature conditions.",
        "solution": "Review and adjust your watering schedule, light exposure, and growing environment.",
        "likelihood": 40,
    },
    {
        "problem": "Nutrient Deficiency",
        "cause": "Lack of key nutrients such as nitrogen, iron, or magnesium in the soil.",
        "solution": "Apply a balanced liquid fertiliser and check soil pH.",
        "likelihood": 40,
    },
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitise_ai_result(raw: dict) -> dict:
    """Validate and sanitise the primary AI result fields."""
    severity = str(raw.get("severity", "Low")).strip().capitalize()
    if severity not in _VALID_SEVERITIES:
        logger.warning(f"Invalid severity '{severity}'. Defaulting to 'Low'.")
        severity = "Low"

    raw_score = raw.get("confidenceScore", 50)
    try:
        confidence = clamp_confidence(int(raw_score))
    except (TypeError, ValueError):
        confidence = 50

    return {
        "problem": str(raw.get("problem", "Unknown Issue")),
        "cause": str(raw.get("cause", "Unknown cause.")),
        "severity": severity,
        "solution": str(raw.get("solution", "Monitor the plant closely.")),
        "confidenceScore": confidence,
    }


_VALID_GROWTH_STAGES = frozenset({
    "Germination", "Seedling", "Vegetative", "Flowering",
    "Fruiting", "Mature", "Dormant", "Unknown",
})


def _sanitise_crop(raw: dict) -> dict:
    """Validate and sanitise crop identification fields."""
    growth_stage = str(raw.get("growthStage", "Unknown")).strip().capitalize()
    # Re-capitalise known multi-word stages that .capitalize() would mangle
    stage_map = {
        "Germination": "Germination", "Seedling": "Seedling",
        "Vegetative": "Vegetative", "Flowering": "Flowering",
        "Fruiting": "Fruiting", "Mature": "Mature",
        "Dormant": "Dormant", "Unknown": "Unknown",
    }
    growth_stage = stage_map.get(growth_stage, "Unknown")
    return {
        "name": str(raw.get("name", "Unknown Plant")),
        "botanicalName": str(raw.get("botanicalName", "")),
        "description": str(raw.get("description", "")),
        "growthStage": growth_stage,
        "growthStageNote": str(raw.get("growthStageNote", "")),
    }


def _sanitise_alternatives(raw_list: list) -> list:
    """Validate and sanitise alternative diagnoses."""
    if not isinstance(raw_list, list):
        return _FALLBACK_ALTERNATIVES
    result = []
    for item in raw_list[:3]:
        if not isinstance(item, dict):
            continue
        try:
            likelihood = max(1, min(99, int(item.get("likelihood", 5))))
        except (TypeError, ValueError):
            likelihood = 5
        result.append({
            "problem": str(item.get("problem", "Unknown")),
            "cause": str(item.get("cause", "")),
            "solution": str(item.get("solution", "")),
            "likelihood": likelihood,
        })
    return result if result else _FALLBACK_ALTERNATIVES


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/diagnose")
async def diagnose_plant(req: DiagnoseRequest):
    """
    Analyse a plant image using Gemini Vision.
    Saves the diagnosis to MongoDB diagnoses collection and returns the result.
    """
    db = get_db()

    # Load prompt
    try:
        system_prompt = load_prompt("diagnose_system.txt")
    except RuntimeError as e:
        logger.error(f"Could not load diagnose prompt: {e}")
        raise HTTPException(status_code=500, detail="AI service configuration error: missing prompt file.")

    # Validate: need at least an image or imageUrl
    if not req.image and not req.imageUrl:
        raise HTTPException(status_code=400, detail="Provide either 'image' (base64) or 'imageUrl'.")

    ai_result = None
    crop_identified = None
    alternatives = None

    # Run AI analysis if base64 image is provided
    if req.image and req.image.strip():
        try:
            media_type, b64_data = extract_base64_data(req.image)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image format: {e}")

        if not b64_data:
            raise HTTPException(status_code=400, detail="Image data is empty after parsing.")

        try:
            image_bytes = base64.b64decode(b64_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not decode image: {e}")

        user_message = (
            f"Crop Type: {req.cropType or 'Unknown'}\n"
            f"Growth Stage: {req.growthStage or 'Unknown'}\n"
            f"Reported Symptoms: {req.symptoms or 'None reported'}\n\n"
            f"Analyse the image and return your diagnosis strictly as JSON following the schema in your instructions."
        )

        try:
            logger.info(
                f"Calling Gemini ({GEMINI_MODEL}) for diagnosis. "
                f"Crop: {req.cropType or 'Unknown'}, Stage: {req.growthStage or 'Unknown'}"
            )
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
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
                logger.warning(f"Gemini rate limit: {err[:100]}")
                ai_result = _FALLBACK_AI_RESULT.copy()
            elif "403" in err or "401" in err or "API_KEY" in err.upper():
                raise HTTPException(status_code=502, detail="AI service authentication error.")
            else:
                logger.error(f"Gemini error: {err[:200]}")
                ai_result = _FALLBACK_AI_RESULT.copy()
        else:
            cleaned = strip_json_fences(raw_text)
            parsed = parse_json_safe(cleaned)

            if parsed:
                raw_result = parsed.get("aiResult", parsed)
                ai_result = _sanitise_ai_result(raw_result)
                crop_identified = _sanitise_crop(parsed.get("cropIdentified", {}))
                alternatives = _sanitise_alternatives(parsed.get("alternatives", []))
            else:
                logger.warning(f"Unparseable AI response. Raw (first 300): {raw_text[:300]!r}")
                ai_result = _FALLBACK_AI_RESULT.copy()
    else:
        # No base64 image — use fallback (imageUrl-only mode, no AI analysis)
        logger.info("No base64 image provided. Storing imageUrl without AI analysis.")
        ai_result = _FALLBACK_AI_RESULT.copy()

    if crop_identified is None:
        crop_identified = _FALLBACK_CROP.copy()
    if alternatives is None:
        alternatives = _FALLBACK_ALTERNATIVES.copy()

    flagged_for_review = ai_result["confidenceScore"] < 75

    # Build MongoDB document
    user_oid = None
    if req.userId:
        try:
            user_oid = ObjectId(req.userId)
        except InvalidId:
            logger.warning(f"Invalid userId '{req.userId}' — saving diagnosis without userId.")

    diagnosis_doc = {
        "cropType": req.cropType or "Unknown",
        "growthStage": req.growthStage or "Unknown",
        "issue": req.symptoms or "None reported",
        "imageUrl": req.imageUrl or None,
        "cropIdentified": crop_identified,
        "aiResult": ai_result,
        "alternatives": alternatives,
        "flaggedForReview": flagged_for_review,
        "createdAt": datetime.now(timezone.utc),
    }
    if user_oid is not None:
        diagnosis_doc["userId"] = user_oid

    # Save to MongoDB
    try:
        insert_result = await db.diagnoses.insert_one(diagnosis_doc)
        diagnosis_id = str(insert_result.inserted_id)
        logger.info(
            f"Diagnosis saved. _id={diagnosis_id}, "
            f"problem='{ai_result['problem']}', "
            f"severity={ai_result['severity']}, "
            f"confidence={ai_result['confidenceScore']}, "
            f"flagged={flagged_for_review}"
        )
    except Exception as e:
        logger.error(f"Failed to save diagnosis to DB: {e}")
        diagnosis_id = None

    return {
        "diagnosisId": diagnosis_id,
        "cropType": diagnosis_doc["cropType"],
        "growthStage": diagnosis_doc["growthStage"],
        "issue": diagnosis_doc["issue"],
        "imageUrl": diagnosis_doc["imageUrl"],
        "cropIdentified": crop_identified,
        "aiResult": ai_result,
        "alternatives": alternatives,
        "flaggedForReview": flagged_for_review,
        "createdAt": diagnosis_doc["createdAt"].isoformat(),
    }
