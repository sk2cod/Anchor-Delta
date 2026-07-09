#!/usr/bin/env python3
"""
New cover layout preview script — pulls real cards from Supabase,
generates one-idea cover headlines + completing sub-headings via the
writer_v1_6.md candidate prompt (NOT wired into production —
carousel/writer.py still runs writer_v1_5.md), derives a story-specific
visual subject and generates AI sketch/imagery via gpt-image-1, and
renders the new image-forward cover layout (no kicker, headline at 65%
down, sub-heading below the rule) via Playwright.

Phase A per spec.md (2026-07-09): punchier one-line headlines (max 8
words, no two-sentence/colon structure), sub-heading re-introduced,
and image generation now uses a documentary-filmmaker-derived visual
subject instead of the raw entity label.

Standalone and self-contained: imports nothing from carousel/*.py or
db/*.py. The Supabase query, Playwright render, Pillow downscale, and
duotone treatment are all replicated inline (duotone/DALL-E pattern
matches tests/carousel/test_portrait_hook.py, read as reference).

Zero production impact — writer_v1_5.md stays active, carousel/writer.py
is untouched, the Streamlit app still runs the old pipeline exactly.

Requires ANTHROPIC/OPENAI/SUPABASE keys in .env (see check below).

Usage: python tests/carousel/test_new_cover.py
"""

import base64
import io
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "test_new_cover.html"
WRITER_PROMPT_PATH = REPO_ROOT / "carousel" / "prompts" / "writer_v1_6.md"
OUTPUT_DIR = REPO_ROOT / "outputs" / "renders"

RENDER_WIDTH = 2160
RENDER_HEIGHT = 2700
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1350

SHADOW_HEX = "#1A1612"  # brand background tone — the duotone shadow colour
SONNET_MODEL = "claude-sonnet-4-6"
HAIKU_MODEL = "claude-haiku-4-5-20251001"

DOMAINS = ["world", "finance", "ai_tech"]

DOMAIN_TAGS = {
    "world": "WORLD",
    "finance": "FINANCE",
    "ai_tech": "AI & TECH",
}
DOMAIN_ACCENT_HEX = {
    "world": "#C8813A",
    "finance": "#A8B8C8",
    "ai_tech": "#00D9FF",
}
# Descriptive colour words for the DALL-E prompt text (distinct from the
# hex values above, which drive the template CSS + duotone highlight).
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

load_dotenv(REPO_ROOT / ".env")

# Small, single-purpose entity-detection prompt — deliberately NOT the
# same thing as carousel/context_builder.py's full entity/quote/number
# extraction (that's production logic, not replicated here per task
# scope). Haiku, matching the production Decision #07 split of Haiku
# for extraction work, Sonnet for creative writing.
ENTITY_SYSTEM_PROMPT = """You identify the single primary named entity \
a news story is about — the one person, place, or concept the story \
centres on. Return only valid JSON, no preamble, no markdown fences.

{"entity": "the primary named entity, as a short noun phrase", \
"is_person": true or false}

If the story has no single dominant named entity, use the most \
central concept or place mentioned in the title instead. Never leave \
entity empty."""

# spec.md Phase A, item 3 — the raw entity label ("Ukraine", "Canada")
# produces generic/stereotyped DALL-E imagery unrelated to the specific
# story. This is a deliberately separate call from entity detection
# above: entity detection still feeds the writer's own primary_entity
# input; this one is purely for image generation, framed the way the
# spec asks — "what would a documentary filmmaker actually put on
# screen for this story", not the country/company name.
VISUAL_SUBJECT_SYSTEM_PROMPT = """You are a documentary filmmaker deciding what to actually film for \
this story. Identify the single most visually distinctive, story-specific \
element you would put on screen — never a generic stand-in for the \
country or company name (not "Russia", not "a submarine" in the \
abstract), but the concrete detail unique to THIS story.

If the story centres on a specific named individual as its main \
character, the subject is that person (for a recognisable portrait).
Otherwise, describe the specific object, place, or scene a documentary \
would actually show — grounded in what this story is literally about.

Return only valid JSON, no preamble, no markdown fences.

{"visual_subject": "the specific visual subject, as a short descriptive phrase", \
"is_person": true or false}

Never leave visual_subject empty."""


