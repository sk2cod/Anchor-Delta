#!/usr/bin/env python3
"""
Portrait/editorial cover slide render test — now with real AI-generated
background art (DALL-E 3) instead of the earlier procedural-SVG stand-in.
Design feedback tool only, same spirit as tests/carousel/test_render.py
(CAROUSEL_DECISIONS.md #46) but fully self-contained: imports nothing
from carousel/*.py, reads/writes nothing under carousel/templates/.
Reuses the real self-hosted fonts in carousel/fonts/ (read-only) so the
type treatment matches production, but the chassis CSS and template are
duplicated locally in tests/carousel/templates/test_portrait_cover.html.

Requires OPENAI_API_KEY in .env for real image generation. If missing,
or if generation fails for any other reason, each card falls back to
rendering the real production carousel/templates/cover.html (read
only, never modified) instead — never a crash, always a warning.

Usage: python tests/carousel/test_portrait_hook.py
"""

import base64
import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).parent.parent.parent
TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "test_portrait_cover.html"
OUTPUT_DIR = REPO_ROOT / "outputs" / "renders"

RENDER_WIDTH = 2160
RENDER_HEIGHT = 2700
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1350

SHADOW_HEX = "#1A1612"  # brand background tone — the duotone shadow colour

load_dotenv(REPO_ROOT / ".env")

# Hardcoded test content — two real cards from this session.
TEST_CARDS = [
    {
        "id": "putin_war_narratives",
        "variant": "portrait",
        "domain": "world",
        "domain_tag": "WORLD",
        "accent_hex": "#C8813A",
        "accent_rgb": "200,129,58",
        "dalle_prompt": (
            "Editorial pencil sketch portrait of Vladimir Putin, detailed and "
            "recognisable facial features, serious authoritative expression, "
            "dark near-black warm brown background, dramatic chiaroscuro "
            "lighting with amber accent highlights, high contrast, editorial "
            "magazine illustration style reminiscent of The Economist cover "
            "illustrations, no text, no logos, no watermarks, portrait "
            "orientation"
        ),
        "kicker": "PUTIN'S WAR OF NARRATIVES",
        "headline_line1": "Putin claimed victory.",
        "headline_line2": "The real number: 97.",
        "emphasis_word": "97",
        "sub_line": "Russia is fighting a different war now — and it's inside your head.",
        "slide_label": "1 / 10",
        "output": "outputs/renders/test_portrait_hook_putin.png",
    },
    {
        "id": "sk_hynix_memory",
        "variant": "editorial",
        "domain": "ai_tech",
        "domain_tag": "AI & TECH",
        "accent_hex": "#00D9FF",
        "accent_rgb": "0,217,255",
        "dalle_prompt": (
            "Cinematic dark editorial macro photograph. An extreme close-up "
            "of a semiconductor memory chip, deep near-black warm brown "
            "background matching #1A1612, electric cyan light tracing "
            "circuit pathways, dramatic chiaroscuro, shallow depth of field, "
            "no text, no logos, no watermarks, editorial magazine cover "
            "style, ultra high contrast, futuristic and precise, "
            "4:5 portrait orientation"
        ),
        "kicker": "THE MEMORY CHIP GOLD RUSH",
        "headline_line1": "AI runs on memory.",
        "headline_line2": "It's running out.",
        "emphasis_word": "memory",
        "sub_line": "SK Hynix just showed up on Wall Street — with a $28 billion ask.",
        "slide_label": "1 / 8",
        "output": "outputs/renders/test_portrait_hook_skhynix.png",
    },
]


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
        import openai  # noqa: F401
    except ImportError:
        missing.append("openai")

    if missing:
        print("Missing required dependencies: " + ", ".join(missing))
        print()
        print("Install with:")
        print(f"  pip install {' '.join(missing)}")
        if "playwright" in missing:
            print("  playwright install chromium")
        sys.exit(1)


