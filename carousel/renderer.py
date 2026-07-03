"""
SlideRenderer — renders each EnrichedSlide to a 1080x1350 PNG (Blueprint §5.6).

The production renderer, not the test script (Decision #46). Takes typed
EnrichedSlide/EnrichedSpec models from carousel/models.py, uses Jinja2 for
variable substitution, and maintains a render cache keyed by content hash.
tests/carousel/test_render.py remains unchanged and independent — this
module never imports from it.

Fonts self-hosted, no CDN at render time (Decision #10, #11). Renders at
2160x2700 (2x), downscales to 1080x1350 for sharp typography on high-DPI
phones (Decision #09).
"""

import io
import re
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from PIL import Image

from carousel.cache import render_cache_key
from carousel.layout_picker import DOMAIN_ACCENTS
from carousel.models import EnrichedSlide, EnrichedSpec

REPO_ROOT = Path(__file__).parent.parent
TEMPLATE_DIR = Path(__file__).parent / "templates"
OUTPUT_DIR = REPO_ROOT / "outputs" / "renders"

RENDER_WIDTH = 2160
RENDER_HEIGHT = 2700
FINAL_WIDTH = 1080
FINAL_HEIGHT = 1350

BRAND_VERSION = "1.0"  # bump when CSS changes, to invalidate the render cache
WORDMARK = "ANCHOR & DELTA"
CTA_HANDLE = "@anchoranddelta"  # placeholder per Decision #29

DOMAIN_DISPLAY_LABELS = {
    "world": "WORLD",
    "finance": "FINANCE",
    "ai_tech": "AI & TECH",
}
# EnrichedSlide/EnrichedSpec carry no domain field anywhere in the schema —
# domain only exists transiently as a pick_layouts() parameter. Since each
# domain maps to a distinct accent colour in v1.0, we recover it here via
# reverse lookup rather than threading a new field through models.py.
_ACCENT_TO_DOMAIN = {accent: domain for domain, accent in DOMAIN_ACCENTS.items()}

DATE_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)

_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


class RendererError(Exception):
    pass


def _domain_label_from_accent(accent_colour: str) -> str:
    domain = _ACCENT_TO_DOMAIN.get(accent_colour)
    return DOMAIN_DISPLAY_LABELS.get(domain, "") if domain else ""


def _extract_date_label(*texts: str) -> str:
    for text in texts:
        if not text:
            continue
        match = DATE_PATTERN.search(text)
        if match:
            return match.group(0)
    return ""


def _build_body_html(body: str, emphasis_word: Optional[str]) -> str:
    if emphasis_word and emphasis_word in body:
        return body.replace(emphasis_word, f'<em class="accent">{emphasis_word}</em>', 1)
    return body


def _build_variables(enriched_slide: EnrichedSlide, domain_label: str, page_indicator: str) -> dict:
    slide = enriched_slide.slide
    layout = enriched_slide.layout
    template_id = layout.template_id.value

    variables = {
        "domain_label": domain_label,
        "accent_colour": layout.accent_colour,
        "page_indicator": page_indicator,
        "wordmark": WORDMARK,
    }

    if template_id in ("statement", "concept"):
        variables["headline"] = slide.headline
        variables["body_html"] = _build_body_html(slide.body, slide.emphasis_word)
    elif template_id == "hook":
        variables["headline"] = slide.headline
        variables["emphasis_line"] = slide.body
    elif template_id == "number":
        variables["date_label"] = _extract_date_label(slide.body, slide.headline)
        variables["headline"] = slide.headline
        if slide.dominant_number is not None:
            variables["number_row_1_label"] = slide.dominant_number.label
            variables["number_row_1_value"] = slide.dominant_number.value
            variables["context_label"] = slide.dominant_number.context
        else:
            variables["number_row_1_label"] = ""
            variables["number_row_1_value"] = ""
            variables["context_label"] = slide.body
        variables["number_row_2_label"] = ""
        variables["number_row_2_value"] = ""
    elif template_id == "quote":
        variables["attribution"] = slide.quote.attribution if slide.quote else ""
        variables["quote_text"] = slide.quote.text if slide.quote else ""
    elif template_id == "timeline":
        variables["date_label"] = _extract_date_label(slide.body)
        variables["headline"] = slide.headline
        variables["body_html"] = _build_body_html(slide.body, slide.emphasis_word)
    elif template_id == "cta":
        variables["handle"] = CTA_HANDLE

    return variables


