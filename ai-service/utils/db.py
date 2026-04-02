"""
utils/db.py
Async MongoDB connection for the HomeGrow AI service.
Uses Motor (AsyncIO) for non-blocking database operations.
"""

import logging
import os
import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

load_dotenv()

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI environment variable is not set.")
        _client = AsyncIOMotorClient(uri, tlsCAFile=certifi.where())
    return _client


def get_db() -> AsyncIOMotorDatabase:
    global _client, _db
    if _db is None:
        client = get_client()
        db_name = os.getenv("DB_NAME", "homegrow")
        _db = client[db_name]
    return _db


def reset_connection():
    """Force-close the Motor client so the next get_db() creates a fresh connection."""
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
