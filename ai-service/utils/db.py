"""
utils/db.py
MongoDB connection for the HomeGrow AI service.
"""

import logging
import os
import certifi
from dotenv import load_dotenv
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

load_dotenv()

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_db = None


def get_db():
    global _client, _db
    if _db is not None:
        return _db

    uri = os.getenv("MONGODB_URI")
    if not uri:
        logger.error("MONGODB_URI environment variable is not set.")
        return None
    try:
        _client = MongoClient(uri, server_api=ServerApi("1"), tlsCAFile=certifi.where())
        _client.admin.command("ping")
        _db = _client["homegrow"]
        logger.info("MongoDB connected successfully.")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        _db = None

    return _db
