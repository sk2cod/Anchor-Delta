"""
Cache key generation and hashtag rotation log (Blueprint §8, Decision #12).

Single source of truth for the two existing cache layers' key generation
(writer output cache in writer.py, render cache in renderer.py) and the
previously-unimplemented third layer — the hashtag rotation log.
"""

import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
ROTATION_LOG_PATH = REPO_ROOT / "outputs" / "hashtag_rotation.json"
MAX_ROTATION_HISTORY = 10


def writer_cache_key(
    card_id: str,
    card_version: str,
    prompt_version: str,
    slot_plan_hash: str,
) -> str:
    """
    Stable cache key for CarouselWriter output.
    Keyed by card content + prompt version + slot structure.
    """
    raw = "|".join([card_id, card_version, prompt_version, slot_plan_hash])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def render_cache_key(
    template_id: str,
    headline: str,
    body: str,
    accent: str,
    theme: str,
    brand_version: str = "1.0",
) -> str:
    """
    Stable cache key for rendered slide PNGs.
    brand_version invalidates all renders when CSS changes.
    """
    raw = "|".join([template_id, headline, body, accent, theme, brand_version])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def load_rotation_log() -> list[list[str]]:
    """Load last N hashtag sets from rotation log."""
    if not ROTATION_LOG_PATH.exists():
        return []
    with open(ROTATION_LOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_rotation_log(log: list[list[str]]) -> None:
    """Save updated rotation log to disk."""
    ROTATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(ROTATION_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


def record_hashtag_use(hashtags: list[str]) -> None:
    """
    Append a hashtag set to the rotation log.
    Trims to MAX_ROTATION_HISTORY entries.
    """
    log = load_rotation_log()
    log.append(list(hashtags))
    log = log[-MAX_ROTATION_HISTORY:]
    save_rotation_log(log)


def get_recent_hashtags(n: int = 3) -> list[set[str]]:
    """
    Return the last n hashtag sets as sets for
    overlap checking in HashtagBuilder.
    """
    log = load_rotation_log()
    return [set(entry) for entry in log[-n:]]
