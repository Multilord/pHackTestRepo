"""
utils/helpers.py
Shared utility functions used across routes.
"""

import json
import logging
import os
import re
from typing import Any

from bson import ObjectId

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def strip_json_fences(text: str) -> str:
    """Remove markdown code fences (```json ... ```) from AI responses."""
    text = text.strip()
    # Remove ```json or ``` fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json_safe(text: str) -> dict | list | None:
    """Parse JSON without raising — returns None on failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def extract_base64_data(image_str: str) -> tuple[str, str]:
    """
    Accept either:
      - a raw base64 string → returns ("image/jpeg", base64_str)
      - a data URL like "data:image/png;base64,<data>" → returns ("image/png", base64_str)
    """
    image_str = image_str.strip()
    if image_str.startswith("data:"):
        match = re.match(r"data:([^;]+);base64,(.+)", image_str, re.DOTALL)
        if not match:
            raise ValueError("Malformed data URL — expected data:<mime>;base64,<data>")
        return match.group(1), match.group(2).strip()
    # Raw base64 — assume JPEG
    return "image/jpeg", image_str


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def clamp_confidence(value: int, lo: int = 1, hi: int = 99) -> int:
    """Clamp a confidence score to [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Prompt loader
# ---------------------------------------------------------------------------


def load_prompt(filename: str) -> str:
    """Load a .txt prompt file from the prompts/ directory."""
    path = os.path.join(PROMPTS_DIR, filename)
    if not os.path.isfile(path):
        raise RuntimeError(f"Prompt file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


# ---------------------------------------------------------------------------
# MongoDB serialisation helpers
# ---------------------------------------------------------------------------


def _serialise_value(v: Any) -> Any:
    if isinstance(v, ObjectId):
        return str(v)
    if hasattr(v, "isoformat"):       # datetime
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _serialise_value(val) for k, val in v.items()}
    if isinstance(v, list):
        return [_serialise_value(i) for i in v]
    return v


def serialize_doc(doc: dict) -> dict:
    """Convert a MongoDB document to a JSON-safe dict (ObjectId → str, datetime → ISO)."""
    result = {}
    for k, v in doc.items():
        key = "id" if k == "_id" else k
        result[key] = _serialise_value(v)
    return result


def serialize_list(docs: list[dict]) -> list[dict]:
    """Serialise a list of MongoDB documents."""
    return [serialize_doc(d) for d in docs]
