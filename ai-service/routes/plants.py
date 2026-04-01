"""
routes/plants.py
GET /api/plants — return all plants from MongoDB.
"""

import logging

from fastapi import APIRouter, HTTPException

from utils.db import get_db
from utils.helpers import serialize_list

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/plants")
async def get_plants():
    """Return all plants from the plants collection."""
    try:
        db = get_db()
        plants = await db.plants.find().to_list(length=500)
        return serialize_list(plants)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to fetch plants: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch plants from database.")
