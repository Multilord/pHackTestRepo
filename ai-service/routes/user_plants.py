"""
routes/user_plants.py

POST /api/user-plants  — add a plant to a user's collection
POST /api/activity     — log a watering/harvest/feeding activity
GET  /api/dashboard/{userId} — aggregated dashboard stats for a user
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.db import get_db
from utils.helpers import serialize_doc, serialize_list

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AddUserPlantRequest(BaseModel):
    userId: str = Field(..., description="MongoDB user _id")
    plantId: str = Field(..., description="MongoDB plant _id")
    status: str = Field("growing", description="'growing', 'harvested', 'dormant'")
    checklist: List[str] = Field(default_factory=list)


class ActivityRequest(BaseModel):
    userId: str = Field(..., description="MongoDB user _id")
    userPlantId: str = Field(..., description="MongoDB user_plants _id")
    type: str = Field(..., description="Activity type e.g. 'watering', 'harvesting', 'fertilizing'")
    value: Optional[float] = Field(None, description="Numeric value e.g. litres of water")
    unit: Optional[str] = Field(None, description="Unit string e.g. 'litres', 'kg'")


# ---------------------------------------------------------------------------
# POST /api/user-plants
# ---------------------------------------------------------------------------


@router.post("/user-plants", status_code=201)
async def add_user_plant(req: AddUserPlantRequest):
    """Add a plant to the user's collection (user_plants collection)."""
    db = get_db()

    try:
        user_oid = ObjectId(req.userId)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"Invalid userId: '{req.userId}'")

    try:
        plant_oid = ObjectId(req.plantId)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"Invalid plantId: '{req.plantId}'")

    # Verify plant exists
    plant = await db.plants.find_one({"_id": plant_oid})
    if not plant:
        raise HTTPException(status_code=404, detail=f"Plant '{req.plantId}' not found.")

    doc = {
        "userId": user_oid,
        "plantId": plant_oid,
        "status": req.status,
        "checklist": req.checklist,
        "stats": {
            "totalHarvestKg": 0.0,
            "waterUsedLitres": 0.0,
        },
        "startedAt": datetime.now(timezone.utc),
    }

    try:
        result = await db.user_plants.insert_one(doc)
        return {"userPlantId": str(result.inserted_id), "status": req.status}
    except Exception as e:
        logger.error(f"Failed to add user plant: {e}")
        raise HTTPException(status_code=500, detail="Failed to save to database.")


# ---------------------------------------------------------------------------
# POST /api/activity
# ---------------------------------------------------------------------------


@router.post("/activity", status_code=201)
async def log_activity(req: ActivityRequest):
    """Log a plant activity (watering, harvest, etc.) to activity_logs collection."""
    db = get_db()

    try:
        user_oid = ObjectId(req.userId)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"Invalid userId: '{req.userId}'")

    try:
        user_plant_oid = ObjectId(req.userPlantId)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"Invalid userPlantId: '{req.userPlantId}'")

    doc = {
        "userId": user_oid,
        "userPlantId": user_plant_oid,
        "type": req.type,
        "loggedAt": datetime.now(timezone.utc),
    }
    if req.value is not None:
        doc["value"] = req.value
    if req.unit:
        doc["unit"] = req.unit

    # Update stats in user_plants document
    if req.type == "watering" and req.value is not None:
        await db.user_plants.update_one(
            {"_id": user_plant_oid},
            {"$inc": {"stats.waterUsedLitres": req.value}},
        )
    elif req.type == "harvesting" and req.value is not None:
        await db.user_plants.update_one(
            {"_id": user_plant_oid},
            {"$inc": {"stats.totalHarvestKg": req.value}},
        )

    try:
        result = await db.activity_logs.insert_one(doc)
        return {"activityId": str(result.inserted_id), "type": req.type}
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")
        raise HTTPException(status_code=500, detail="Failed to save activity to database.")


# ---------------------------------------------------------------------------
# GET /api/dashboard/{userId}
# ---------------------------------------------------------------------------


@router.get("/dashboard/{userId}")
async def get_dashboard(userId: str):
    """Return aggregated dashboard stats for a user."""
    db = get_db()

    try:
        user_oid = ObjectId(userId)
    except InvalidId:
        raise HTTPException(status_code=400, detail=f"Invalid userId: '{userId}'")

    # Fetch user's plants with plant details
    user_plants = await db.user_plants.find({"userId": user_oid}).to_list(length=200)

    plant_ids = [up["plantId"] for up in user_plants if "plantId" in up]
    plants_map = {}
    if plant_ids:
        plants = await db.plants.find({"_id": {"$in": plant_ids}}).to_list(length=200)
        plants_map = {str(p["_id"]): p for p in plants}

    # Aggregate stats
    total_water = sum(
        up.get("stats", {}).get("waterUsedLitres", 0) for up in user_plants
    )
    total_harvest = sum(
        up.get("stats", {}).get("totalHarvestKg", 0) for up in user_plants
    )
    active_plants = [up for up in user_plants if up.get("status") == "growing"]

    # Recent activity (last 10 logs)
    recent_activity = await db.activity_logs.find(
        {"userId": user_oid}
    ).sort("loggedAt", -1).limit(10).to_list(length=10)

    # Recent diagnoses (last 5)
    recent_diagnoses = await db.diagnoses.find(
        {"userId": user_oid}
    ).sort("createdAt", -1).limit(5).to_list(length=5)

    # Build enriched active plants list
    enriched_plants = []
    for up in active_plants:
        pid_str = str(up.get("plantId", ""))
        plant_info = plants_map.get(pid_str, {})
        enriched_plants.append({
            "userPlantId": str(up["_id"]),
            "plantId": pid_str,
            "name": plant_info.get("name", "Unknown"),
            "emoji": plant_info.get("emoji", "🌱"),
            "status": up.get("status"),
            "checklist": up.get("checklist", []),
            "stats": up.get("stats", {}),
            "startedAt": up["startedAt"].isoformat() if "startedAt" in up else None,
        })

    return {
        "userId": userId,
        "summary": {
            "activePlants": len(active_plants),
            "totalPlantsTracked": len(user_plants),
            "totalWaterUsedLitres": round(total_water, 2),
            "totalHarvestKg": round(total_harvest, 2),
        },
        "activePlants": enriched_plants,
        "recentActivity": serialize_list(recent_activity),
        "recentDiagnoses": serialize_list(recent_diagnoses),
    }
