"""
routes/diagnose.py
POST /api/diagnose               — analyse a plant image with Gemini Vision
POST /api/diagnoses/{id}/review  — agronomist submits expert review
GET  /api/diagnoses/flagged      — list all flagged diagnoses (agronomist only)

Architecture: FastAPI -> Gemini Vision AI -> MongoDB Atlas
"""

import base64
import io
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from PIL import Image

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
    serialize_doc,
    serialize_list,
    strip_json_fences,
)

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_VALID_SEVERITIES = frozenset({"Low", "Moderate", "High"})


# ---------------------------------------------------------------------------
# Request models
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


class ReviewRequest(BaseModel):
    reviewedBy: Optional[str] = Field(None, description="Agronomist user _id")
    corrected_diagnosis: dict = Field(..., description="Corrected diagnosis fields")
    advice: Optional[str] = Field(None, description="Expert advice for the user")
    aiWasCorrect: Optional[bool] = Field(None, description="Was the AI diagnosis correct?")


# ---------------------------------------------------------------------------
# Fallback values
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
# Internal sanitisers
# ---------------------------------------------------------------------------


def _sanitise_ai_result(raw: dict) -> dict:
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
    growth_stage = str(raw.get("growthStage", "Unknown")).strip().capitalize()
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
# Helpers
# ---------------------------------------------------------------------------


