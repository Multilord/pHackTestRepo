"""
HomeGrow AI Engine — main.py

Architecture: FastAPI -> MongoDB Atlas + Google Gemini AI
Endpoints are called directly by the frontend or test UI.

Run:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.plants import router as plants_router
from routes.recommend import router as recommend_router
from routes.diagnose import router as diagnose_router
from routes.user_plants import router as user_plants_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="HomeGrow AI Engine",
    description=(
        "AI + database backend for HomeGrow. "
        "Connects directly to MongoDB Atlas and Google Gemini. "
        "Provides plant recommendations, disease diagnosis, and user plant tracking."
    ),
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Primary API routes
app.include_router(plants_router, prefix="/api", tags=["Plants"])
app.include_router(recommend_router, prefix="/api", tags=["Recommendations"])
app.include_router(diagnose_router, prefix="/api", tags=["Diagnosis"])
app.include_router(user_plants_router, prefix="/api", tags=["User Plants"])


@app.get("/health", tags=["Health"])
async def health_check():
    """Service health check including DB connectivity."""
    from utils.db import get_db

    db_status = "unknown"
    db_error = None
    try:
        db = get_db()
        # Motor ping: run a lightweight command
        await db.command("ping")
        db_status = "connected"
    except Exception as e:
        db_status = "error"
        db_error = str(e)[:120]

    return {
        "status": "ok",
        "service": os.getenv("AI_SERVICE_NAME", "HomeGrow AI Engine"),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "db": db_status,
        **({"dbError": db_error} if db_error else {}),
    }


@app.on_event("startup")
async def on_startup():
    gemini_key_set = bool(os.getenv("GEMINI_API_KEY"))
    mongo_uri_set = bool(os.getenv("MONGODB_URI"))
    logger.info("HomeGrow AI Engine starting up (v3.0.0 — direct MongoDB integration)")
    logger.info(f"GEMINI_API_KEY set: {gemini_key_set}")
    logger.info(f"GEMINI_MODEL: {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}")
    logger.info(f"MONGODB_URI set: {mongo_uri_set}")
    logger.info(f"DB_NAME: {os.getenv('DB_NAME', 'homegrow')}")
    if not gemini_key_set:
        logger.warning("GEMINI_API_KEY is not set — AI endpoints will fail!")
    if not mongo_uri_set:
        logger.warning("MONGODB_URI is not set — database endpoints will fail!")
