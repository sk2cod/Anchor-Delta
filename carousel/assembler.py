"""
PostAssembler — the final pipeline stage (Blueprint §5.7).

Assembles final caption + hashtags + pinned comment, persists the Carousel
record, and prepares the export bundle for sync-to-folder (Decision #28).
HashtagBuilder samples from a curated YAML pool only — hashtags are never
LLM-generated (Decision #31).
"""

import json
import os
import random
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import yaml

from carousel.cache import get_recent_hashtags, record_hashtag_use
from carousel.models import Carousel, CarouselSpec, CarouselStatus, EnrichedSpec
from config import CAROUSEL_SYNC_DIR
from db.cards import get_card_by_id
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


_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")


def _lookup_card(carousel: Carousel) -> dict:
    return get_card_by_id(carousel.card_id) or {}


def _infer_domain(card_row: dict) -> str:
    """Same fallback as ui/carousel_view.py._infer_domain (Decision #49) —
    Carousel/CarouselSpec carry no domain field, so recover it from the
    source card row."""
    domain = card_row.get("domain")
    return domain if domain in ("world", "finance", "ai_tech") else "world"


def _slugify(text: str, max_len: int = 40) -> str:
    slug = _SLUG_INVALID_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def _bundle_folder_name(carousel: Carousel, card_row: dict) -> str:
    """
    Per-carousel sync subfolder name (Decision #52):
    YYYY-MM-DD_domain_slug, where the date is the generation date and
    the slug is derived from the source card's umbrella_title.
    """
    date_str = carousel.created_at.date().isoformat()
    domain = _infer_domain(card_row)
    slug = _slugify(card_row.get("umbrella_title") or "untitled")
    return f"{date_str}_{domain}_{slug}"


def _reserve_bundle_dir(base_dir: Path, folder_name: str) -> Path:
    """
    Collision guard (Decision #52) — never overwrite an existing bundle.
    A same-day regenerate of the same card gets a time suffix; the rare
    same-second collision falls back to a short hash.
    """
    candidate = base_dir / folder_name
    if not candidate.exists():
        return candidate
    candidate = base_dir / f"{folder_name}_{datetime.now().strftime('%H%M%S')}"
    if not candidate.exists():
        return candidate
    return base_dir / f"{folder_name}_{uuid4().hex[:4]}"


_GOOGLE_DRIVE_ENV_VARS = (
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REFRESH_TOKEN",
)


def _drive_configured() -> bool:
    return all(os.getenv(var) for var in _GOOGLE_DRIVE_ENV_VARS)


def export_carousel(carousel: Carousel, output_dir: Path) -> Path:
    """
    Write carousel bundle to its per-carousel sync subfolder (Decision #52),
    then, when Google Drive OAuth is configured (Stage 3 —
    INFRA_DECISIONS.md #02), upload that bundle to Drive.
    Returns path to the local bundle directory (the local write always
    happens: it's the finished export when Drive isn't configured, and the
    staging directory uploaded from when it is).
    Bundle: slide PNGs + caption.txt + pinned_comment.txt
            + hashtags.txt + manifest.json

    Local write target: CAROUSEL_SYNC_DIR (config.py) when set — typically
    a Google Drive-desktop / iCloud synced folder — else output_dir. Never
    used when Drive OAuth is configured: Drive uploads always stage into
    output_dir directly, not CAROUSEL_SYNC_DIR, since the two are separate
    sync mechanisms and mixing them would upload whatever else happens to
    be sitting in the local Drive-desktop mount rather than this run's own
    bundle. This function has no other knowledge of the sync layer itself —
    it only ever writes to a configured directory (and, when applicable,
    uploads what it just wrote).
    """
    use_drive = _drive_configured()

    if use_drive:
        base_dir = Path(output_dir)
    else:
        sync_root = CAROUSEL_SYNC_DIR.strip() if CAROUSEL_SYNC_DIR else ""
        base_dir = Path(sync_root) if sync_root else Path(output_dir)
    bundle_dir = base_dir

    try:
        card_row = _lookup_card(carousel)
        folder_name = _bundle_folder_name(carousel, card_row)
        bundle_dir = _reserve_bundle_dir(base_dir, folder_name)
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

        if use_drive:
            from carousel.drive_sync import get_or_create_folder, upload_bundle

            drive_folder_id = get_or_create_folder()
            upload_bundle(bundle_dir, drive_folder_id)
    except AssemblerError:
        raise
    except Exception as e:
        raise AssemblerError(f"Failed to export carousel bundle to {bundle_dir}") from e

    return bundle_dir
