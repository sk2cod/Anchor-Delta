"""
ImageGenerator — AI-generated, duotone-treated cover images (Decision #64).

Promoted from tests/carousel/test_new_cover.py, where the gpt-image-1 +
duotone treatment was iteratively validated against real Supabase cards
across several rounds this session.

Uses OPENAI_API_KEY — a separate provider from the CAROUSEL_ANTHROPIC_API_KEY
Sonnet/Haiku calls elsewhere in this package. Never raises: any failure
(missing key, network error, API error, decode error) is caught, logged,
and surfaced as a None return so the caller can fall back to a
typography-only cover slide (same philosophy as the Decision #54/#56/#63
"never crash on a soft dependency" guards).

Images are saved to disk (outputs/cover_images/) and referenced by file
path in the returned ImageAsset, never inlined as base64 — the persisted
CarouselSpec (Supabase carousels.spec, a jsonb column) would otherwise
bloat by 1-3MB per row for a value nothing needs at query time.
"""

import io
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from carousel.layout_picker import DOMAIN_ACCENTS
from carousel.models import ImageAsset

load_dotenv()

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "outputs" / "cover_images"

SHADOW_HEX = "#1A1612"  # brand background tone — the duotone shadow colour
IMAGE_MODEL = "gpt-image-1"
IMAGE_TIMEOUT_SECONDS = 90.0  # bounded — a hanging call must degrade to the
# None-fallback within a predictable window, not block the whole request.
# Was 45s; raised after real "Request timed out" failures once size moved
# 1024x1024 -> 1024x1536 (50% more pixels at quality="high" routinely
# pushed real generation time past the old bound).
DUOTONE_GAMMA = 0.55  # Decision #71 — was 0.70; real generations were
# reading as "extremely dark, hard to tell what it is" (confirmed against
# actual saved cover images). 0.70 wasn't brightening the raw gpt-image-1
# output enough for most pixels to reach the lighter half of the
# shadow->accent gradient below.

IMAGE_QUALITY = "high"
IMAGE_SIZE = "1024x1536"

# Decision #74 — real gpt-image-1 pricing, user-supplied from OpenAI's
# current price sheet (2026-07-11). Flat per (quality, size) tier, not
# linear per-token the way Anthropic's text models are — gpt-image-1's
# own usage response does return token counts, but OpenAI bills this
# model per-image at these tiers, so a lookup table is the correct,
# precise cost source, not a token-rate estimate. Previously this
# entire cost was an unverified guess (~$0.01-00.02, written once in a
# docstring in Decision #64 and never checked against a real bill) —
# off by 12-25x from the real $0.25 rate at the quality/size this
# pipeline actually uses.
IMAGE_PRICING_USD = {
    ("low", "1024x1024"): 0.011,
    ("low", "1024x1536"): 0.016,
    ("low", "1536x1024"): 0.016,
    ("medium", "1024x1024"): 0.042,
    ("medium", "1024x1536"): 0.063,
    ("medium", "1536x1024"): 0.063,
    ("high", "1024x1024"): 0.167,
    ("high", "1024x1536"): 0.25,
    ("high", "1536x1024"): 0.25,
}

# Descriptive colour words / tone words for the DALL-E prompt text —
# distinct from DOMAIN_ACCENTS (hex, reused from layout_picker rather than
# duplicated here) since prompt text needs words, not hex codes.
DOMAIN_ACCENT_WORD = {
    "world": "amber",
    "finance": "silver-blue",
    "ai_tech": "electric cyan",
}
DOMAIN_TONE = {
    "world": "warm brown",
    "finance": "cool grey",
    "ai_tech": "deep teal-black",
}