def apply_duotone(pil_image, shadow_hex, highlight_hex):
    """
    Convert image to duotone using shadow and highlight colours.
    shadow_hex: the dark tone (e.g. '#1A1612')
    highlight_hex: the accent colour (e.g. '#C8813A')
    Returns a new PIL Image in RGB mode.
    """
    from PIL import Image

    grey = pil_image.convert("L")

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


def generate_and_duotone(card: dict) -> str:
    """
    Generate an AI image for this card (gpt-image-1 — see model note
    below), apply the brand duotone treatment, and return a base64 data
    URI. Returns "" (triggering the template's typography-only fallback)
    on any failure — API key missing, API error, decode error — never
    raises.
    """
    from PIL import Image

    try:
        import openai

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in environment/.env")

        client = openai.OpenAI(api_key=api_key)

        # Model note: dall-e-3 is unavailable on this account's API key
        # (confirmed via client.models.list() — only the gpt-image-*
        # family is present). Switched to gpt-image-1 per explicit user
        # choice. Its schema differs from dall-e-3: no style param,
        # quality is "low"/"medium"/"high"/"auto" (not "standard"/"hd"),
        # and it returns b64_json directly rather than a URL — no
        # download step needed, unlike the original dall-e-3 flow.
        response = client.images.generate(
            model="gpt-image-1",
            prompt=card["dalle_prompt"],
            size="1024x1024",
            quality="high",
            n=1,
        )
        b64_source = response.data[0].b64_json
        raw_image = Image.open(io.BytesIO(base64.b64decode(b64_source)))
        duotoned = apply_duotone(raw_image, SHADOW_HEX, card["accent_hex"])

        buffer = io.BytesIO()
        duotoned.save(buffer, format="PNG")
        b64_string = base64.b64encode(buffer.getvalue()).decode()
        return f"data:image/png;base64,{b64_string}"

    except Exception as e:
        print(f"  WARNING: DALL-E generation failed for {card['id']!r}: {e}")
        print("  Falling back to typography-only render (no image).")
        return ""


def _wrap_emphasis(line: str, emphasis_word: str) -> str:
    """Wrap emphasis_word in <em class="accent"> if it appears in this
    line, mirroring carousel/renderer.py's _build_body_html treatment
    (read-only reference — not imported)."""
    if emphasis_word and emphasis_word in line:
        return line.replace(emphasis_word, f'<em class="accent">{emphasis_word}</em>', 1)
    return line