def check_dependencies():
    missing = []
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright")
    try:
        import PIL  # noqa: F401
    except ImportError:
        missing.append("pillow")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        missing.append("anthropic")
    try:
        import openai  # noqa: F401
    except ImportError:
        missing.append("openai")
    try:
        import supabase  # noqa: F401
    except ImportError:
        missing.append("supabase")

    if missing:
        print("Missing required dependencies: " + ", ".join(missing))
        print()
        print("Install with:")
        print(f"  pip install {' '.join(missing)}")
        if "playwright" in missing:
            print("  playwright install chromium")
        sys.exit(1)

    required_env = ["ANTHROPIC_API_KEY", "CAROUSEL_ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY"]
    missing_env = [k for k in required_env if not os.environ.get(k)]
    if missing_env:
        print("Missing required .env keys: " + ", ".join(missing_env))
        sys.exit(1)


def fetch_latest_card(supabase_client, domain: str) -> dict | None:
    """Most recently created card for this domain (no is_archived filter
    — most recent cards in this dataset are archived, and the task only
    asked for "most recently created", not "most recently active").
    Returns a plain dict (id, umbrella_title, anchor_text, domain,
    transmission_text) or None if no card exists for this domain."""
    card_rows = (
        supabase_client.table("cards")
        .select("*")
        .eq("domain", domain)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    ).data
    if not card_rows:
        return None
    card_row = card_rows[0]

    trans_rows = (
        supabase_client.table("transmissions")
        .select("*")
        .eq("card_id", card_row["id"])
        .execute()
    ).data
    transmission_text = trans_rows[0]["nodes_markdown"] if trans_rows else ""

    return {
        "id": card_row["id"],
        "umbrella_title": card_row["umbrella_title"],
        "anchor_text": card_row["anchor_text"],
        "domain": card_row["domain"],
        "transmission_text": transmission_text,
    }


def _strip_json_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def determine_primary_entity(client, card: dict) -> tuple[str, bool]:
    """Returns (entity_name, is_person). Falls back to umbrella_title
    (treated as not-a-person) on any failure, per task-specified
    fallback behaviour."""
    try:
        user_content = (
            f"TITLE: {card['umbrella_title']}\n\n"
            f"CONTEXT: {card['anchor_text']}\n\n"
            f"CHAIN: {card['transmission_text'][:500]}"
        )
        message = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200,
            system=ENTITY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        data = json.loads(_strip_json_fences(message.content[0].text))
        entity = (data.get("entity") or "").strip()
        if not entity:
            raise ValueError("empty entity")
        return entity, bool(data.get("is_person", False))
    except Exception as e:
        print(f"  WARNING: entity detection failed, using umbrella_title: {e}")
        return card["umbrella_title"], False


def determine_visual_subject(client, card: dict) -> tuple[str, bool]:
    """Returns (visual_subject, is_person) — a documentary-filmmaker-style
    story-specific subject for DALL-E, distinct from the plain entity
    label determine_primary_entity() returns. Falls back to
    umbrella_title (treated as not-a-person) on any failure."""
    try:
        user_content = (
            f"TITLE: {card['umbrella_title']}\n\n"
            f"CONTEXT: {card['anchor_text']}\n\n"
            f"CHAIN: {card['transmission_text'][:500]}"
        )
        message = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200,
            system=VISUAL_SUBJECT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        data = json.loads(_strip_json_fences(message.content[0].text))
        visual_subject = (data.get("visual_subject") or "").strip()
        if not visual_subject:
            raise ValueError("empty visual_subject")
        return visual_subject, bool(data.get("is_person", False))
    except Exception as e:
        print(f"  WARNING: visual subject derivation failed, using umbrella_title: {e}")
        return card["umbrella_title"], False