def apply_duotone(pil_image, shadow_hex: str, highlight_hex: str, gamma: float = 0.7):
    """
    Convert image to duotone using shadow and highlight colours.
    gamma < 1 brightens shadows/midtones before the duotone mapping — the
    raw gpt-image-1 outputs skew dark (every prompt below explicitly
    requests a near-black background), which combined with a purely
    linear duotone map made early renders read as underexposed.
    """
    from PIL import Image

    grey = pil_image.convert("L")
    grey = grey.point(lambda p: min(255, int(255 * ((p / 255) ** gamma))))

    def hex_to_rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    shadow = hex_to_rgb(shadow_hex)
    highlight = hex_to_rgb(highlight_hex)

    lut_r = [int(shadow[0] + (highlight[0] - shadow[0]) * i / 255) for i in range(256)]
    lut_g = [int(shadow[1] + (highlight[1] - shadow[1]) * i / 255) for i in range(256)]
    lut_b = [int(shadow[2] + (highlight[2] - shadow[2]) * i / 255) for i in range(256)]

    r = grey.point(lut_r)
    g = grey.point(lut_g)
    b = grey.point(lut_b)
    return Image.merge("RGB", (r, g, b))


def generate_cover_image(visual_subject: str, is_person: bool, domain: str) -> Optional[ImageAsset]:
    """
    Generate a cover image for this story via gpt-image-1, apply the brand
    duotone treatment, and save it to outputs/cover_images/. Returns an
    ImageAsset(source="ai_generated", url=<file path>, treatment="duotone",
    cost_usd=<real price from IMAGE_PRICING_USD>) on success, or None on
    any failure — never raises.
    Cost: $0.25 per image at the current IMAGE_QUALITY/IMAGE_SIZE
    ("high"/"1024x1536") — see IMAGE_PRICING_USD (Decision #74). Not
    $0.01-0.02 as earlier versions of this docstring claimed; that
    figure was an unverified guess, off by 12-25x from OpenAI's real
    price sheet.
    """
    import base64

    accent_hex = DOMAIN_ACCENTS[domain]
    accent_word = DOMAIN_ACCENT_WORD[domain]
    domain_tone = DOMAIN_TONE[domain]

    if is_person:
        prompt = (
            f"Graphic portrait illustration of {visual_subject}, bold ink and "
            f"charcoal style, sharp detailed features, serious authoritative "
            f"expression, clearly lit and easy to make out, moody {domain_tone} "
            f"background, {accent_word} accent lighting catching the edges of "
            f"the face, strong but readable contrast, editorial magazine cover "
            f"art, no text, no logos, no watermarks, aspect ratio 9:16, "
            f"vertical orientation"
        )
    else:
        prompt = (
            f"Minimalist cinematic editorial shot of {visual_subject}, clean "
            f"sharp composition, subject clearly lit and easy to identify, "
            f"moody {domain_tone} background, {accent_word} accent lighting "
            f"tracing key elements, strong but readable contrast, editorial "
            f"magazine cover style, no text, no logos, no watermarks, aspect "
            f"ratio 9:16, vertical orientation"
        )

    try:
        import openai
        from PIL import Image

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment/.env")

        client = openai.OpenAI(api_key=api_key, timeout=IMAGE_TIMEOUT_SECONDS)
        response = client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=IMAGE_SIZE,
            quality=IMAGE_QUALITY,
            n=1,
        )
        b64_source = response.data[0].b64_json
        raw_image = Image.open(io.BytesIO(base64.b64decode(b64_source)))
        duotoned = apply_duotone(raw_image, SHADOW_HEX, accent_hex, gamma=DUOTONE_GAMMA)

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / f"{uuid.uuid4().hex}.png"
        duotoned.save(output_path, format="PNG")

        cost_usd = IMAGE_PRICING_USD.get((IMAGE_QUALITY, IMAGE_SIZE))
        if cost_usd is None:
            # Should never happen with the constants above, but a missing
            # price-table entry must never crash generation over a $0 vs.
            # unknown-cost bookkeeping gap.
            logger.warning(
                "No IMAGE_PRICING_USD entry for (%r, %r) — cost_usd will be None.",
                IMAGE_QUALITY, IMAGE_SIZE,
            )

        return ImageAsset(
            source="ai_generated",
            url=str(output_path),
            treatment="duotone",
            cost_usd=cost_usd,
        )

    except Exception as e:
        logger.warning("Cover image generation failed for domain=%r: %s", domain, e)
        return None
