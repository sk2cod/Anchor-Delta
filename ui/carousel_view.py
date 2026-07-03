"""
Carousel preview + edit + approve UI (Blueprint §12).

Renders the full preview UI for a single generated Carousel, called from
render_card() in ui/app.py after carousel generation. ui/ may import from
carousel/; carousel/ never imports from ui/ (Decision #41).
"""

import hashlib
from pathlib import Path

import streamlit as st

from carousel.assembler import AssemblerError, build_hashtags, export_carousel
from carousel.layout_picker import pick_layouts
from carousel.models import Carousel, CarouselStatus
from carousel.renderer import render_slide
from db.cards import get_card_by_id
from db.carousel_queries import update_carousel_status, upsert_carousel

EXPORT_OUTPUT_DIR = Path("outputs") / "bundles"


def render_carousel_preview(carousel: Carousel) -> None:
    """
    Render the full carousel preview UI.
    Called from within a card's expander in app.py.
    """
    try:
        st.markdown("---")
        st.markdown("### 🎠 Carousel Preview")
        _render_slide_thumbnails(carousel)
        _render_caption_section(carousel)
        _render_script_controls(carousel)
        _render_hashtag_display(carousel)
    except Exception as e:
        # A broken carousel preview must never take the rest of the card
        # view down with it.
        st.error(f"Failed to render carousel preview: {e}")


def _infer_domain(carousel: Carousel) -> str:
    """
    Carousel carries no domain field anywhere in its schema (neither does
    CarouselSpec — domain only ever existed as a transient pick_layouts()
    parameter, same gap noted in carousel/renderer.py). card_id is a real
    foreign key back to the source card, so look it up there instead of
    guessing.
    """
    card_row = get_card_by_id(carousel.card_id)
    if card_row and card_row.get("domain") in ("world", "finance", "ai_tech"):
        return card_row["domain"]
    return "world"


def _render_slide_thumbnails(carousel: Carousel) -> None:
    slides = carousel.spec.slides
    slide_paths = carousel.slide_paths

    if not slides:
        st.info("No slides in this carousel.")
        return

    st.markdown("#### Slides")
    cols = st.columns(len(slides))

    for i, (slide, col) in enumerate(zip(slides, cols)):
        with col:
            path_str = slide_paths[i] if i < len(slide_paths) else None
            if path_str and Path(path_str).exists():
                st.image(path_str, width=270)
            else:
                st.markdown(
                    "<div style='width:270px;height:337px;background:#222;"
                    "display:flex;align-items:center;justify-content:center;"
                    f"color:#888;font-size:12px;text-align:center;'>Missing PNG<br>{slide.slot_id}</div>",
                    unsafe_allow_html=True,
                )
            st.caption(slide.slot_id)
            _render_slide_controls(carousel, i, slide)


def _render_slide_controls(carousel: Carousel, index: int, slide) -> None:
    edit_key = f"editing_slide_{carousel.id}_{index}"
    lock_key = f"locked_slide_{carousel.id}_{index}"

    btn_cols = st.columns(3)
    with btn_cols[0]:
        if st.button("✏️", key=f"edit_btn_{carousel.id}_{index}", help="Edit this slide"):
            st.session_state[edit_key] = not st.session_state.get(edit_key, False)
    with btn_cols[1]:
        st.button(
            "🔄",
            key=f"regen_btn_{carousel.id}_{index}",
            help="Targeted regenerate coming in v1.1",
            disabled=True,
        )
        # Wired but inert in v1.0 — would set:
        #   st.session_state[f"regenerating_slide_{carousel.id}_{index}"] = True
    with btn_cols[2]:
        locked = st.session_state.setdefault(lock_key, slide.manually_edited)
        if st.button("🔒" if locked else "🔓", key=f"lock_btn_{carousel.id}_{index}", help="Lock this slide"):
            st.session_state[lock_key] = not locked
            st.rerun()

    if st.session_state.get(edit_key, False):
        # Inline text editor (Model C — no LLM call, $0 cost, Decision #16).
        new_headline = st.text_input(
            "Headline", value=slide.headline, key=f"headline_input_{carousel.id}_{index}"
        )
        new_body = st.text_area(
            "Body", value=slide.body, key=f"body_input_{carousel.id}_{index}", height=80
        )
        if st.button("💾 Save", key=f"save_slide_{carousel.id}_{index}"):
            try:
                _save_slide_edit(
                    carousel=carousel,
                    slide_index=index,
                    new_headline=new_headline,
                    new_body=new_body,
                    domain=_infer_domain(carousel),
                )
                st.session_state[edit_key] = False
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save slide edit: {e}")


