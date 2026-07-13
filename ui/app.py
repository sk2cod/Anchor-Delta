import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from config import CAROUSEL_DOMAINS, FRESHNESS_HOURS, MAX_ACTIVE_CARDS
from db.cards import get_active_cards, get_archived_cards, get_card_by_id
from db.delta_events import get_delta_events_for_card, get_last_run_per_domain
from db.noise_log import get_noise_log_since
from db.transmissions import get_transmission_for_card
from pipeline.runner import run_pipeline

st.set_page_config(
    page_title="Anchor & Delta",
    page_icon="⚓",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        max-width: 860px;
        margin-left: auto;
        margin-right: auto;
    }

    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
            Helvetica, Arial, sans-serif;
    }

    .ad-card {
        background-color: transparent;
        border-radius: 16px;
        padding: 20px;
        border: 1px solid #1B2A4A !important;
        border-left: 4px solid #1B2A4A !important;
    }

    .stTabs [data-baseweb="tab"] p {
        font-size: 1.05rem;
    }

    .stTabs [data-baseweb="tab-list"] {
        overflow-x: auto;
        flex-wrap: nowrap;
    }

    blockquote {
        border-left: 3px solid #4A6FA5;
        padding-left: 16px;
        margin: 8px 0;
    }

    blockquote, blockquote p, blockquote em, blockquote strong, blockquote span {
        color: #D0D8E4 !important;
        font-style: italic;
    }

    blockquote strong {
        color: #A0B4CC !important;
        font-style: normal;
        font-weight: 600;
    }

    #MainMenu {
        visibility: hidden;
    }

    footer {
        visibility: hidden;
    }

    [data-testid="stToolbar"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }
    .stAppDeployButton { display: none !important; }
    [data-baseweb="tab-list"] button[aria-label="scroll left"],
    [data-baseweb="tab-list"] button[aria-label="scroll right"] {
        display: none !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ── Helper functions ──────────────────────────────────────────────────────────

def _chain_latex_to_text(latex: str) -> str:
    text = latex
    text = text.replace(r'\longrightarrow', '→')
    text = text.replace(r'\rightarrow', '→')
    text = text.replace(r'\approx', '≈')
    text = text.replace(r'\geq', '≥')
    text = text.replace(r'\leq', '≤')
    text = text.replace(r'\%', '%')
    text = text.replace(r'\$', '$')
    text = re.sub(r'\\text\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    return text.strip()


def _format_card_header(card, last_updated_at=None):
    ts = last_updated_at or card["last_delta_at"]
    last_updated = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(
        ZoneInfo("Australia/Sydney")
    )
    now_sydney = datetime.now(ZoneInfo("Australia/Sydney"))
    hours_ago = (now_sydney - last_updated).total_seconds() / 3600

    is_research = card.get("source", "pipeline") == "research"
    badge_new = "🔍 RESEARCH" if is_research else "🔴 NEW"
    badge_old = "🔍 RESEARCH" if is_research else "📌"

    if hours_ago < 3:
        hours_int = max(1, round(hours_ago))
        timestamp = f"updated {hours_int} hour{'s' if hours_int != 1 else ''} ago"
        return f"{badge_new} · {card['umbrella_title']} — {timestamp}"
    elif hours_ago < 24:
        time_str = last_updated.strftime("%I:%M %p").lstrip("0")
        timestamp = f"updated today at {time_str}"
        return f"{badge_new} · {card['umbrella_title']} — {timestamp}"
    else:
        days_ago = max(1, int(hours_ago // 24))
        timestamp = f"updated {days_ago} day{'s' if days_ago != 1 else ''} ago"
        return f"{badge_old} · {card['umbrella_title']} — {timestamp}"


def _format_run_timestamp(ts):
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(
        ZoneInfo("Australia/Sydney")
    )
    date_str = dt.strftime("%A, %d %B %Y")
    time_str = dt.strftime("%I:%M %p").lstrip("0")
    return f"{date_str} at {time_str}"


def format_elapsed(seconds):
    if seconds < 60:
        return f"{int(seconds)}s"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}m {secs}s"


_THIN_DIVIDER = "<hr style='margin:8px 0;border:none;border-top:0.5px solid rgba(255,255,255,0.1);'>"


def _section_label(text: str) -> str:
    return (
        f"<p style='font-size:11px;text-transform:uppercase;color:#888;"
        f"letter-spacing:0.08em;margin:16px 0 6px 0;'>{text}</p>"
    )


def _render_event_block(event: dict):
    headline = event.get("headline") or event.get("event_headline", "")
    date_str = event.get("event_date", "")
    try:
        formatted_date = datetime.strptime(str(date_str), "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0", " ")
    except Exception:
        formatted_date = str(date_str)
    st.markdown(
        f"<p style='font-size:15px;font-weight:500;margin:4px 0 2px 0;'>{headline}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='font-size:12px;color:#888;margin:0 0 6px 0;'>{formatted_date}</p>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='font-size:14px;line-height:1.7;margin:0 0 8px 0;'>{event.get('what_happened', '')}</p>",
        unsafe_allow_html=True,
    )
    for turn in event.get("dialogue") or []:
        st.markdown(
            f"<div style='border-left:2px solid rgba(255,255,255,0.2);padding-left:12px;margin:6px 0;'>"
            f"<span style='font-size:12px;color:#888;'>{turn['speaker']}</span><br>"
            f"<span style='font-size:14px;font-style:italic;'>\"{turn['quote']}\"</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def _render_nodes_markdown(nodes_md: str):
    blocks = re.split(r'\n\n+', nodes_md.strip())
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.split('\n')
        first_line = lines[0].strip()

        title_only = re.match(r'^\*\*(.+?)\*\*\s*$', first_line)
        title_inline = re.match(r'^\*\*(.+?)\*\*[:\s]+(.+)$', first_line, re.DOTALL)
        heading = re.match(r'^#{1,4}\s+(.+)$', first_line)

        if title_only:
            title = title_only.group(1).strip()
            st.markdown(
                f"<p style='font-size:16px;font-weight:500;color:var(--color-text-primary);margin-top:1.5rem;margin-bottom:4px;display:block;border-top:0.5px solid rgba(255,255,255,0.1);padding-top:1rem;'>{title}</p>",
                unsafe_allow_html=True,
            )
            body = '\n'.join(lines[1:]).strip()
            if body:
                st.markdown(body)
        elif title_inline:
            title = title_inline.group(1).strip()
            rest = title_inline.group(2).strip()
            st.markdown(
                f"<p style='font-size:16px;font-weight:500;color:var(--color-text-primary);margin-top:1.5rem;margin-bottom:4px;display:block;border-top:0.5px solid rgba(255,255,255,0.1);padding-top:1rem;'>{title}</p>",
                unsafe_allow_html=True,
            )
            body = '\n'.join([rest] + lines[1:]).strip()
            if body:
                st.markdown(body)
        elif heading:
            title = heading.group(1).strip()
            st.markdown(
                f"<p style='font-size:16px;font-weight:500;color:var(--color-text-primary);margin-top:1.5rem;margin-bottom:4px;display:block;border-top:0.5px solid rgba(255,255,255,0.1);padding-top:1rem;'>{title}</p>",
                unsafe_allow_html=True,
            )
            body = '\n'.join(lines[1:]).strip()
            if body:
                st.markdown(body)
        else:
            st.markdown(block)


def render_card(card_data):
    card = card_data["card"]
    delta_events = card_data["delta_events"]
    transmission = card_data["transmission"]

    latest = delta_events[0] if delta_events else None
    older = delta_events[1:] if delta_events else []

    last_updated_at = (
        max(e["created_at"] for e in delta_events if e.get("created_at"))
        if delta_events else None
    )

    with st.expander(_format_card_header(card, last_updated_at=last_updated_at)):
        if latest and latest.get("tldr"):
            st.markdown(
                f"<p style='font-size:17px;font-weight:500;border-left:4px solid #E24B4A;"
                f"padding-left:12px;margin:0 0 16px 0;'>{latest['tldr']}</p>",
                unsafe_allow_html=True,
            )

        st.markdown(_section_label("⚡ LATEST"), unsafe_allow_html=True)

        if latest:
            _render_event_block(latest)

        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)
        st.markdown(_section_label("THE CORE ANCHOR"), unsafe_allow_html=True)

        st.markdown(
            f"<div style='background:rgba(255,255,255,0.05);border-radius:8px;padding:12px 14px;"
            f"font-size:14px;line-height:1.7;'>{card['anchor_text']}</div>",
            unsafe_allow_html=True,
        )

        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)

        if older:
            with st.expander("📖 Previous Chapters", expanded=False):
                for index, event in enumerate(older):
                    _render_event_block(event)
                    if index < len(older) - 1:
                        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)

        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)
        st.markdown(_section_label("🧩 CONCEPTUAL TRANSMISSION"), unsafe_allow_html=True)

        if transmission:
            chain_text = _chain_latex_to_text(transmission["chain_latex"])
            st.markdown(
                f"<div style='background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 14px;"
                f"font-family:monospace;font-size:14px;'>{chain_text}</div>",
                unsafe_allow_html=True,
            )
            _render_nodes_markdown(transmission["nodes_markdown"])
        else:
            st.markdown(
                "<p style='font-size:11px;color:#888;'>Transmission not yet generated.</p>",
                unsafe_allow_html=True,
            )

        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)
        if not card.get('is_archived', False):
            if card.get('domain') in ('world', 'finance', 'ai_tech'):
                with st.expander("🖼️ Cover image keywords (optional)", expanded=False):
                    st.text_input(
                        "Keywords (optional — overrides the auto-derived subject entirely)",
                        placeholder="e.g. uranium enrichment facility",
                        key=f"gen_image_keywords_{card['id']}",
                    )
                    st.checkbox(
                        "Portrait / person composition",
                        key=f"gen_image_is_person_{card['id']}",
                        value=False,
                    )

            col1, col2, col3, col4 = st.columns([4, 1, 1, 1])
            with col2:
                if st.button("📦", key=f"archive_{card['id']}", help="Archive this card"):
                    st.session_state[f"confirm_archive_{card['id']}"] = True
            with col3:
                if st.button("🗑️", key=f"delete_{card['id']}", help="Delete this card permanently"):
                    st.session_state[f"confirm_delete_{card['id']}"] = True
            with col4:
                if card.get('domain') in ('world', 'finance', 'ai_tech'):
                    carousel_key = f"generate_carousel_{card['id']}"
                    if st.button("🎠", key=carousel_key, help="Generate Instagram carousel"):
                        st.session_state[f"carousel_generating_{card['id']}"] = True

            if st.session_state.get(f"confirm_archive_{card['id']}", False):
                st.warning("Move this card to Archive?")
                col_yes, col_no = st.columns([1, 1])
                with col_yes:
                    if st.button("Yes, archive", key=f"archive_yes_{card['id']}"):
                        from db.cards import archive_card
                        archive_card(card['id'])
                        st.session_state[f"confirm_archive_{card['id']}"] = False
                        st.rerun()
                with col_no:
                    if st.button("Cancel", key=f"archive_no_{card['id']}"):
                        st.session_state[f"confirm_archive_{card['id']}"] = False
                        st.rerun()
        else:
            col1, col2 = st.columns([6, 1])
            with col2:
                if st.button("🗑️", key=f"delete_{card['id']}", help="Delete this card permanently"):
                    st.session_state[f"confirm_delete_{card['id']}"] = True

        if st.session_state.get(f"confirm_delete_{card['id']}", False):
            st.warning("Delete this card permanently?")
            col_yes, col_no = st.columns([1, 1])
            with col_yes:
                if st.button("Yes, delete", key=f"confirm_yes_{card['id']}"):
                    from db.cards import delete_card
                    delete_card(card['id'])
                    st.session_state[f"confirm_delete_{card['id']}"] = False
                    st.rerun()
            with col_no:
                if st.button("Cancel", key=f"confirm_no_{card['id']}"):
                    st.session_state[f"confirm_delete_{card['id']}"] = False
                    st.rerun()

        if card.get('domain') in ('world', 'finance', 'ai_tech'):
            if st.session_state.get(f"carousel_generating_{card['id']}"):
                with st.spinner("Generating carousel..."):
                    try:
                        from carousel.loader import load_card
                        from carousel.context_builder import build_context
                        from carousel.writer import write_carousel
                        from carousel.layout_picker import pick_layouts
                        from carousel.renderer import render_carousel
                        from carousel.assembler import assemble_carousel

                        story_card = load_card(card['id'])
                        context = build_context(story_card)

                        # Manual cover-image keyword override (optional) —
                        # full override of the Haiku-derived visual_subject,
                        # not a blend with it, same convention as the
                        # regenerate-image button in ui/carousel_view.py.
                        gen_keywords = st.session_state.get(
                            f"gen_image_keywords_{card['id']}", ""
                        ).strip()
                        if gen_keywords:
                            context.visual_subject = gen_keywords
                            context.visual_subject_is_person = st.session_state.get(
                                f"gen_image_is_person_{card['id']}", False
                            )

                        spec = write_carousel(
                            context, card_id=card['id']
                        )
                        enriched = pick_layouts(spec, domain=context.domain)
                        paths = render_carousel(enriched)
                        carousel = assemble_carousel(
                            enriched, paths,
                            domain=context.domain,
                            card_id=card['id'],
                            persist=True,
                        )
                        st.session_state[
                            f"carousel_{card['id']}"
                        ] = carousel
                        st.session_state[
                            f"carousel_generating_{card['id']}"
                        ] = False
                        st.rerun()

                    except Exception as e:
                        st.error(f"Carousel generation failed: {e}")
                        st.session_state[
                            f"carousel_generating_{card['id']}"
                        ] = False

            if f"carousel_{card['id']}" in st.session_state:
                from ui.carousel_view import render_carousel_preview
                carousel = st.session_state[f"carousel_{card['id']}"]
                render_carousel_preview(carousel)


