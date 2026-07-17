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
from carousel.models import Carousel, CarouselStatus, SlotRole
from carousel.renderer import render_slide
from db.cards import get_card_by_id
from db.carousel_queries import update_carousel_status, upsert_carousel

EXPORT_OUTPUT_DIR = Path("outputs") / "bundles"

# Short fixed labels so the "{i+1} · {role}" caption never wraps inside the
# narrow per-slide card column.
ROLE_ABBREV = {
    "hook": "hook",
    "event": "event",
    "setup": "setup",
    "pivot": "pivot",
    "mechanism": "mech",
    "concept": "concpt",
    "contrast": "ctrst",
    "proof": "proof",
    "payoff": "payoff",
    "cta": "cta",
}


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
            # Bordered container groups thumbnail + label + controls into
            # one cohesive per-slide card unit (native primitive, no CSS).
            with st.container(border=True):
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
                st.caption(f"{i + 1} · {ROLE_ABBREV.get(slide.role.value, slide.role.value)}")
                _render_slide_controls(carousel, i, slide)

    # Edit panel renders full-width below the entire slide row (standard
    # Streamlit inline-edit pattern, matches the caption editor further
    # down) rather than inside a narrow per-slide card column.
    for i, slide in enumerate(slides):
        if st.session_state.get(f"editing_slide_{carousel.id}_{i}", False):
            _render_edit_panel(carousel, i, slide)

    # Image regenerate panel — same full-width-below-the-row pattern as
    # the edit panel above (not inside the narrow column, which was the
    # original bug here: cramped text input + checkbox + button squeezed
    # into a 270px column read as broken, not just tight).
    for i, slide in enumerate(slides):
        if slide.role == SlotRole.hook and st.session_state.get(
            f"image_regen_open_{carousel.id}_{i}", False
        ):
            _render_image_regenerate_controls(carousel, i, slide)


def _render_slide_controls(carousel: Carousel, index: int, slide) -> None:
    edit_key = f"editing_slide_{carousel.id}_{index}"

    btn_cols = st.columns(2)
    with btn_cols[0]:
        if st.button("✏️", key=f"edit_btn_{carousel.id}_{index}", help="Edit this slide"):
            st.session_state[edit_key] = not st.session_state.get(edit_key, False)
    with btn_cols[1]:
        regen_instruction = st.text_input(
            "Regenerate instruction (optional)",
            placeholder="e.g. make the hook sharper",
            key=f"regen_instruction_{carousel.id}_{index}",
            label_visibility="collapsed",
        )
        if st.button("🔄", key=f"regen_{carousel.id}_{index}",
                     help="Regenerate this slide"):
            with st.spinner("Regenerating slide..."):
                try:
                    from carousel.writer import regenerate_slide
                    domain = _infer_domain(carousel)
                    new_slide = regenerate_slide(
                        spec=carousel.spec,
                        slot_id=slide.slot_id,
                        domain=domain,
                        card_id=carousel.card_id,
                        instruction=regen_instruction if regen_instruction else None,
                    )
                    for j, s in enumerate(carousel.spec.slides):
                        if s.slot_id == new_slide.slot_id:
                            # Save previous slide for undo
                            st.session_state[
                                f"prev_slide_{carousel.id}_{index}"
                            ] = carousel.spec.slides[j].model_copy()
                            carousel.spec.slides[j] = new_slide
                            break
                    enriched = pick_layouts(carousel.spec, domain)
                    target_enriched = next(
                        es for es in enriched.slides
                        if es.slide.slot_id == new_slide.slot_id
                    )
                    new_path = render_slide(
                        target_enriched,
                        slide_index=index,
                        total_slides=len(carousel.spec.slides),
                        force=True,
                    )
                    paths = list(carousel.slide_paths)
                    paths[index] = str(new_path)
                    carousel.slide_paths = paths
                    upsert_carousel(carousel)
                    st.session_state[f"carousel_{carousel.card_id}"] = carousel
                    st.rerun()
                except Exception as e:
                    st.error(f"Regenerate failed: {e}")
        if st.session_state.get(f"prev_slide_{carousel.id}_{index}"):
            if st.button("↩️", key=f"undo_{carousel.id}_{index}",
                         help="Restore previous slide"):
                try:
                    prev = st.session_state[f"prev_slide_{carousel.id}_{index}"]
                    for j, s in enumerate(carousel.spec.slides):
                        if s.slot_id == prev.slot_id:
                            carousel.spec.slides[j] = prev
                            break
                    domain = _infer_domain(carousel)
                    enriched = pick_layouts(carousel.spec, domain)
                    target_enriched = next(
                        es for es in enriched.slides
                        if es.slide.slot_id == prev.slot_id
                    )
                    new_path = render_slide(
                        target_enriched,
                        slide_index=index,
                        total_slides=len(carousel.spec.slides),
                        force=True,
                    )
                    paths = list(carousel.slide_paths)
                    paths[index] = str(new_path)
                    carousel.slide_paths = paths
                    upsert_carousel(carousel)
                    st.session_state[f"carousel_{carousel.card_id}"] = carousel
                    # Clear undo state
                    st.session_state.pop(f"prev_slide_{carousel.id}_{index}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Undo failed: {e}")

    if slide.role == SlotRole.hook:
        image_regen_key = f"image_regen_open_{carousel.id}_{index}"
        if st.button("🖼️", key=f"image_regen_btn_{carousel.id}_{index}",
                     help="Regenerate cover image"):
            st.session_state[image_regen_key] = not st.session_state.get(
                image_regen_key, False
            )


