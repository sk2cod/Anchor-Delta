"""
PostAssembler — the final pipeline stage (Blueprint §5.7).

Assembles final caption + hashtags + pinned comment, persists the Carousel
record, and prepares the export bundle for sync-to-folder (Decision #28).
HashtagBuilder samples from a curated YAML pool only — hashtags are never
LLM-generated (Decision #31).
"""

import json
import random
from pathlib import Path

import yaml

from carousel.cache import record_hashtag_use
from carousel.models import Carousel, CarouselSpec, CarouselStatus, EnrichedSpec
from db.carousel_queries import upsert_carousel

HASHTAGS_YAML_PATH = Path(__file__).parent / "hashtags.yaml"
DEFAULT_HASHTAG_COUNT = 20
BRAND_HANDLE = "@anchoranddelta"  # placeholder per Decision #29


class AssemblerError(Exception):
    pass


def _load_hashtag_pool() -> dict:
    if not HASHTAGS_YAML_PATH.exists():
        raise AssemblerError(f"hashtags.yaml not found at {HASHTAGS_YAML_PATH}")
    try:
        with open(HASHTAGS_YAML_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        raise AssemblerError("Failed to load hashtags.yaml") from e


def build_hashtags(
    domain: str,
    hashtag_themes: list[str],
    n: int = DEFAULT_HASHTAG_COUNT,
) -> list[str]:
    """
    Sample n hashtags from the curated YAML pool.
    Weighted toward domain tags. Always include
    cross_domain tags. Returns list of hashtag strings
    with # prefix.

    Records the selected set to the rotation log (carousel/cache.py) so
    future selections can check for repeats.

    TODO(v1.5+): actually use get_recent_hashtags() to avoid repeating the
    exact same set as the previous post (anti-shadowban heuristic per
    Blueprint §5.7). Recording is wired up; the avoidance check is not.
    """
    pool = _load_hashtag_pool()
    domain_pool = list(pool.get(domain, []))
    cross_pool = list(pool.get("cross_domain", []))

    if not domain_pool:
        raise AssemblerError(f"No hashtag pool found for domain {domain!r}")

    themes_lower = [t.lower() for t in hashtag_themes]

    def is_theme_matched(tag: str) -> bool:
        tag_lower = tag.lower()
        return any(tag_lower in theme or theme in tag_lower for theme in themes_lower)

    remaining_slots = max(n - len(cross_pool), 0)

    matched = [t for t in domain_pool if is_theme_matched(t)]
    unmatched = [t for t in domain_pool if t not in matched]
    random.shuffle(matched)
    random.shuffle(unmatched)

    domain_selection = (matched + unmatched)[:remaining_slots]

    selected = domain_selection + cross_pool
    random.shuffle(selected)

    hashtags = [f"#{tag}" for tag in selected]
    record_hashtag_use(hashtags)
    return hashtags


def assemble_caption(
    spec: CarouselSpec,
    hashtags: list[str],
    brand_handle: str = BRAND_HANDLE,
) -> str:
    """
    Assemble final Instagram caption.
    Structure:
    {LLM-written caption from spec.caption}

    {brand_handle}

    {hashtag block — one line, space-separated}
    """
    hashtag_block = " ".join(hashtags)
    return f"{spec.caption}\n\n{brand_handle}\n\n{hashtag_block}"


def assemble_carousel(
    enriched_spec: EnrichedSpec,
    slide_paths: list[Path],
    domain: str,
    card_id: str,
    persist: bool = True,
) -> Carousel:
    """
    Assemble final post content, persist to Supabase,
    prepare export bundle.
    Returns a Carousel record.
    Cost: $0. Latency: <100ms.
    """
    spec = enriched_spec.spec

    hashtags = build_hashtags(domain, spec.hashtag_themes)
    final_caption = assemble_caption(spec, hashtags)

    carousel = Carousel(
        card_id=card_id,
        card_version=spec.card_version,
        spec=spec,
        slide_paths=[str(p) for p in slide_paths],
        final_caption=final_caption,
        final_hashtags=hashtags,
        pinned_comment=spec.pinned_comment,
        status=CarouselStatus.draft,
    )

    if persist:
        try:
            upsert_carousel(carousel)
        except Exception as e:
            # The `carousels` table does not exist in Supabase yet (anon key
            # cannot run DDL — DESIGN_LESSONS.md §6; human must run the SQL
            # printed by db/carousel_queries.py first). Persistence failing
            # here should not block returning the assembled Carousel record.
            raise AssemblerError(
                "Failed to persist carousel — has the `carousels` table been "
                "created? See db/carousel_queries.CAROUSELS_TABLE_SQL."
            ) from e

    return carousel


def export_carousel(carousel: Carousel, output_dir: Path) -> Path:
    """
    Write carousel bundle to output_dir.
    Returns path to the bundle directory.
    Bundle: slide PNGs + caption.txt + pinned_comment.txt
            + hashtags.txt + manifest.json
    """
    output_dir = Path(output_dir)
    bundle_dir = output_dir / str(carousel.id)

    try:
        bundle_dir.mkdir(parents=True, exist_ok=True)

        for i, (slide, src_path) in enumerate(
            zip(carousel.spec.slides, carousel.slide_paths), start=1
        ):
            src = Path(src_path)
            if not src.exists():
                raise AssemblerError(f"Slide PNG not found: {src}")
            dest = bundle_dir / f"{i:02d}_{slide.slot_id}.png"
            dest.write_bytes(src.read_bytes())

        (bundle_dir / "caption.txt").write_text(carousel.final_caption, encoding="utf-8")
        (bundle_dir / "pinned_comment.txt").write_text(
            carousel.pinned_comment, encoding="utf-8"
        )
        (bundle_dir / "hashtags.txt").write_text(
            " ".join(carousel.final_hashtags), encoding="utf-8"
        )

        manifest = {
            "carousel_id": str(carousel.id),
            "card_id": carousel.card_id,
            "card_version": carousel.card_version,
            "generation_metadata": json.loads(
                carousel.spec.generation_metadata.model_dump_json()
            ),
            "slot_map": [
                {"slot_id": s.slot_id, "role": s.role.value} for s in carousel.spec.slides
            ],
            "created_at": carousel.created_at.isoformat(),
        }
        (bundle_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    except AssemblerError:
        raise
    except Exception as e:
        raise AssemblerError(f"Failed to export carousel bundle to {bundle_dir}") from e

    return bundle_dir