DOMAIN_KEYS = {
    "🌍 World": "world",
    "💹 Finance": "finance",
    "🤖 AI & Tech": "ai_tech",
    "🌏 Australia": "australia",
    "🌐 India": "india",
}

DOMAIN_PLACEHOLDER = "No active cards in this domain yet. Run the pipeline to fetch stories."


def _format_domain_last_run(domain_key: str, domain_last_run: dict) -> str:
    iso = domain_last_run.get(domain_key)
    if not iso:
        return "never run"
    dt = datetime.fromisoformat(iso).astimezone(ZoneInfo("Australia/Sydney"))
    now = datetime.now(ZoneInfo("Australia/Sydney"))
    if dt.date() == now.date():
        return "last run today at " + dt.strftime("%I:%M %p").lstrip("0")
    if (now.date() - dt.date()).days == 1:
        return "last run yesterday"
    return "last run " + dt.strftime("%d %b")


def render_domain_tab(domain_key, domain_last_run):
    st.caption(_format_domain_last_run(domain_key, domain_last_run))
    cards = get_active_cards(domain=domain_key)
    if not cards:
        st.info(DOMAIN_PLACEHOLDER)
    else:
        for card in cards:
            render_card(
                {
                    "card": card,
                    "delta_events": get_delta_events_for_card(card["id"]),
                    "transmission": get_transmission_for_card(card["id"]),
                }
            )

    with st.expander("🗑️ Noise Log — last 24 hours", expanded=False):
        noise = get_noise_log_since(hours=24)
        if not noise:
            st.caption("No noise logged in the last 24 hours.")
        else:
            for entry in noise:
                st.markdown(f"**{entry['gate_failed']}** — {entry['headline']}")
                st.caption(f"{entry['reason']} · {entry['logged_at']}")
                st.divider()


