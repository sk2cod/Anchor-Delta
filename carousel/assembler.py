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

from carousel.cache import get_recent_hashtags, record_hashtag_use
from carousel.models import Carousel, CarouselSpec, CarouselStatus, EnrichedSpec
from db.carousel_queries import upsert_carousel

HASHTAGS_YAML_PATH = Path(__file__).parent / "hashtags.yaml"
DEFAULT_HASHTAG_COUNT = 5
BRAND_HANDLE = "@anchordelta"  # placeholder per Decision #29


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
    Select exactly 5 hashtags per post.
    Formula:
    - #anchordelta (brand, always)
    - #intelligencebriefing (category, always)
    - 1 mid-volume tag from domain pool (rotated)
    - 2 niche tags matched to hashtag_themes
    Total: 5
    """
    pool = _load_hashtag_pool()

    domain_pool = pool.get(domain, {})
    if not domain_pool:
        raise AssemblerError(f"No hashtag pool found for domain {domain!r}")

    niche_tags = domain_pool.get("niche", [])
    mid_volume_tags = domain_pool.get("mid_volume", [])

    # Fixed slots — always included
    fixed = ["anchordelta", "intelligencebriefing"]

    # 1 mid-volume tag — rotate through pool to avoid repetition
    recent = get_recent_hashtags(3)
    recent_flat = set(tag.lstrip("#") for s in recent for tag in s)

    available_mid = [t for t in mid_volume_tags if t not in recent_flat]
    if not available_mid:
        available_mid = mid_volume_tags  # reset if all used recently
    mid_pick = [random.choice(available_mid)]

    # 2 niche tags — match to hashtag_themes
    themes_lower = [t.lower() for t in hashtag_themes]

    def theme_score(tag: str) -> int:
        return sum(
            1 for theme in themes_lower
            if theme in tag or tag in theme
        )

    scored = sorted(niche_tags, key=theme_score, reverse=True)
    niche_picks = [t for t in scored if t not in recent_flat][:2]

    # Fallback if fewer than 2 niche matches
    if len(niche_picks) < 2:
        fallback = [t for t in niche_tags if t not in niche_picks]
        niche_picks += fallback[:2 - len(niche_picks)]

    # Assemble final 5
    selected = fixed + mid_pick + niche_picks
    selected = selected[:5]  # hard cap

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
