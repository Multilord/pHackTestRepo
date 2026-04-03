"""Architecture:
FastAPI + MongoDB (Motor async) + Gemini AI
"""

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from utils.db import connect_db, close_db

# Routers
from routes.plants import router as plants_router
from routes.recommend import router as recommend_router
from routes.diagnose import router as diagnose_router
from routes.user_plants import router as user_plants_router
from routes.auth import router as auth_router

load_dotenv()

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")

# ---------------- FastAPI App ----------------
app = FastAPI(
    title="HomeGrow AI Engine",
    description="AI + MongoDB backend for plant recommendation and diagnosis system",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # change in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Routers ----------------
app.include_router(auth_router, prefix="/api", tags=["Auth"])
app.include_router(plants_router, prefix="/api", tags=["Plants"])
app.include_router(recommend_router, prefix="/api", tags=["Recommendations"])
app.include_router(diagnose_router, prefix="/api", tags=["Diagnosis"])
app.include_router(user_plants_router, prefix="/api", tags=["User Plants"])


# ---------------- Startup & Shutdown ----------------
@app.on_event("startup")
async def startup():
    logger.info("Starting HomeGrow AI Engine...")

    # Connect DB
    await connect_db()
    logger.info("MongoDB connected successfully")

    # Env checks
    gemini_key = bool(os.getenv("GEMINI_API_KEY"))
    mongo_uri = bool(os.getenv("MONGODB_URI"))

    logger.info(f"GEMINI_API_KEY set: {gemini_key}")
    logger.info(f"GEMINI_MODEL: {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}")
    logger.info(f"MONGODB_URI set: {mongo_uri}")
    logger.info(f"DB_NAME: {os.getenv('MONGODB_DB', 'homegrow')}")

    if not gemini_key:
        logger.warning("GEMINI_API_KEY is missing!")
    if not mongo_uri:
        logger.warning("MONGODB_URI is missing!")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Shutting down HomeGrow AI Engine...")
    await close_db()
    logger.info("MongoDB connection closed")


# ---------------- Health Check ----------------
@app.get("/health", tags=["Health"])
async def health_check():
    """
    Check API + DB status
    """
    from utils.db import get_db

    db_status = "unknown"
    db_error = None

    try:
        db = get_db()
        await db.command("ping")
        db_status = "connected"
    except Exception as e:
        db_status = "error"
        db_error = str(e)

    return {
        "status": "ok",
        "service": os.getenv("AI_SERVICE_NAME", "HomeGrow AI Engine"),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        "db": db_status,
        "dbError": db_error if db_error else None,
    }