"""
HomeGrow AI Engine — main.py
Person C: FastAPI microservice for plant recommendations and disease diagnosis.

Architecture:
  - Receives HTTP calls from Person D's Express backend (never from frontend directly)
  - Calls Gemini Vision API
  - Returns stable, schema-safe JSON
  - Does NOT connect to MongoDB — Person D's backend owns all persistence

Run:
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.recommend import router as recommend_router
from routes.diagnose import router as diagnose_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="HomeGrow AI Engine",
    description=(
        "AI microservice for HomeGrow. Provides plant recommendations and "
        "plant disease diagnosis powered by Google Gemini. "
        "Called by Person D's Express backend only — never directly by the frontend."
    ),
    version="2.0.0",
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

app.include_router(recommend_router, prefix="/ai", tags=["Recommendations"])
app.include_router(diagnose_router, prefix="/ai", tags=["Diagnosis"])


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "ok",
        "service": os.getenv("AI_SERVICE_NAME", "HomeGrow AI Engine"),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    }


@app.on_event("startup")
async def on_startup():
    gemini_key_set = bool(os.getenv("GEMINI_API_KEY"))
    logger.info("HomeGrow AI Engine starting up")
    logger.info(f"GEMINI_API_KEY set: {gemini_key_set}")
    logger.info(f"GEMINI_MODEL: {os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')}")
    logger.info(f"BACKEND_URL (reference): {os.getenv('BACKEND_URL', 'http://localhost:3000')}")
    if not gemini_key_set:
        logger.warning("GEMINI_API_KEY is not set — AI endpoints will fail!")