def _render_image_regenerate_controls(carousel: Carousel, index: int, slide) -> None:
    """
    Hook-slide-only cover image regenerate. Text-only Sonnet regenerate
    (the 🔄 button above) never touches the image (Decision #64 — it
    preserves image_asset unchanged), and there was previously no way to
    get a new image without also getting new text. This is a pure image
    swap: one gpt-image-1 call via image_generator.generate_cover_image(),
    no Sonnet call, so headline/sub-heading are never touched.

    Keywords are a full override of the auto-derived visual_subject, not
    a blend with it — if the Haiku-derived subject was wrong (the
    original problem this button exists to fix), blending would still
    drag the wrong guess along. is_person is a manual toggle, not
    inferred or defaulted by this code: image generation policy makes a
    named public figure's likeness unreliable regardless of the flag,
    but that's the user's call to test, not something to silently gate.

    Rendered full-width below the entire slide row (see
    _render_slide_thumbnails) — not inside the narrow per-slide column,
    same reasoning as the edit panel.
    """
    st.markdown("##### 🖼️ Regenerate cover image")
    keywords = st.text_input(
        "Keywords (optional — overrides the auto-derived subject entirely)",
        placeholder="e.g. uranium enrichment facility",
        key=f"image_keywords_{carousel.id}_{index}",
    )
    is_person = st.checkbox(
        "Portrait / person composition",
        key=f"image_is_person_{carousel.id}_{index}",
        value=False,
    )
    if st.button("Regenerate image", key=f"regen_image_{carousel.id}_{index}"):
        with st.spinner("Generating new cover image..."):
            try:
                from carousel import image_generator
                from carousel.context_builder import build_context
                from carousel.loader import load_card

                domain = _infer_domain(carousel)
                if keywords.strip():
                    visual_subject = keywords.strip()
                    subject_is_person = is_person
                else:
                    context = build_context(load_card(carousel.card_id))
                    visual_subject = context.visual_subject
                    subject_is_person = context.visual_subject_is_person

                new_asset = image_generator.generate_cover_image(
                    visual_subject=visual_subject,
                    is_person=subject_is_person,
                    domain=domain,
                )
                if new_asset is None:
                    st.error(
                        "Image generation failed — check OPENAI_API_KEY, "
                        "billing, or logs for the underlying error."
                    )
                else:
                    carousel.spec.slides[index].image_asset = new_asset
                    enriched = pick_layouts(carousel.spec, domain)
                    target_enriched = enriched.slides[index]
                    new_path = render_slide(
                        target_enriched,
                        slide_index=index,
                        total_slides=len(carousel.spec.slides),
                        force=True,
                    )
                    paths = list(carousel.slide_paths)
                    paths[index] = str(new_path)
                    carousel.slide_paths = paths
                    upsert_carousel(carousel)
                    st.session_state[f"carousel_{carousel.card_id}"] = carousel
                    st.rerun()
            except Exception as e:
                st.error(f"Image regenerate failed: {e}")


def _render_edit_panel(carousel: Carousel, index: int, slide) -> None:
    # Inline text editor (Model C — no LLM call, $0 cost, Decision #16).
    # Rendered full-width below the slide row, not inside its card column.
    edit_key = f"editing_slide_{carousel.id}_{index}"
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
                # export_carousel() already unifies the Drive-upload and
                # local-fallback paths into one success/failure outcome
                # (carousel/assembler.py) — reaching here means the bundle
                # landed somewhere real either way, so both count as
                # "exported" (INFRA_DECISIONS.md follow-up on Decision #02).
                bundle_dir = export_carousel(carousel, EXPORT_OUTPUT_DIR)
                update_carousel_status(carousel.id, CarouselStatus.exported, "exported_at")
                carousel.status = CarouselStatus.exported
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