def _cache_key(enriched_slide: EnrichedSlide) -> str:
    layout = enriched_slide.layout
    slide = enriched_slide.slide
    return render_cache_key(
        template_id=layout.template_id.value,
        headline=slide.headline,
        body=slide.body,
        accent=layout.accent_colour,
        theme=layout.theme_variant,
        brand_version=BRAND_VERSION,
    )


def _cache_path(cache_key: str) -> Path:
    return OUTPUT_DIR / f"{cache_key[:16]}.png"


def _render_to_bytes(page, template_id: str, variables: dict) -> bytes:
    try:
        template = _jinja_env.get_template(f"{template_id}.html")
    except TemplateNotFound as e:
        raise RendererError(f"Template not found: {template_id}.html") from e

    rendered_html = template.render(**variables)

    # page.set_content() gives the document an about:blank-style origin,
    # which Chromium blocks from loading local file:// resources (base.css,
    # ../fonts/*.woff2) even with a <base> tag pointing at them. Writing a
    # real temp file inside carousel/templates/ and navigating via
    # page.goto() gives the document a genuine file:// origin matching its
    # resources — the same approach tests/carousel/test_render.py uses.
    tmp_html_path = TEMPLATE_DIR / "_tmp_render.html"
    tmp_html_path.write_text(rendered_html, encoding="utf-8")

    try:
        page.goto(tmp_html_path.as_uri())
        page.evaluate("document.fonts.ready")
        return page.screenshot()
    except Exception as e:
        raise RendererError(f"Playwright render failed for template {template_id!r}") from e
    finally:
        tmp_html_path.unlink(missing_ok=True)


def _render_and_cache(
    enriched_slide: EnrichedSlide,
    page_indicator: str,
    page,
    force: bool,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cache_key = _cache_key(enriched_slide)
    output_path = _cache_path(cache_key)
    if output_path.exists() and not force:
        return output_path

    domain_label = _domain_label_from_accent(enriched_slide.layout.accent_colour)
    variables = _build_variables(enriched_slide, domain_label, page_indicator)
    full_res_bytes = _render_to_bytes(page, enriched_slide.layout.template_id.value, variables)

    with Image.open(io.BytesIO(full_res_bytes)) as img:
        downscaled = img.resize((FINAL_WIDTH, FINAL_HEIGHT), Image.LANCZOS)
        downscaled.save(output_path)

    return output_path


def render_slide(
    slide: EnrichedSlide,
    force: bool = False,
    slide_index: int = 0,
    total_slides: int = 1,
) -> Path:
    """
    Render a single EnrichedSlide to a 1080x1350 PNG.
    Returns path to the output PNG.
    Uses render cache — identical input returns cached path.
    Cost: $0. Latency: ~250ms cold, ~5ms warm.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cache_key = _cache_key(slide)
    output_path = _cache_path(cache_key)
    if output_path.exists() and not force:
        return output_path

    page_indicator = f"{slide_index + 1} / {total_slides}"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RendererError(
            "playwright is not installed. Install with: pip install playwright "
            "&& playwright install chromium"
        ) from e

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": RENDER_WIDTH, "height": RENDER_HEIGHT})
                return _render_and_cache(slide, page_indicator, page, force)
            finally:
                browser.close()
    except RendererError:
        raise
    except Exception as e:
        raise RendererError("Playwright browser launch failed") from e


def render_carousel(enriched_spec: EnrichedSpec, force: bool = False) -> list[Path]:
    """
    Render all slides in an EnrichedSpec.
    Returns ordered list of PNG paths.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = len(enriched_spec.slides)

    if not force:
        cached_paths = []
        for enriched_slide in enriched_spec.slides:
            path = _cache_path(_cache_key(enriched_slide))
            if not path.exists():
                cached_paths = None
                break
            cached_paths.append(path)
        if cached_paths is not None:
            # Every slide was already cached — skip launching Playwright entirely.
            return cached_paths

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RendererError(
            "playwright is not installed. Install with: pip install playwright "
            "&& playwright install chromium"
        ) from e

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": RENDER_WIDTH, "height": RENDER_HEIGHT})
                return [
                    _render_and_cache(enriched_slide, f"{i + 1} / {total}", page, force)
                    for i, enriched_slide in enumerate(enriched_spec.slides)
                ]
            finally:
                browser.close()
    except RendererError:
        raise
    except Exception as e:
        raise RendererError("Playwright browser launch failed") from e