# ── Page header ───────────────────────────────────────────────────────────────

st.title("⚓ Anchor & Delta")
today_str = datetime.now(ZoneInfo("Australia/Sydney")).strftime("%A, %d %B %Y")
st.caption(today_str)

# ── Research row ──────────────────────────────────────────────────────────────

if 'research_running' not in st.session_state:
    st.session_state.research_running = False

col1, col2 = st.columns([5, 1])
with col1:
    user_query = st.text_input("Query", placeholder="", label_visibility="collapsed", key="query_input")
with col2:
    research_clicked = st.button("🔍 Research", use_container_width=True, disabled=st.session_state.research_running)

if research_clicked and user_query:
    st.session_state.research_running = True
    with st.spinner("Researching with Gemini..."):
        from pipeline.engine import research_card
        from db.cards import create_card
        from db.delta_events import append_delta_event
        from difflib import SequenceMatcher
        import re as _re
        from datetime import date

        def _similar_title(a, b):
            return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.6

        result = research_card(user_query)
        import json as json_lib

        try:
            raw_clean = result["raw_text"].strip()
            if raw_clean.startswith("```"):
                raw_clean = _re.sub(r"```json|```", "", raw_clean).strip()
            parsed = json_lib.loads(raw_clean)

            umbrella_title = parsed.get("umbrella_title", user_query)
            domain = parsed.get("domain", "world").lower().strip()
            anchor_text = parsed.get("anchor", "")
            tldr = parsed.get("tldr", "")
            event_headline = parsed.get("event_headline", f"Research: {user_query}")
            what_happened = parsed.get("what_happened", "")
            chain = parsed.get("chain", "")

            nodes = parsed.get("nodes", [])
            nodes_markdown = ""
            for node in nodes:
                nodes_markdown += f"**{node.get('title', '')}**\n{node.get('text', '')}\n\n"

            dialogue_raw = parsed.get("dialogue", "")
            dialogue = []
            if dialogue_raw and ":" in dialogue_raw:
                parts = dialogue_raw.split(":", 1)
                if len(parts) == 2:
                    dialogue = [{"speaker": parts[0].strip(), "quote": parts[1].strip().strip('"')}]

            if domain not in ['world', 'finance', 'ai_tech', 'australia', 'india']:
                domain = 'world'

        except (json_lib.JSONDecodeError, KeyError) as e:
            st.error(f"Failed to parse Gemini response: {e}")
            st.session_state.research_running = False
            st.stop()

        existing_cards = get_active_cards(domain=domain)
        existing_card = None
        for card in existing_cards:
            if _similar_title(card['umbrella_title'], umbrella_title or user_query):
                existing_card = card
                break

        if existing_card:
            card_id = existing_card['id']
        else:
            card_result = create_card(
                domain=domain,
                umbrella_title=umbrella_title or user_query,
                anchor_text=anchor_text,
                source='research',
            )
            card_id = card_result['id'] if isinstance(card_result, dict) else card_result

        append_delta_event(
            card_id=card_id,
            event_date=date.today(),
            headline=event_headline or f"Research: {user_query}",
            what_happened=what_happened,
            dialogue=dialogue,
            tldr=tldr,
        )

        from db.transmissions import upsert_transmission
        upsert_transmission(
            card_id=card_id,
            chain_latex=chain,
            nodes_markdown=nodes_markdown,
        )

        st.success(f"Research card created: {umbrella_title}")
        st.session_state.research_running = False
        st.rerun()