def generate_headline(client, card: dict, primary_entity: str) -> tuple[str, str, str]:
    """Returns (headline, emphasis_word, sub_heading) via writer_v1_6.md.
    Falls back to umbrella_title / empty emphasis_word / empty
    sub_heading on any failure."""
    try:
        system_prompt = WRITER_PROMPT_PATH.read_text(encoding="utf-8")
        user_content = (
            f"umbrella_title: {card['umbrella_title']}\n"
            f"anchor_text: {card['anchor_text']}\n"
            f"transmission_summary: {card['transmission_text'][:500]}\n"
            f"primary_entity: {primary_entity}\n"
            f"domain: {card['domain']}"
        )
        message = client.messages.create(
            model=SONNET_MODEL,
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        data = json.loads(_strip_json_fences(message.content[0].text))
        headline = (data.get("headline") or "").strip()
        emphasis_word = (data.get("emphasis_word") or "").strip()
        sub_heading = (data.get("sub_heading") or "").strip()
        if not headline:
            raise ValueError("empty headline")
        return headline, emphasis_word, sub_heading
    except Exception as e:
        print(f"  WARNING: headline generation failed, using umbrella_title: {e}")
        return card["umbrella_title"], "", ""


def apply_duotone(pil_image, shadow_hex, highlight_hex, gamma=0.7):
    """Convert image to duotone using shadow and highlight colours.
    Same base treatment as tests/carousel/test_portrait_hook.py, plus a
    gamma lift (gamma < 1 brightens shadows/midtones) applied to the
    greyscale layer before the duotone mapping — the raw gpt-image-1
    outputs skew dark (near-black backgrounds requested in every DALL-E
    prompt), which combined with a purely linear duotone map made
    renders read as underexposed. Per explicit user request."""
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


def generate_and_duotone_image(card: dict, visual_subject: str, is_person: bool) -> str:
    """Generate an image via gpt-image-1, apply the brand duotone
    treatment, return a base64 data URI. Returns "" (typography-only
    fallback) on any failure — never raises. visual_subject is the
    documentary-filmmaker-derived subject from determine_visual_subject(),
    not the raw entity label — spec.md Phase A item 3."""
    from PIL import Image

    domain = card["domain"]
    accent_hex = DOMAIN_ACCENT_HEX[domain]
    accent_word = DOMAIN_ACCENT_WORD[domain]
    domain_tone = DOMAIN_TONE[domain]

    if is_person:
        prompt = (
            f"Editorial pencil sketch portrait of {visual_subject}, detailed "
            f"recognisable features, serious authoritative expression, dark "
            f"near-black warm {domain_tone} background, dramatic chiaroscuro "
            f"with {accent_word} accent highlights, high contrast, editorial "
            f"magazine illustration style, no text, no logos, no watermarks, "
            f"portrait orientation"
        )
    else:
        prompt = (
            f"Cinematic dark editorial macro image of {visual_subject}, deep "
            f"near-black {domain_tone} background, {accent_word} accent light "
            f"tracing key elements, dramatic chiaroscuro, no text, no logos, "
            f"no watermarks, editorial magazine cover style, ultra high "
            f"contrast, portrait orientation"
        )

    try:
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment/.env")

        client = openai.OpenAI(api_key=api_key)
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            size="1024x1024",
            quality="high",
            n=1,
        )
        b64_source = response.data[0].b64_json
        raw_image = Image.open(io.BytesIO(base64.b64decode(b64_source)))
        duotoned = apply_duotone(raw_image, SHADOW_HEX, accent_hex)

        buffer = io.BytesIO()
        duotoned.save(buffer, format="PNG")
        b64_string = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{b64_string}"

    except Exception as e:
        print(f"  WARNING: image generation failed for {domain!r}: {e}")
        print("  Falling back to typography-only render (no image).")
        return ""


def _wrap_emphasis(headline: str, emphasis_word: str, accent_hex: str) -> str:
    """Wrap emphasis_word in an inline-styled <em>, case-insensitive
    whole-word match, per the template's explicit spec."""
    if not emphasis_word:
        return headline
    pattern = re.compile(r"\b" + re.escape(emphasis_word) + r"\b", re.IGNORECASE)
    replacement = (
        f'<em style="color:{accent_hex};font-style:italic;font-weight:700">'
        f"\\g<0></em>"
    )
    new_headline, count = pattern.subn(replacement, headline, count=1)
    return new_headline if count else headline