def _compress_image(image_bytes: bytes, max_size: tuple = (800, 600), quality: int = 70) -> str:
    """Resize and compress image, return as base64 data URL for storage."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail(max_size, Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(output.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"Image compression failed: {e}")
        return None


# ---------------------------------------------------------------------------
# POST /api/diagnose
# ---------------------------------------------------------------------------


@router.post("/diagnose")
async def diagnose_plant(req: DiagnoseRequest):
    """Analyse a plant image using Gemini Vision and save to MongoDB."""
    db = get_db()

    try:
        system_prompt = load_prompt("diagnose_system.txt")
    except RuntimeError as e:
        logger.error(f"Could not load diagnose prompt: {e}")
        raise HTTPException(status_code=500, detail="AI service configuration error: missing prompt file.")

    if not req.image and not req.imageUrl:
        raise HTTPException(status_code=400, detail="Provide either 'image' (base64) or 'imageUrl'.")

    ai_result = None
    crop_identified = None
    alternatives = None
    image_bytes = None

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
            logger.info(f"Calling Gemini ({GEMINI_MODEL}). Crop: {req.cropType or 'Unknown'}")
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
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
                if parsed.get("multiplePlantsDetected") is True:
                    plants_found = parsed.get("plantsDetected", [])
                    if isinstance(plants_found, list):
                        plants_found = [str(p) for p in plants_found]
                    else:
                        plants_found = []
                    logger.info(f"Multiple plants detected: {plants_found}")
                    return {"multiplePlantsDetected": True, "plantsDetected": plants_found}

                raw_result = parsed.get("aiResult", parsed)
                ai_result = _sanitise_ai_result(raw_result)
                crop_identified = _sanitise_crop(parsed.get("cropIdentified", {}))
                alternatives = _sanitise_alternatives(parsed.get("alternatives", []))
            else:
                logger.warning(f"Unparseable AI response (first 300): {raw_text[:300]!r}")
                ai_result = _FALLBACK_AI_RESULT.copy()
    else:
        logger.info("No base64 image — storing imageUrl without AI analysis.")
        ai_result = _FALLBACK_AI_RESULT.copy()

    if crop_identified is None:
        crop_identified = _FALLBACK_CROP.copy()
    if alternatives is None:
        alternatives = _FALLBACK_ALTERNATIVES.copy()

    flagged_for_review = ai_result["confidenceScore"] < 75

    # Resolve user info — store denormalised so agronomist always sees name/email
    user_oid = None
    user_name = None
    user_email = None
    if req.userId:
        try:
            user_oid = ObjectId(req.userId)
            user_doc = await db.users.find_one({"_id": user_oid})
            if user_doc:
                user_name = user_doc.get("name")
                user_email = user_doc.get("email")
        except InvalidId:
            logger.warning(f"Invalid userId '{req.userId}' — saving without userId.")

    # Compress and store image so agronomist can view it during review
    stored_image_url = req.imageUrl or None
    if image_bytes:
        stored_image_url = _compress_image(image_bytes) or stored_image_url

    diagnosis_doc = {
        "cropType": req.cropType or "Unknown",
        "growthStage": req.growthStage or "Unknown",
        "issue": req.symptoms or "None reported",
        "imageUrl": stored_image_url,
        "cropIdentified": crop_identified,
        "aiResult": ai_result,
        "alternatives": alternatives,
        "flaggedForReview": flagged_for_review,
        "createdAt": datetime.now(timezone.utc),
    }
    if user_oid is not None:
        diagnosis_doc["userId"] = user_oid
    if user_name:
        diagnosis_doc["userName"] = user_name
    if user_email:
        diagnosis_doc["userEmail"] = user_email

    try:
        insert_result = await db.diagnoses.insert_one(diagnosis_doc)
        diagnosis_id = str(insert_result.inserted_id)
        logger.info(
            f"Diagnosis saved. _id={diagnosis_id}, "
            f"problem='{ai_result['problem']}', confidence={ai_result['confidenceScore']}, "
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
        "userName": user_name,
        "userEmail": user_email,
    }


# ---------------------------------------------------------------------------
# GET /api/diagnoses/flagged  (agronomist dashboard) — must be before /{id}
# ---------------------------------------------------------------------------


@router.get("/diagnoses/flagged")
async def get_flagged_diagnoses():
    """Return all diagnoses flagged for expert review, newest first."""
    db = get_db()
    try:
        docs = await db.diagnoses.find(
            {"flaggedForReview": True}
        ).sort("createdAt", -1).to_list(length=100)
        return serialize_list(docs)
    except Exception as e:
        logger.error(f"Failed to fetch flagged diagnoses: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch flagged diagnoses.")


# ---------------------------------------------------------------------------
# GET /api/diagnoses/reviewed  (agronomist dashboard) — must be before /{id}
# ---------------------------------------------------------------------------


@router.get("/diagnoses/reviewed")
async def get_reviewed_diagnoses():
    """Return all diagnoses that have been expert-reviewed, newest first."""
    db = get_db()
    try:
        docs = await db.diagnoses.find(
            {"expertReview": {"$exists": True}}
        ).sort("reviewedAt", -1).to_list(length=100)
        return serialize_list(docs)
    except Exception as e:
        logger.error(f"Failed to fetch reviewed diagnoses: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch reviewed diagnoses.")


# ---------------------------------------------------------------------------
# GET /api/diagnoses/{diagnosis_id}  (single diagnosis — user view)
# ---------------------------------------------------------------------------


@router.get("/diagnoses/{diagnosis_id}")
async def get_diagnosis(diagnosis_id: str):
    """Fetch a single diagnosis by ID including expert review if available."""
    db = get_db()
    try:
        oid = ObjectId(diagnosis_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"Invalid diagnosisId: '{diagnosis_id}'.")

    doc = await db.diagnoses.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Diagnosis not found.")

    return serialize_doc(doc)


# ---------------------------------------------------------------------------
# POST /api/diagnoses/{diagnosis_id}/review  (agronomist submits review)
# ---------------------------------------------------------------------------


@router.post("/diagnoses/{diagnosis_id}/review")
async def submit_review(diagnosis_id: str, req: ReviewRequest):
    """Agronomist submits an expert review for a flagged diagnosis."""
    db = get_db()

    try:
        oid = ObjectId(diagnosis_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"Invalid diagnosisId: '{diagnosis_id}'.")

    diagnosis = await db.diagnoses.find_one({"_id": oid})
    if not diagnosis:
        raise HTTPException(status_code=404, detail="Diagnosis not found.")

    reviewer_oid = None
    if req.reviewedBy:
        try:
            reviewer_oid = ObjectId(req.reviewedBy)
        except InvalidId:
            logger.warning(f"Invalid reviewedBy '{req.reviewedBy}' — storing as string.")

    review_doc = {
        "correctedDiagnosis": req.corrected_diagnosis,
        "advice": req.advice,
        "aiWasCorrect": req.aiWasCorrect,
        "reviewedBy": reviewer_oid or req.reviewedBy,
        "reviewedAt": datetime.now(timezone.utc),
    }

    try:
        await db.diagnoses.update_one(
            {"_id": oid},
            {
                "$set": {
                    "expertReview": review_doc,
                    "flaggedForReview": False,   # clear flag after review
                    "reviewedAt": datetime.now(timezone.utc),
                }
            },
        )
        logger.info(f"Review submitted for diagnosis _id={diagnosis_id}")
        return {"status": "ok", "diagnosisId": diagnosis_id}
    except Exception as e:
        logger.error(f"Failed to save review: {e}")
        raise HTTPException(status_code=500, detail="Failed to save review.")