# ── Pipeline buttons ──────────────────────────────────────────────────────────

_DOMAIN_LABELS = {
    "world": "🌍 World",
    "finance": "💹 Finance",
    "ai_tech": "🤖 AI & Tech",
    "australia": "🌏 Australia",
    "india": "🌐 India",
    CAROUSEL_DOMAINS: "🚀 Carousel Domains",
}

if "pending_domain" not in st.session_state:
    st.session_state.pending_domain = "NOT_SET"

st.markdown("**Run Pipeline**")
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("🌍 World", use_container_width=True):
        st.session_state.pending_domain = "world"
        st.rerun()
    if st.button("🌏 Australia", use_container_width=True):
        st.session_state.pending_domain = "australia"
        st.rerun()

with col2:
    if st.button("💹 Finance", use_container_width=True):
        st.session_state.pending_domain = "finance"
        st.rerun()
    if st.button("🌐 India", use_container_width=True):
        st.session_state.pending_domain = "india"
        st.rerun()

with col3:
    if st.button("🤖 AI & Tech", use_container_width=True):
        st.session_state.pending_domain = "ai_tech"
        st.rerun()
    if st.button("🚀 Carousel Domains", use_container_width=True):
        st.session_state.pending_domain = CAROUSEL_DOMAINS
        st.rerun()