def _save_slide_edit(
    carousel: Carousel,
    slide_index: int,
    new_headline: str,
    new_body: str,
    domain: str,
) -> None:
    """
    Model C inline edit — no LLM call, $0 cost (Blueprint §5.4, Decision #16).
    Updates slide text, re-renders that slide's PNG, persists to Supabase.
    """
    slide = carousel.spec.slides[slide_index]
    slide.headline = new_headline
    slide.body = new_body
    slide.manually_edited = True
    slide.text_hash = hashlib.md5((new_headline + new_body).encode()).hexdigest()

    # LayoutChoice (template/accent/theme) isn't persisted on Carousel — only
    # the plain CarouselSpec is. pick_layouts() is deterministic and cheap
    # ($0, <10ms), so re-deriving it here is correct and avoids reaching into
    # layout_picker's private per-slide helpers.
    enriched_spec = pick_layouts(carousel.spec, domain)
    enriched_slide = enriched_spec.slides[slide_index]

    new_png_path = render_slide(
        enriched_slide,
        force=True,
        slide_index=slide_index,
        total_slides=len(carousel.spec.slides),
    )

    paths = list(carousel.slide_paths)
    paths[slide_index] = str(new_png_path)
    carousel.slide_paths = paths

    upsert_carousel(carousel)


def _render_caption_section(carousel: Carousel) -> None:
    st.markdown("#### Caption")
    caption_key = f"carousel_caption_{carousel.id}"
    st.session_state.setdefault(caption_key, carousel.final_caption)
    st.session_state[caption_key] = st.text_area(
        "Caption",
        value=st.session_state[caption_key],
        key=f"caption_area_{carousel.id}",
        label_visibility="collapsed",
        height=150,
    )

    st.markdown("#### Pinned Comment")
    pinned_key = f"carousel_pinned_{carousel.id}"
    st.session_state.setdefault(pinned_key, carousel.pinned_comment)
    st.session_state[pinned_key] = st.text_area(
        "Pinned comment",
        value=st.session_state[pinned_key],
        key=f"pinned_area_{carousel.id}",
        label_visibility="collapsed",
        height=80,
    )


def _render_script_controls(carousel: Carousel) -> None:
    st.markdown("#### Script Controls")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if st.button("🔄 Resample hashtags", key=f"resample_hashtags_{carousel.id}"):
            try:
                carousel.final_hashtags = build_hashtags(
                    domain=_infer_domain(carousel),
                    hashtag_themes=carousel.spec.hashtag_themes,
                )
                st.rerun()
            except AssemblerError as e:
                st.error(f"Failed to resample hashtags: {e}")

    with col2:
        st.text_input(
            "Tweak instruction",
            placeholder="e.g. make the hook sharper",
            key=f"tweak_input_{carousel.id}",
            label_visibility="collapsed",
            disabled=True,
        )
        st.button(
            "🪄 Tweak whole carousel",
            key=f"tweak_btn_{carousel.id}",
            help="Full regenerate coming in v1.1",
            disabled=True,
        )

    with col3:
        if st.button("✅ Approve & Sync", key=f"approve_btn_{carousel.id}"):
            try:
                bundle_dir = export_carousel(carousel, EXPORT_OUTPUT_DIR)
                update_carousel_status(carousel.id, CarouselStatus.approved, "approved_at")
                carousel.status = CarouselStatus.approved
                st.session_state[f"carousel_approved_{carousel.id}"] = True
                st.success(f"Synced to {bundle_dir}")
            except AssemblerError as e:
                st.error(f"Export failed: {e}")
            except Exception as e:
                st.error(f"Approve & Sync failed: {e}")

    with col4:
        st.button(
            "📤 Publish to Instagram",
            key=f"publish_btn_{carousel.id}",
            help="Direct publishing arrives in v2",
            disabled=True,
        )


def _render_hashtag_display(carousel: Carousel) -> None:
    st.markdown("#### Hashtags")
    st.caption(f"{len(carousel.final_hashtags)} hashtags")
    st.code(" ".join(carousel.final_hashtags), language=None)