def render_cover(page, domain: str, card: dict, headline: str, emphasis_word: str, sub_heading: str, image_data_uri: str) -> Path:
    if not TEMPLATE_FILE.exists():
        print(f"Template not found: {TEMPLATE_FILE}")
        sys.exit(1)

    html = TEMPLATE_FILE.read_text(encoding="utf-8")
    accent_hex = DOMAIN_ACCENT_HEX[domain]

    substitutions = {
        "accent_hex": accent_hex,
        "domain_tag": DOMAIN_TAGS[domain],
        "headline": _wrap_emphasis(headline, emphasis_word, accent_hex),
        "sub_heading": sub_heading,
        "slide_label": "1 / 9",
        "image_data_uri": image_data_uri,
        "image_display": "block" if image_data_uri else "none",
    }
    for key, value in substitutions.items():
        html = html.replace("{{ " + key + " }}", str(value))

    # Written into tests/carousel/templates/ (same directory as the
    # template itself) so the template's ../../../carousel/fonts/*.woff2
    # relative @font-face paths resolve correctly, without ever writing
    # into carousel/templates/ itself — zero risk to the production
    # pipeline.
    tmp_html_path = TEMPLATE_DIR / "_tmp_new_cover_render.html"
    tmp_html_path.write_text(html, encoding="utf-8")

    output_path = OUTPUT_DIR / f"test_new_cover_{domain}.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        page.goto(tmp_html_path.as_uri())
        page.evaluate("document.fonts.ready")
        full_res_path = OUTPUT_DIR / "_tmp_new_cover_full_res.png"
        page.screenshot(path=str(full_res_path))
    finally:
        tmp_html_path.unlink(missing_ok=True)

    from PIL import Image

    with Image.open(full_res_path) as img:
        downscaled = img.resize((FINAL_WIDTH, FINAL_HEIGHT), Image.LANCZOS)
        downscaled.save(output_path)
    full_res_path.unlink(missing_ok=True)

    size_kb = output_path.stat().st_size / 1024
    print(f"Saved: {output_path} ({size_kb:.1f} KB)")
    return output_path


def main():
    check_dependencies()

    import anthropic
    from playwright.sync_api import sync_playwright
    from supabase import create_client

    supabase_client = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"]
    )
    # Matches carousel/writer.py's actual key usage — CAROUSEL_ANTHROPIC_API_KEY,
    # a separate billing account from ANTHROPIC_API_KEY (Intelligence Engine
    # pipeline, Decision #40). Confirmed by reading carousel/writer.py.
    anthropic_client = anthropic.Anthropic(api_key=os.environ["CAROUSEL_ANTHROPIC_API_KEY"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": RENDER_WIDTH, "height": RENDER_HEIGHT})

        for domain in DOMAINS:
            print(f"\n=== {domain} ===")
            card = fetch_latest_card(supabase_client, domain)
            if card is None:
                print(f"  No card found for domain {domain!r} — skipping.")
                continue

            primary_entity, _ = determine_primary_entity(anthropic_client, card)
            print(f"  Primary entity: {primary_entity}")

            headline, emphasis_word, sub_heading = generate_headline(anthropic_client, card, primary_entity)
            print(f"Headline for {domain}: {headline}")
            print(f"  Emphasis word: {emphasis_word!r}")
            print(f"  Sub-heading: {sub_heading}")

            visual_subject, is_person = determine_visual_subject(anthropic_client, card)
            print(f"  Visual subject: {visual_subject} (person={is_person})")

            image_data_uri = generate_and_duotone_image(card, visual_subject, is_person)
            used_image = bool(image_data_uri)
            if used_image:
                print(f"  Image generated and duotoned for {domain}.")

            output_path = render_cover(page, domain, card, headline, emphasis_word, sub_heading, image_data_uri)
            results.append((domain, headline, sub_heading, visual_subject, output_path, used_image))

        browser.close()

    print()
    print("New cover preview complete.")
    for domain, headline, sub_heading, visual_subject, output_path, used_image in results:
        status = "real image" if used_image else "typography-only fallback"
        print(f"  [{domain}] {output_path} — {status}")
        print(f"    headline: {headline}")
        print(f"    sub_heading: {sub_heading}")
        print(f"    visual_subject: {visual_subject}")


if __name__ == "__main__":
    main()