def _screenshot_and_downscale(page, tmp_html_path: Path, output_path: Path, log_prefix: str) -> None:
    """Shared render tail: goto the temp HTML, screenshot at 2x, downscale
    via Pillow to final size, clean up temp files. Used by both the
    portrait-template path and the production-cover fallback path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        page.goto(tmp_html_path.as_uri())
        page.evaluate("document.fonts.ready")
        full_res_path = OUTPUT_DIR / "_tmp_portrait_full_res.png"
        page.screenshot(path=str(full_res_path))
    finally:
        tmp_html_path.unlink(missing_ok=True)

    from PIL import Image

    with Image.open(full_res_path) as img:
        downscaled = img.resize((FINAL_WIDTH, FINAL_HEIGHT), Image.LANCZOS)
        downscaled.save(output_path)
    full_res_path.unlink(missing_ok=True)

    size_kb = output_path.stat().st_size / 1024
    print(f"{log_prefix}: {output_path} ({size_kb:.1f} KB)")


def render_portrait_template(page, card: dict, image_data_uri: str) -> Path:
    """Render this card on the portrait/editorial test template. Only
    called when a real generated image exists — the no-image case is
    handled entirely by render_fallback_cover() instead (Fix 3)."""
    if not TEMPLATE_FILE.exists():
        print(f"Template not found: {TEMPLATE_FILE}")
        sys.exit(1)

    html = TEMPLATE_FILE.read_text(encoding="utf-8")

    substitutions = {
        "variant": card["variant"],
        "accent_hex": card["accent_hex"],
        "domain_tag": card["domain_tag"],
        "kicker": card["kicker"],
        "headline_line1": _wrap_emphasis(card["headline_line1"], card["emphasis_word"]),
        "headline_line2": _wrap_emphasis(card["headline_line2"], card["emphasis_word"]),
        "sub_line": card["sub_line"],
        "slide_label": card["slide_label"],
        "image_data_uri": image_data_uri,
    }
    for key, value in substitutions.items():
        html = html.replace("{{ " + key + " }}", str(value))

    # Written into tests/carousel/templates/ (same directory as the
    # template itself) so the template's ../../../carousel/fonts/*.woff2
    # relative @font-face paths resolve correctly, without ever writing
    # into carousel/templates/ itself — zero risk to the production
    # pipeline.
    tmp_html_path = TEMPLATE_DIR / "_tmp_test_portrait_render.html"
    tmp_html_path.write_text(html, encoding="utf-8")

    output_path = REPO_ROOT / card["output"]
    _screenshot_and_downscale(page, tmp_html_path, output_path, "Saved")
    return output_path


def render_fallback_cover(page, card: dict) -> Path:
    """
    Fix 3 — when image generation fails, render the REAL production
    cover.html directly instead of a typography-only version of this
    test's own template, so the fallback is identical to a production
    cover slide.

    carousel/templates/cover.html and base.css are only ever READ here,
    never written to or modified. cover.html's <link href="base.css">
    is a same-directory relative path; rather than writing any temp
    file into carousel/templates/ (which the production renderer.py
    and tests/carousel/test_render.py both do, but this task's
    instructions are explicit that carousel/ must not be touched at
    all), the href is rewritten to an absolute file:// URI pointing at
    the real base.css before rendering, so the temp file can live
    entirely inside tests/carousel/templates/ instead.
    """
    cover_path = REPO_ROOT / "carousel" / "templates" / "cover.html"
    base_css_uri = (REPO_ROOT / "carousel" / "templates" / "base.css").as_uri()

    cover_source = cover_path.read_text(encoding="utf-8")
    cover_source = cover_source.replace('href="base.css"', f'href="{base_css_uri}"')

    # Same variable names carousel/renderer.py's _build_variables() cover
    # branch uses (read there, not imported): domain_label, accent_colour,
    # page_indicator, wordmark, kicker, headline_html, sub_line.
    from jinja2 import Template

    headline_html = (
        f"{_wrap_emphasis(card['headline_line1'], card['emphasis_word'])}<br>"
        f"{_wrap_emphasis(card['headline_line2'], card['emphasis_word'])}"
    )
    rendered_html = Template(cover_source).render(
        domain_label=card["domain_tag"],
        accent_colour=card["accent_hex"],
        page_indicator=card["slide_label"],
        wordmark="ANCHOR & DELTA",
        kicker=card["kicker"],
        headline_html=headline_html,
        sub_line=card["sub_line"],
    )

    tmp_html_path = TEMPLATE_DIR / "_tmp_fallback_cover_render.html"
    tmp_html_path.write_text(rendered_html, encoding="utf-8")

    output_path = REPO_ROOT / card["output"]
    _screenshot_and_downscale(page, tmp_html_path, output_path, "Saved (production cover fallback)")
    return output_path


def render_card(page, card: dict) -> Path:
    print(f"Generating image for {card['id']}...")
    image_data_uri = generate_and_duotone(card)
    if image_data_uri:
        print(f"  Image generated and duotoned for {card['id']}.")
        return render_portrait_template(page, card, image_data_uri)
    print(f"  Rendering production cover.html fallback for {card['id']} (no image).")
    return render_fallback_cover(page, card)


def main():
    check_dependencies()

    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": RENDER_WIDTH, "height": RENDER_HEIGHT})
        for card in TEST_CARDS:
            output_paths.append(render_card(page, card))
        browser.close()

    print()
    print("Portrait hook test complete. Open the PNGs in outputs/renders/ to review.")
    for path in output_paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
