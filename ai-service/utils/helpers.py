"""
utils/helpers.py
Shared utility functions for the HomeGrow AI Engine.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

from bson import ObjectId

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(filename: str) -> str:
    prompt_path = PROMPTS_DIR / filename
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                raise RuntimeError(f"Prompt file is empty: {filename}")
            return content
    except FileNotFoundError:
        raise RuntimeError(f"Missing prompt file '{filename}'. Expected at: {prompt_path}")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to load prompt '{filename}': {e}")


def strip_json_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    text = re.sub(r"^json\s*(?=\{)", "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_json_safe(text: str) -> Optional[dict]:
    if not text:
        logger.warning("parse_json_safe received empty string.")
        return None

    text = text.replace("\\'", "'")

    def _try_parse(s: str) -> Optional[dict]:
        try:
            result = json.loads(s)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        return None

    result = _try_parse(text)
    if result:
        return result

    cleaned = strip_json_fences(text)
    result = _try_parse(cleaned)
    if result:
        return result

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        result = _try_parse(match.group(0))
        if result:
            logger.info("Recovered JSON via substring extraction.")
            return result

    logger.warning(f"Failed to parse JSON. First 300 chars: {text[:300]!r}")
    return None


def clamp_confidence(value: int) -> int:
    """Clamp confidence score to [10, 98]."""
    return max(10, min(98, value))


def extract_base64_data(image_str: str) -> Tuple[str, str]:
    image_str = image_str.strip()
    data_url_re = re.compile(
        r"^data:(image/(?:jpeg|jpg|png|gif|webp));base64,(.+)$",
        re.DOTALL | re.IGNORECASE,
    )
    match = data_url_re.match(image_str)
    if match:
        raw_mime = match.group(1).lower()
        media_type = "image/jpeg" if raw_mime == "image/jpg" else raw_mime
        return media_type, match.group(2).strip()
    return "image/jpeg", image_str


def _serialize_value(v: Any) -> Any:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return serialize_doc(v)
    if isinstance(v, list):
        return [_serialize_value(i) for i in v]
    return v


def serialize_doc(doc: Optional[dict]) -> Optional[dict]:
    """Recursively convert ObjectId/datetime values to JSON-safe types."""
    if doc is None:
        return None
    return {k: _serialize_value(v) for k, v in doc.items()}


def serialize_list(docs: list) -> list:
    """Serialize a list of MongoDB documents."""
    return [serialize_doc(d) for d in docs]
