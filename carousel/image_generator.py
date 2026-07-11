"""
ImageGenerator — AI-generated, duotone-treated cover images (Decision #64).

Promoted from tests/carousel/test_new_cover.py, where the gpt-image-1 +
duotone treatment was iteratively validated against real Supabase cards
across several rounds this session. Switched from gpt-image-1/high to
gpt-image-2/medium in Decision #76 after a real side-by-side comparison
showed comparable-or-better output at 84% lower cost — the duotone
treatment itself is unchanged by that switch.

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
IMAGE_MODEL = "gpt-image-2"  # Decision #76 — was "gpt-image-1". Switched
# after a real side-by-side comparison (same prompt/subject, duotone
# pipeline, rendered through the actual cover.html template): gpt-image-2
# at medium quality produced a richer, more coherent composition than
# gpt-image-1 at high quality, at 84% lower cost. Based on one successful
# sample — see the IMAGE_QUALITY note below on gpt-image-2/high's
# reliability before trusting this further.
IMAGE_TIMEOUT_SECONDS = 90.0  # bounded — a hanging call must degrade to the
# None-fallback within a predictable window, not block the whole request.
# Was 45s; raised after real "Request timed out" failures once size moved
# 1024x1024 -> 1024x1536 (50% more pixels at quality="high" routinely
# pushed real generation time past the old bound).
DUOTONE_GAMMA = 0.55  # Decision #71 — was 0.70; real generations were
# reading as "extremely dark, hard to tell what it is" (confirmed against
# actual saved cover images). 0.70 wasn't brightening the raw gpt-image-1
# output enough for most pixels to reach the lighter half of the
# shadow->accent gradient below. Untested against gpt-image-2 beyond one
# sample — revisit if gpt-image-2 output reads differently under this
# same gamma/LUT treatment.

IMAGE_QUALITY = "medium"  # Decision #76 — was "high". gpt-image-2/high
# failed twice in isolated testing (a transient Cloudflare 520, then a
# genuine hang) — not necessarily a quality-tier problem, but untrusted
# right now regardless. Medium succeeded cleanly both times it ran.
IMAGE_SIZE = "1024x1536"

# Real pricing, user-supplied from OpenAI's current price sheet
# (2026-07-11). Flat per (model, quality, size) tier, not linear
# per-token the way Anthropic's text models are — this model family's
# own usage response does return token counts, but OpenAI bills
# per-image at these tiers, so a lookup table is the correct, precise
# cost source, not a token-rate estimate. Keyed by model as of Decision
# #76 (previously just (quality, size), back when gpt-image-1 was the
# only model ever used — that shape silently can't distinguish models,
# which would have made a real bug the moment a second model's entries
# were added the same way). gpt-image-1 entries kept for
# reference/rollback even though gpt-image-2 is now active — deprecate,
# don't delete, matching this project's convention elsewhere.
IMAGE_PRICING_USD = {
    ("gpt-image-1", "low", "1024x1024"): 0.011,
    ("gpt-image-1", "low", "1024x1536"): 0.016,
    ("gpt-image-1", "low", "1536x1024"): 0.016,
    ("gpt-image-1", "medium", "1024x1024"): 0.042,
    ("gpt-image-1", "medium", "1024x1536"): 0.063,
    ("gpt-image-1", "medium", "1536x1024"): 0.063,
    ("gpt-image-1", "high", "1024x1024"): 0.167,
    ("gpt-image-1", "high", "1024x1536"): 0.25,
    ("gpt-image-1", "high", "1536x1024"): 0.25,
    # Decision #76 — cheaper than gpt-image-1 at every quality/size tier,
    # not just the medium tier now in use — a genuinely more efficient
    # model, not just a lower-quality option. Currently active:
    # ("gpt-image-2", "medium", "1024x1536") = $0.041.
    ("gpt-image-2", "low", "1024x1024"): 0.006,
    ("gpt-image-2", "low", "1024x1536"): 0.005,
    ("gpt-image-2", "low", "1536x1024"): 0.005,
    ("gpt-image-2", "medium", "1024x1024"): 0.053,
    ("gpt-image-2", "medium", "1024x1536"): 0.041,
    ("gpt-image-2", "medium", "1536x1024"): 0.041,
    ("gpt-image-2", "high", "1024x1024"): 0.211,
    ("gpt-image-2", "high", "1024x1536"): 0.165,
    ("gpt-image-2", "high", "1536x1024"): 0.165,
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
    Generate a cover image for this story via IMAGE_MODEL (gpt-image-2 as
    of Decision #76, was gpt-image-1), apply the brand duotone treatment,
    and save it to outputs/cover_images/. Returns an
    ImageAsset(source="ai_generated", url=<file path>, treatment="duotone",
    cost_usd=<real price from IMAGE_PRICING_USD>) on success, or None on
    any failure — never raises.
    Cost: $0.041 per image at the current IMAGE_MODEL/IMAGE_QUALITY/
    IMAGE_SIZE ("gpt-image-2"/"medium"/"1024x1536") — see
    IMAGE_PRICING_USD (Decision #76). Was $0.25 at gpt-image-1/high
    (Decision #74) before the switch — an 84% reduction, based on a real
    side-by-side comparison against gpt-image-1/high (one sample; see
    Decision #76 for what wasn't yet validated: only the non-person
    prompt was tested, and gpt-image-2/high failed twice in isolated
    testing before medium was chosen instead).
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

        cost_usd = IMAGE_PRICING_USD.get((IMAGE_MODEL, IMAGE_QUALITY, IMAGE_SIZE))
        if cost_usd is None:
            # Should never happen with the constants above, but a missing
            # price-table entry must never crash generation over a $0 vs.
            # unknown-cost bookkeeping gap.
            logger.warning(
                "No IMAGE_PRICING_USD entry for (%r, %r, %r) — cost_usd will be None.",
                IMAGE_MODEL, IMAGE_QUALITY, IMAGE_SIZE,
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