_run_triggered = False
_run_domain = None

if "pipeline_running" not in st.session_state:
    st.session_state.pipeline_running = False

if st.session_state.pipeline_running:
    _running_label = _DOMAIN_LABELS.get(st.session_state.get("_running_domain", "NOT_SET"), "🚀 Carousel Domains")
    st.info(f"⚙️ Running {_running_label} pipeline...")

elif st.session_state.pending_domain != "NOT_SET":
    _pending = st.session_state.pending_domain
    _label = _DOMAIN_LABELS.get(_pending, "🚀 Carousel Domains")
    col_msg, col_confirm, col_cancel = st.columns([4, 1, 1])
    with col_msg:
        st.info(f"▶ Run {_label} pipeline?")
    with col_confirm:
        if st.button("✅ Confirm", use_container_width=True):
            _run_domain = _pending
            _run_triggered = True
            st.session_state.pending_domain = "NOT_SET"
            st.session_state.pipeline_running = True
            st.session_state["_running_domain"] = _pending
    with col_cancel:
        if st.button("❌ Cancel", use_container_width=True):
            st.session_state.pending_domain = "NOT_SET"
            st.rerun()

if _run_triggered:
    progress_placeholder = st.empty()

    def _update_progress(results):
        counts = {"created": 0, "updated": 0, "noise": 0, "capped": 0, "error": 0}
        for result in results:
            counts[result["status"]] = counts.get(result["status"], 0) + 1
        progress_placeholder.info(
            f"Processing... Articles processed: {len(results)} | "
            f"Created: {counts['created']} | Updated: {counts['updated']} | "
            f"Noise: {counts['noise']}"
        )

    with st.spinner(f"Fetching and filtering news sources..."):
        run_results = run_pipeline(
            extra_queries=[user_query] if user_query else None,
            progress_callback=_update_progress,
            domain=_run_domain,
        )
    progress_placeholder.empty()
    st.session_state.pipeline_running = False
    st.session_state["last_run_results"] = run_results
    _now_iso = datetime.now(ZoneInfo("Australia/Sydney")).isoformat()
    st.session_state["last_run_at"] = _now_iso
    st.success("Pipeline complete.")
    st.rerun()

