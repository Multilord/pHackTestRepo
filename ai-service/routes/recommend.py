"""
routes/recommend.py
POST /api/recommend

Architecture: FastAPI -> MongoDB Atlas + Gemini AI
- Reads candidate plants directly from MongoDB plants collection
- Filters by real plant schema (spaceType, idealConditions)
- Uses AI to rank filtered candidates and generate reasons
- Saves recommendation to MongoDB recommendations collection
- Returns enriched response with full plant data + AI ranking
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
    load_prompt,
    parse_json_safe,
    serialize_doc,
    strip_json_fences,
)

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class RecommendRequest(BaseModel):
    userId: Optional[str] = Field(None, description="MongoDB user _id (optional)")
    location: str = Field(..., description="Growing space e.g. 'Balcony', 'Indoor', 'Rooftop'")
    sunlight: str = Field(..., description="Light level e.g. 'Full Sun', 'Partial Shade', 'Low Light'")
    goal: str = Field(..., description="Growing goal e.g. 'Low maintenance', 'Cooking herbs'")
    sunlightHours: Optional[float] = Field(None, description="Hours of sunlight per day")
    temperature: Optional[float] = Field(None, description="Ambient temperature in °C")
    humidity: Optional[float] = Field(None, description="Ambient humidity percentage")


# ---------------------------------------------------------------------------
# Plant filtering
# ---------------------------------------------------------------------------


def _filter_plants(plants: List[dict], req: RecommendRequest) -> List[dict]:
    """
    Filter plants by spaceType and idealConditions.
    Falls back progressively if not enough candidates pass.
    """
    def passes_strict(p: dict) -> bool:
        space = str(p.get("spaceType", "")).strip().lower()
        if space and space != req.location.strip().lower():
            return False
        ic = p.get("idealConditions", {})
        if req.sunlightHours is not None:
            mn = ic.get("minSunlight")
            mx = ic.get("maxSunlight")
            if mn is not None and req.sunlightHours < mn:
                return False
            if mx is not None and req.sunlightHours > mx:
                return False
        if req.temperature is not None:
            mn = ic.get("minTemp")
            mx = ic.get("maxTemp")
            if mn is not None and req.temperature < mn:
                return False
            if mx is not None and req.temperature > mx:
                return False
        if req.humidity is not None:
            mn = ic.get("minHumidity")
            mx = ic.get("maxHumidity")
            if mn is not None and req.humidity < mn:
                return False
            if mx is not None and req.humidity > mx:
                return False
        return True

    def passes_space_only(p: dict) -> bool:
        space = str(p.get("spaceType", "")).strip().lower()
        return not space or space == req.location.strip().lower()

    strict = [p for p in plants if passes_strict(p)]
    if len(strict) >= 3:
        return strict

    space_only = [p for p in plants if passes_space_only(p)]
    if len(space_only) >= 3:
        logger.info("Strict filter yielded <3 plants — falling back to spaceType-only filter.")
        return space_only

    logger.info("SpaceType filter yielded <3 plants — using all plants as candidates.")
    return plants


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/recommend")
async def recommend_plants(req: RecommendRequest):
    """
    Generate plant recommendations for a user.
    Reads plants from MongoDB, filters, ranks with AI, saves result to DB.
    """
    db = get_db()

    # 1. Load system prompt
    try:
        system_prompt = load_prompt("recommend_system.txt")
    except RuntimeError as e:
        logger.error(f"Could not load recommend prompt: {e}")
        raise HTTPException(status_code=500, detail="AI service configuration error: missing prompt file.")

    # 2. Fetch all plants from MongoDB
    try:
        all_plants = await db.plants.find().to_list(length=500)
    except Exception as e:
        logger.error(f"Failed to fetch plants from DB: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable. Cannot fetch plants.")

    if not all_plants:
        raise HTTPException(status_code=404, detail="No plants found in database.")

    # 3. Filter candidates
    candidates = _filter_plants(all_plants, req)
    logger.info(f"Candidates after filtering: {len(candidates)} / {len(all_plants)} total plants.")

    # Prepare candidates for AI (serialize ObjectIds)
    candidates_for_ai = []
    for p in candidates:
        doc = {k: str(v) if isinstance(v, ObjectId) else v for k, v in p.items()}
        candidates_for_ai.append(doc)

    # 4. Call Gemini AI
    user_message = (
        f"userConditions:\n{json.dumps({'location': req.location, 'sunlight': req.sunlight, 'goal': req.goal, 'sunlightHours': req.sunlightHours, 'temperature': req.temperature, 'humidity': req.humidity}, indent=2)}\n\n"
        f"candidatePlants ({len(candidates_for_ai)} total):\n{json.dumps(candidates_for_ai, indent=2)}\n\n"
        f"Select and rank the best 3–5 plants. Return ONLY valid JSON per the schema."
    )

    try:
        logger.info(f"Calling Gemini ({GEMINI_MODEL}) for recommendations. Candidates: {len(candidates_for_ai)}")
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=4096,
            ),
            contents=user_message,
        )
        raw_text = response.text
    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            logger.warning(f"Gemini rate limit: {err[:100]}")
            raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please retry.")
        if "403" in err or "401" in err or "API_KEY" in err.upper():
            raise HTTPException(status_code=502, detail="AI service authentication error.")
        logger.error(f"Gemini error: {err[:200]}")
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please retry.")

    # 5. Parse AI response
    cleaned = strip_json_fences(raw_text)
    parsed = parse_json_safe(cleaned)
    if not parsed or not isinstance(parsed.get("plants"), list) or not parsed["plants"]:
        logger.warning(f"AI returned invalid structure. Raw (first 300): {raw_text[:300]!r}")
        raise HTTPException(status_code=502, detail="AI returned an invalid response. Please retry.")

    ai_plants: List[dict] = parsed["plants"][:5]

    # 6. Build index of candidates by _id string for fast lookup
    plant_index: Dict[str, dict] = {str(p["_id"]): p for p in candidates}

    # 7. Build enriched response + collect valid ObjectIds for DB
    result_plants = []
    valid_plant_oids = []

    for item in ai_plants:
        pid = str(item.get("plantId", "")).strip()
        if not pid or pid not in plant_index:
            logger.warning(f"AI returned unknown plantId '{pid}' — skipping.")
            continue

        plant_doc = plant_index[pid]
        success_rate = item.get("successRate", 70)
        try:
            success_rate = max(1, min(100, int(success_rate)))
        except (TypeError, ValueError):
            success_rate = 70

        result_plants.append({
            "plantId": pid,
            "name": plant_doc.get("name", ""),
            "botanicalName": plant_doc.get("botanicalName", ""),
            "emoji": plant_doc.get("emoji", ""),
            "category": plant_doc.get("category", ""),
            "difficulty": plant_doc.get("difficulty", ""),
            "spaceType": plant_doc.get("spaceType", ""),
            "idealConditions": plant_doc.get("idealConditions", {}),
            "careTips": plant_doc.get("careTips", {}),
            "successRate": success_rate,
            "reason": str(item.get("reason", "")),
        })
        try:
            valid_plant_oids.append(ObjectId(pid))
        except InvalidId:
            logger.warning(f"plantId '{pid}' is not a valid ObjectId — storing as string ref only.")

    if not result_plants:
        logger.warning("All AI-returned plants failed validation.")
        raise HTTPException(status_code=502, detail="AI returned no valid plants. Please retry.")

    # 8. Save recommendation to MongoDB
    user_oid = None
    if req.userId:
        try:
            user_oid = ObjectId(req.userId)
        except InvalidId:
            logger.warning(f"Invalid userId '{req.userId}' — saving recommendation without userId.")

    rec_doc: Dict[str, Any] = {
        "userInput": {
            "location": req.location,
            "sunlight": req.sunlight,
            "goal": req.goal,
        },
        "plants": valid_plant_oids,
        "createdAt": datetime.now(timezone.utc),
    }
    if user_oid is not None:
        rec_doc["userId"] = user_oid

    try:
        insert_result = await db.recommendations.insert_one(rec_doc)
        recommendation_id = str(insert_result.inserted_id)
        logger.info(f"Recommendation saved. _id={recommendation_id}, plants={len(valid_plant_oids)}")
    except Exception as e:
        logger.error(f"Failed to save recommendation to DB: {e}")
        recommendation_id = None

    logger.info(f"Returning {len(result_plants)} plant recommendations.")
    return {
        "recommendationId": recommendation_id,
        "plants": result_plants,
    }
