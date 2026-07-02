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
OUTPUT_DIR = REPO_ROOT / "outputs" / "renders"

RENDER_WIDTH = 2160
RENDER_HEIGHT = 2700
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1350

TEST_CONTENT_STATEMENT = {
    "template": "statement.html",
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

TEST_CONTENT_HOOK = {
    "template": "hook.html",
    "domain_label": "WORLD",
    "accent_colour": "#C8813A",
    "headline": "Putin doesn't admit problems.",
    "emphasis_line": "Today, he did.",
    "page_indicator": "1 / 8",
    "wordmark": "ANCHOR & DELTA",
}

TEST_CONTENT_NUMBER = {
    "template": "number.html",
    "domain_label": "WORLD",
    "accent_colour": "#C8813A",
    "date_label": "JUNE 29, 2026",
    "headline": "Ukraine struck two more refineries.",
    "number_row_1_label": "Krasnodar",
    "number_row_1_value": "186 mi",
    "number_row_2_label": "Yaroslavl",
    "number_row_2_value": "435 mi",
    "context_label": "from the front line",
    "page_indicator": "3 / 8",
    "wordmark": "ANCHOR & DELTA",
}

TEST_CONTENT_QUOTE = {
    "template": "quote.html",
    "domain_label": "WORLD",
    "accent_colour": "#C8813A",
    "attribution": "Volodymyr Zelensky, President of Ukraine",
    "quote_text": (
        "Russia thought this was about land. "
        "We showed them it was about survival."
    ),
    "page_indicator": "5 / 8",
    "wordmark": "ANCHOR & DELTA",
}

TEST_CONTENT_TIMELINE = {
    "template": "timeline.html",
    "domain_label": "WORLD",
    "accent_colour": "#C8813A",
    "date_label": "JUNE 29, 2026",
    "headline": "Ukraine struck the Kremlin's supply chain.",
    "body_html": (
        'Two refineries hit in a single night — '
        '<em class="accent">800 miles</em> from the front line.'
    ),
    "page_indicator": "2 / 8",
    "wordmark": "ANCHOR & DELTA",
}

TEST_CONTENT_CONCEPT = {
    "template": "concept.html",
    "domain_label": "WORLD",
    "accent_colour": "#C8813A",
    "headline": "Why refineries, not tanks.",
    "body_html": (
        'Tanks need fuel. Fuel needs refineries. '
        'Refineries are fixed, large, and visible. '
        'Ukraine found the '
        '<em class="accent">single point of failure</em> '
        'in Russia\'s entire war machine.'
    ),
    "page_indicator": "6 / 8",
    "wordmark": "ANCHOR & DELTA",
}

TEST_CONTENT_CTA = {
    "template": "cta.html",
    "accent_colour": "#C8813A",
    "handle": "@anchordelta",
    "wordmark": "ANCHOR & DELTA",
}

# Each job renders one TEST_CONTENT dict to its own output file.
RENDER_JOBS = [
    (TEST_CONTENT_STATEMENT, OUTPUT_DIR / "test_statement.png"),
    (TEST_CONTENT_HOOK, OUTPUT_DIR / "test_hook.png"),
    (TEST_CONTENT_NUMBER, OUTPUT_DIR / "test_number.png"),
    (TEST_CONTENT_QUOTE, OUTPUT_DIR / "test_quote.png"),
    (TEST_CONTENT_TIMELINE, OUTPUT_DIR / "test_timeline.png"),
    (TEST_CONTENT_CONCEPT, OUTPUT_DIR / "test_concept.png"),
    (TEST_CONTENT_CTA, OUTPUT_DIR / "test_cta.png"),
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

    if missing:
        print("Missing required dependencies: " + ", ".join(missing))
        print()
        print("Install with:")
        print(f"  pip install {' '.join(missing)}")
        if "playwright" in missing:
            print("  playwright install chromium")
        sys.exit(1)


def render_template(template_file: Path, variables: dict) -> str:
    html = template_file.read_text(encoding="utf-8")
    for key, value in variables.items():
        if key == "template":
            continue
        html = html.replace("{{ " + key + " }}", str(value))
    return html


def render_one(page, content: dict, output_file: Path):
    template_file = TEMPLATE_DIR / content.get("template", "statement.html")
    if not template_file.exists():
        print(f"Template not found: {template_file}")
        sys.exit(1)

    rendered_html = render_template(template_file, content)
    tmp_html_path = TEMPLATE_DIR / "_tmp_render.html"
    tmp_html_path.write_text(rendered_html, encoding="utf-8")

    try:
        page.goto(tmp_html_path.as_uri())
        page.evaluate("document.fonts.ready")
        full_res_path = OUTPUT_DIR / "_tmp_full_res.png"
        page.screenshot(path=str(full_res_path))
    finally:
        tmp_html_path.unlink(missing_ok=True)

    from PIL import Image

    with Image.open(full_res_path) as img:
        downscaled = img.resize((FINAL_WIDTH, FINAL_HEIGHT), Image.LANCZOS)
        downscaled.save(output_file)
    full_res_path.unlink(missing_ok=True)

    size_kb = output_file.stat().st_size / 1024
    print(f"Rendered: {output_file} ({size_kb:.1f} KB)")


def main():
    check_dependencies()

    from playwright.sync_api import sync_playwright

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": RENDER_WIDTH, "height": RENDER_HEIGHT})
        for content, output_file in RENDER_JOBS:
            render_one(page, content, output_file)
        browser.close()


if __name__ == "__main__":
    main()