# ── Last run info (compact) ───────────────────────────────────────────────────

last_run_results = st.session_state.get("last_run_results")
if last_run_results:
    run_stats = last_run_results.get("run_stats", {})
    results = last_run_results["results"]
    status_counts = {"created": 0, "updated": 0, "noise": 0, "capped": 0, "error": 0}
    for r in results:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    last_run_at = st.session_state.get("last_run_at", "")
    timestamp_str = _format_run_timestamp(last_run_at) if last_run_at else "recent"
    cost = run_stats.get("estimated_cost_usd", 0)
    elapsed = format_elapsed(run_stats.get("elapsed_seconds", 0))
    fetch_stats = last_run_results.get("fetch_stats", {})
    rss_fetched = fetch_stats.get("rss_fetched", last_run_results.get("fetched", 0))
    survived_filter = fetch_stats.get("survived_filter", last_run_results.get("survived_filter", 0))
    reached_llm = fetch_stats.get("reached_llm", len(results))

    run_id = last_run_results.get("run_id", "")
    run_id_part = f" · Run #{run_id}" if run_id else ""
    st.caption(
        f"Last run: {timestamp_str}{run_id_part} · "
        f"Fetched {rss_fetched} · Survived filter {survived_filter} · Processed {reached_llm} · {elapsed}"
    )
    st.caption(
        f"Created {status_counts['created']} · Updated {status_counts['updated']} · "
        f"Noise {status_counts['noise']} · Capped {status_counts['capped']} · Error {status_counts['error']} · "
        f"Haiku {run_stats.get('haiku_calls', 0)} · Sonnet {run_stats.get('sonnet_calls', 0)} · "
        f"Est. cost ${cost:.2f}"
    )

    if last_run_results.get("archived", 0) > 0:
        st.info(f"📦 {last_run_results['archived']} stale cards archived")

