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
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect_db() first.")
    return _db