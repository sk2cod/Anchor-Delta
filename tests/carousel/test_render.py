#!/usr/bin/env python3
"""
Carousel template render script.
Design feedback tool only — see CAROUSEL_DECISIONS.md #46.
Imports nothing from carousel/*.py.
Usage: python tests/carousel/test_render.py
"""

import sys
from pathlib import Path

# --- Paths (all relative to repo root) ---
REPO_ROOT = Path(__file__).parent.parent.parent
TEMPLATE_DIR = REPO_ROOT / "carousel" / "templates"
TEMPLATE_FILE = TEMPLATE_DIR / "statement.html"
OUTPUT_DIR = REPO_ROOT / "outputs" / "renders"
OUTPUT_FILE = OUTPUT_DIR / "test_statement.png"

RENDER_WIDTH = 2160
RENDER_HEIGHT = 2700
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1350

TEST_CONTENT = {
    "domain_label": "WORLD",
    "accent_colour": "#C8813A",
    "headline": "This isn't a territorial war anymore.",
    "body_html": (
        'Ukraine figured out something '
        '<em class="accent">dangerous</em>'
        ' — Russia\'s refineries fund the entire war machine. '
        'Strike the supply chain, and the tanks stop moving.'
    ),
    "page_indicator": "4 / 8",
    "wordmark": "ANCHOR & DELTA",
}


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

    if missing:
        print("Missing required dependencies: " + ", ".join(missing))
        print()
        print("Install with:")
        print(f"  pip install {' '.join(missing)}")
        if "playwright" in missing:
            print("  playwright install chromium")
        sys.exit(1)


def render_template(variables: dict) -> str:
    html = TEMPLATE_FILE.read_text(encoding="utf-8")
    for key, value in variables.items():
        html = html.replace("{{ " + key + " }}", str(value))
    return html


def main():
    check_dependencies()

    from playwright.sync_api import sync_playwright
    from PIL import Image

    if not TEMPLATE_FILE.exists():
        print(f"Template not found: {TEMPLATE_FILE}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rendered_html = render_template(TEST_CONTENT)
    tmp_html_path = TEMPLATE_DIR / "_tmp_render.html"
    tmp_html_path.write_text(rendered_html, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": RENDER_WIDTH, "height": RENDER_HEIGHT})
            page.goto(tmp_html_path.as_uri())
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(OUTPUT_DIR / "_tmp_full_res.png"))
            browser.close()
    finally:
        tmp_html_path.unlink(missing_ok=True)

    full_res_path = OUTPUT_DIR / "_tmp_full_res.png"
    with Image.open(full_res_path) as img:
        downscaled = img.resize((FINAL_WIDTH, FINAL_HEIGHT), Image.LANCZOS)
        downscaled.save(OUTPUT_FILE)
    full_res_path.unlink(missing_ok=True)

    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"Rendered: {OUTPUT_FILE} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
