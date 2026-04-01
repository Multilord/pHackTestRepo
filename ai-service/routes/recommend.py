"""
routes/recommend.py
POST /ai/recommend

Receives userInput + availablePlants from Person D's Express backend.
Calls Gemini to rank plants and return enriched recommendations.
Returns schema-safe JSON — Person D's backend saves this into MongoDB.

Person D is the ONLY caller of this endpoint.
This route never touches MongoDB.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Union

from google import genai
from google.genai import types
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.helpers import load_prompt, strip_json_fences, parse_json_safe

load_dotenv()

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class UserInput(BaseModel):
    location: str = Field(..., description="Growing space type e.g. 'Balcony', 'Indoor', 'Rooftop'")
    sunlight: str = Field(..., description="Sunlight availability e.g. 'Full Sun', 'Partial Shade'")
    goal: str = Field(..., description="Growing goal e.g. 'Low maintenance', 'Cooking herbs'")


class RecommendRequest(BaseModel):
    userInput: UserInput
    availablePlants: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Plant documents from MongoDB plants collection, sent by Person D's backend",
    )


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class CareGuide(BaseModel):
    waterFreq: str
    sunNeeds: str
    growTime: Union[int, str]
    soilMix: str
    potSize: str
    fertilizerNeeded: str


class CalendarEntry(BaseModel):
    week: str
    title: str
    description: str


class PlantRecommendation(BaseModel):
    plantId: str
    score: int
    reason: str
    careGuide: CareGuide
    calendar: List[CalendarEntry]


class RecommendResponse(BaseModel):
    recommendedPlants: List[PlantRecommendation]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sanitise_recommendation(raw: dict) -> PlantRecommendation:
    """Coerce a single Gemini-returned plant dict into a validated PlantRecommendation."""

    # score: clamp to [1, 100]
    try:
        score = max(1, min(100, int(raw.get("score", 70))))
    except (TypeError, ValueError):
        score = 70

    # careGuide
    cg_raw = raw.get("careGuide", {})
    if not isinstance(cg_raw, dict):
        cg_raw = {}

    care_guide = CareGuide(
        waterFreq=str(cg_raw.get("waterFreq", "As needed")),
        sunNeeds=str(cg_raw.get("sunNeeds", "Moderate light")),
        growTime=cg_raw.get("growTime", "60–90 days"),
        soilMix=str(cg_raw.get("soilMix", "General-purpose potting mix")),
        potSize=str(cg_raw.get("potSize", "8–10 inch pot")),
        fertilizerNeeded=str(cg_raw.get("fertilizerNeeded", "Monthly")),
    )

    # calendar: 4–6 entries
    calendar_raw = raw.get("calendar", [])
    if not isinstance(calendar_raw, list):
        calendar_raw = []
    calendar_raw = calendar_raw[:6]
    while len(calendar_raw) < 4:
        idx = len(calendar_raw) + 1
        calendar_raw.append({
            "week": f"Week {idx * 2 - 1}–{idx * 2}",
            "title": "Ongoing Care",
            "description": "Continue regular watering, feeding, and monitoring for pests.",
        })

    validated_calendar = []
    for entry in calendar_raw:
        if not isinstance(entry, dict):
            continue
        validated_calendar.append(CalendarEntry(
            week=str(entry.get("week", "Week ?")),
            title=str(entry.get("title", "Care")),
            description=str(entry.get("description", "Continue regular plant care.")),
        ))

    return PlantRecommendation(
        plantId=str(raw.get("plantId", "")),
        score=score,
        reason=str(raw.get("reason", "Suitable for your growing conditions.")),
        careGuide=care_guide,
        calendar=validated_calendar,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/recommend", response_model=RecommendResponse)
async def recommend_plants(request: RecommendRequest) -> RecommendResponse:
    """
    Rank and enrich plant recommendations using Gemini.

    Called by Person D's Express backend with:
      - userInput: user's location, sunlight, and goal
      - availablePlants: plant candidates fetched from MongoDB plants collection

    Returns top 3–5 ranked plant recommendations.
    Person D's backend saves the result into the recommendations collection.
    """
    try:
        system_prompt = load_prompt("recommend_system.txt")
    except RuntimeError as e:
        logger.error(f"Could not load recommend prompt: {e}")
        raise HTTPException(status_code=500, detail="AI service configuration error: missing prompt file.")

    if not request.availablePlants:
        raise HTTPException(
            status_code=400,
            detail="availablePlants must not be empty. Person D's backend should query the plants collection first."
        )

    user_input_json = json.dumps(request.userInput.model_dump(), indent=2)
    plants_json = json.dumps(request.availablePlants, indent=2)

    user_message = (
        f"User Input:\n{user_input_json}\n\n"
        f"Available Plants from Database ({len(request.availablePlants)} total):\n{plants_json}\n\n"
        f"Rank the top 3 to 5 plants ONLY from the list above. "
        f"Use each plant's _id field exactly as the plantId in your response. "
        f"Return strictly as JSON following the schema in your instructions."
    )

    try:
        logger.info(
            f"Calling Gemini ({GEMINI_MODEL}) for recommendations. "
            f"Plant candidates: {len(request.availablePlants)}"
        )
        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=8192,
            ),
            contents=user_message,
        )
        raw_text = response.text

    except Exception as e:
        err = str(e)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            logger.warning(f"Gemini rate limit hit: {err[:100]}")
            raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please retry.")
        if "403" in err or "401" in err or "API_KEY" in err.upper():
            logger.error(f"Gemini auth error: {err[:100]}")
            raise HTTPException(status_code=502, detail="AI service authentication error.")
        logger.error(f"Unexpected error calling Gemini for recommendations: {err[:200]}")
        raise HTTPException(status_code=503, detail="AI service temporarily unavailable. Please retry.")

    cleaned_text = strip_json_fences(raw_text)
    parsed = parse_json_safe(cleaned_text)

    if not parsed:
        logger.warning(f"Gemini returned unparseable JSON. Raw (first 300): {raw_text[:300]!r}")
        raise HTTPException(status_code=502, detail="AI returned an invalid response. Please retry.")

    plants_raw = parsed.get("recommendedPlants")
    if not isinstance(plants_raw, list) or len(plants_raw) == 0:
        logger.warning(f"Gemini returned invalid 'recommendedPlants' structure: {type(plants_raw).__name__}")
        raise HTTPException(status_code=502, detail="AI returned an invalid response. Please retry.")

    plants_raw = plants_raw[:5]
    validated: List[PlantRecommendation] = []
    for idx, plant in enumerate(plants_raw):
        if not isinstance(plant, dict):
            logger.warning(f"Plant at index {idx} is not a dict. Skipping.")
            continue
        try:
            validated.append(_sanitise_recommendation(plant))
        except Exception as e:
            logger.warning(f"Failed to sanitise plant at index {idx}: {e}. Skipping.")

    if not validated:
        logger.warning("All plants failed validation.")
        raise HTTPException(status_code=502, detail="AI returned an invalid response. Please retry.")

    logger.info(f"Returning {len(validated)} plant recommendations.")
    return RecommendResponse(recommendedPlants=validated)
