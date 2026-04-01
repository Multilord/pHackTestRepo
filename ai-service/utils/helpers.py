"""
utils/helpers.py
Shared utility functions for the HomeGrow AI Engine.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional, Tuple

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
    # Remove ```json ... ``` or ``` ... ``` blocks
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    # Remove bare 'json' prefix before {
    text = re.sub(r"^json\s*(?=\{)", "", text, flags=re.IGNORECASE)
    return text.strip()


def parse_json_safe(text: str) -> Optional[dict]:
    if not text:
        logger.warning("parse_json_safe received empty string.")
        return None

    # Gemini sometimes emits \' (invalid JSON) — normalise to plain '
    text = text.replace("\\'", "'")

    def _try_parse(s: str) -> Optional[dict]:
        try:
            result = json.loads(s)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        return None

    # Attempt 1: direct parse
    result = _try_parse(text)
    if result:
        return result

    # Attempt 2: strip fences and retry (in case they weren't stripped earlier)
    cleaned = strip_json_fences(text)
    result = _try_parse(cleaned)
    if result:
        return result

    # Attempt 3: extract first outermost { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        result = _try_parse(match.group(0))
        if result:
            logger.info("Recovered JSON via substring extraction.")
            return result

    logger.warning(f"Failed to parse JSON. First 300 chars: {text[:300]!r}")
    return None


def clamp_confidence(value: int) -> int:
    """Clamp confidence score to [10, 98] to avoid misleading 0% or 100% extremes."""
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