if FRESHNESS_HOURS > 48:
    st.caption(f"⚠️ Bootstrap mode: fetching articles from last {FRESHNESS_HOURS // 24} days")

# ── Domain tabs ───────────────────────────────────────────────────────────────

domain_last_run = get_last_run_per_domain()
active_cards = get_active_cards()
domain_counts = Counter(c['domain'] for c in active_cards)
total = len(active_cards)
st.caption(f"Active cards: {total} / {MAX_ACTIVE_CARDS}")

tabs = st.tabs([
    f"🌍 World ({domain_counts.get('world', 0)})",
    f"💹 Finance ({domain_counts.get('finance', 0)})",
    f"🤖 AI & Tech ({domain_counts.get('ai_tech', 0)})",
    f"🌏 Australia ({domain_counts.get('australia', 0)})",
    f"🌐 India ({domain_counts.get('india', 0)})",
])

with tabs[0]:
    render_domain_tab("world", domain_last_run)

with tabs[1]:
    render_domain_tab("finance", domain_last_run)

with tabs[2]:
    render_domain_tab("ai_tech", domain_last_run)

with tabs[3]:
    render_domain_tab("australia", domain_last_run)

with tabs[4]:
    render_domain_tab("india", domain_last_run)

# ── Archive ───────────────────────────────────────────────────────────────────

with st.expander("📦 Archive"):
    all_archived = get_archived_cards()
    if not all_archived:
        st.caption("No archived cards yet.")
    else:
        for domain_label, domain_key in DOMAIN_KEYS.items():
            domain_cards = get_archived_cards(domain=domain_key)
            if domain_cards:
                with st.expander(f"{domain_label} ({len(domain_cards)})"):
                    for card in domain_cards:
                        render_card(
                            {
                                "card": card,
                                "delta_events": get_delta_events_for_card(card["id"]),
                                "transmission": get_transmission_for_card(card["id"]),
                            }
                        )

# ── Danger Zone ───────────────────────────────────────────────────────────────

with st.expander("⚠️ Danger Zone"):
    st.caption("This will permanently delete all cards, delta events, transmissions, noise log, and processed articles. This cannot be undone.")
    if st.button("🗑️ Hard Delete All Data", type="secondary"):
        from db.cards import hard_delete_all_cards
        result = hard_delete_all_cards()
        st.success(f"Database wiped: {result}")
        st.rerun()
