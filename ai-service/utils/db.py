"""
utils/db.py
MongoDB Atlas async connection using Motor.

Usage:
    from utils.db import get_db
    db = get_db()
    docs = await db.plants.find().to_list(100)
"""

import logging
import os

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

load_dotenv()

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


async def connect_db() -> None:
    global _client, _db
    uri = os.getenv("MONGODB_URI")
    db_name = os.getenv("MONGODB_DB", "homegrow")
    if not uri:
        raise RuntimeError("MONGODB_URI environment variable is not set.")
    _client = AsyncIOMotorClient(uri)
    _db = _client[db_name]
    logger.info(f"Connected to MongoDB database: '{db_name}'")


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        # Lazy init for serverless environments where startup events may not fire
        uri = os.getenv("MONGODB_URI")
        db_name = os.getenv("MONGODB_DB", "homegrow")
        if not uri:
            raise RuntimeError("MONGODB_URI environment variable is not set.")
        _client = AsyncIOMotorClient(uri)
        _db = _client[db_name]
        logger.info(f"Lazy-connected to MongoDB database: '{db_name}'")
    return _db