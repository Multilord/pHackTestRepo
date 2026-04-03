"""
routes/auth.py
POST /api/auth/register  — create a new user account
POST /api/auth/login     — authenticate and return a JWT

Architecture: FastAPI -> MongoDB Atlas -> JWT
- Passwords are hashed with bcrypt
- Returns JWT token + user info the frontend stores in localStorage
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from utils.db import get_db
import hashlib

load_dotenv()
logger = logging.getLogger(__name__)
router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto",  bcrypt__rounds=10 )

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-secret-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 30

AGRO_ACCESS_CODE = os.getenv("AGRO_ACCESS_CODE", "AGRO2024")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    password: str = Field(..., min_length=6, description="Password (min 6 chars)")
    role: str = Field("user", description="'user' or 'agronomist'")
    accessCode: Optional[str] = Field(None, description="Required for agronomist role")
    organization: Optional[str] = Field(None, description="Organization name (agronomist only)")


class LoginRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")
    role: str = Field("user", description="'user' or 'agronomist'")
    accessCode: Optional[str] = Field(None, description="Required for agronomist role")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_token(user_id: str, role: str) -> str:
    payload = {
        "userId": user_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _auth_response(user: dict, token: str) -> dict:
    return {
        "token": token,
        "role": user["role"],
        "name": user["name"],
        "userId": str(user["_id"]),
    }

def hash_password(password: str):
    hashed = hashlib.sha256(password.encode()).hexdigest()
    return pwd_context.hash(hashed)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/auth/register", status_code=201)
async def register(req: RegisterRequest):
    """Register a new user or agronomist account."""
    db = get_db()

    # Validate role
    if req.role not in ("user", "agronomist"):
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'agronomist'.")

    # Validate agronomist access code
    if req.role == "agronomist":
        if not req.accessCode or req.accessCode.strip() != AGRO_ACCESS_CODE:
            raise HTTPException(status_code=403, detail="Invalid agronomist access code.")

    # Check duplicate email (same role)
    existing = await db.users.find_one({"email": req.email.lower().strip(), "role": req.role})
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    
    # Build document
    doc = {
        "name": req.name.strip(),
        "email": req.email.lower().strip(), 
        "password": hash_password(req.password),
        "role": req.role,
        "createdAt": datetime.now(timezone.utc),
    }
    if req.organization:
        doc["organization"] = req.organization.strip()

    try:
        result = await db.users.insert_one(doc)
        doc["_id"] = result.inserted_id
        token = _create_token(str(result.inserted_id), req.role)
        logger.info(f"New {req.role} registered: {req.email} (_id={result.inserted_id})")
        return _auth_response(doc, token)
    except Exception as e:
        logger.error(f"Failed to register user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create account.")

@router.post("/auth/login")
async def login(req: LoginRequest):
    """Authenticate a user and return a JWT."""
    db = get_db()

    # Validate role
    if req.role not in ("user", "agronomist"):
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'agronomist'.")
    
    # Validate agronomist access code early (before hitting DB)
    if req.role == "agronomist":
        if not req.accessCode or req.accessCode.strip() != AGRO_ACCESS_CODE:
            raise HTTPException(status_code=403, detail="Invalid agronomist access code.")

    # Find user
    user = await db.users.find_one({"email": req.email.lower().strip(), "role": req.role})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    # Verify password (must match hash_password: sha256 then bcrypt)
    hashed_input = hashlib.sha256(req.password.encode()).hexdigest()
    if not pwd_context.verify(hashed_input, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    token = _create_token(str(user["_id"]), user["role"])
    logger.info(f"{user['role']} logged in: {user['email']} (_id={user['_id']})")
    return _auth_response(user, token)

@router.get("/auth/me")
async def get_me(authorization: Optional[str] = None):
    """
    Decode the JWT and return the current user's profile.
    Pass the token as: Authorization: Bearer <token>
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")

    db = get_db()
    try:
        user = await db.users.find_one({"_id": ObjectId(payload["userId"])})
    except (InvalidId, Exception):
        raise HTTPException(status_code=401, detail="User not found.")

    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    return {
        "userId": str(user["_id"]),
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "organization": user.get("organization"),
        "createdAt": user["createdAt"].isoformat() if "createdAt" in user else None,
    }