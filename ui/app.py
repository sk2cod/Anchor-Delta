import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from config import FRESHNESS_HOURS
from db.cards import get_active_cards, get_archived_cards, get_card_by_id
from db.delta_events import get_delta_events_for_card
from db.noise_log import get_noise_log_since
from db.transmissions import get_transmission_for_card
from pipeline.runner import run_pipeline

st.set_page_config(
    page_title="Anchor & Delta",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
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

    button[data-testid="baseButton-header"] {
        background-color: rgba(255,255,255,0.1) !important;
        border-radius: 4px !important;
        opacity: 1 !important;
        visibility: visible !important;
    }

    button[data-testid="baseButton-header"]:hover {
        background-color: rgba(255,255,255,0.2) !important;
    }

    div[data-testid="collapsedControl"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        background-color: rgba(255,255,255,0.15) !important;
        border-radius: 4px !important;
    }

    div[data-testid="collapsedControl"] button {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
    }

    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("# ⚓ Anchor & Delta")
today_str = datetime.now(ZoneInfo("Australia/Sydney")).strftime("%A, %d %B %Y")
st.caption(today_str)


def _chain_latex_to_text(latex: str) -> str:
    import re
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
    text = text.strip()
    return text


def _format_card_header(card):
    last_updated = datetime.fromisoformat(str(card["last_delta_at"]).replace("Z", "+00:00")).astimezone(
        ZoneInfo("Australia/Sydney")
    )
    now_sydney = datetime.now(ZoneInfo("Australia/Sydney"))
    hours_ago = (now_sydney - last_updated).total_seconds() / 3600

    if hours_ago < 3:
        hours_int = max(1, round(hours_ago))
        timestamp = f"updated {hours_int} hour{'s' if hours_int != 1 else ''} ago"
        return f"🔴 NEW · {card['umbrella_title']} — {timestamp}"
    elif hours_ago < 24:
        time_str = last_updated.strftime("%I:%M %p").lstrip("0")
        timestamp = f"updated today at {time_str}"
        return f"🔴 NEW · {card['umbrella_title']} — {timestamp}"
    else:
        days_ago = max(1, int(hours_ago // 24))
        timestamp = f"updated {days_ago} day{'s' if days_ago != 1 else ''} ago"
        return f"📌 {card['umbrella_title']} — {timestamp}"


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

    with st.expander(_format_card_header(card)):
        # 1. tldr hook — Level 1: 17px, weight 500, red left border
        if latest and latest.get("tldr"):
            st.markdown(
                f"<p style='font-size:17px;font-weight:500;border-left:4px solid #E24B4A;"
                f"padding-left:12px;margin:0 0 16px 0;'>{latest['tldr']}</p>",
                unsafe_allow_html=True,
            )

        # 2. ⚡ LATEST section label — Level 3
        st.markdown(_section_label("⚡ LATEST"), unsafe_allow_html=True)

        # 3–7. Latest event block
        if latest:
            _render_event_block(latest)

        # 8. Thin divider
        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)

        # 9. THE CORE ANCHOR section label — Level 3
        st.markdown(_section_label("THE CORE ANCHOR"), unsafe_allow_html=True)

        # 10. Anchor text in muted background box
        st.markdown(
            f"<div style='background:rgba(255,255,255,0.05);border-radius:8px;padding:12px 14px;"
            f"font-size:14px;line-height:1.7;'>{card['anchor_text']}</div>",
            unsafe_allow_html=True,
        )

        # 11. Thin divider
        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)

        # 12. Previous Chapters expander
        if older:
            with st.expander("📖 Previous Chapters", expanded=False):
                for index, event in enumerate(older):
                    _render_event_block(event)
                    if index < len(older) - 1:
                        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)

        # 13. Thin divider
        st.markdown(_THIN_DIVIDER, unsafe_allow_html=True)

        # 14. 🧩 CONCEPTUAL TRANSMISSION section label — Level 3
        st.markdown(_section_label("🧩 CONCEPTUAL TRANSMISSION"), unsafe_allow_html=True)

        if transmission:
            # 15. Transmission chain in monospace box
            chain_text = _chain_latex_to_text(transmission["chain_latex"])
            st.markdown(
                f"<div style='background:rgba(255,255,255,0.05);border-radius:8px;padding:10px 14px;"
                f"font-family:monospace;font-size:14px;'>{chain_text}</div>",
                unsafe_allow_html=True,
            )
            # 16. Node titles (14px, weight 500) + explanations (14px body)
            _render_nodes_markdown(transmission["nodes_markdown"])
        else:
            st.markdown(
                "<p style='font-size:11px;color:#888;'>Transmission not yet generated.</p>",
                unsafe_allow_html=True,
            )


DOMAIN_KEYS = {
    "🌍 World": "world",
    "💹 Finance": "finance",
    "🤖 AI & Tech": "ai_tech",
    "🌏 Australia": "australia",
    "🌐 India": "india",
}


def render_domain_tab(domain_key):
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
        domain_noise = [n for n in noise if True]  # show all noise for now
        if not domain_noise:
            st.caption("No noise logged in the last 24 hours.")
        else:
            for entry in domain_noise:
                st.markdown(f"**{entry['gate_failed']}** — {entry['headline']}")
                st.caption(f"{entry['reason']} · {entry['logged_at']}")
                st.divider()


DOMAIN_PLACEHOLDER = "No active cards in this domain yet. Run the pipeline to fetch stories."

(
    tab_world,
    tab_finance,
    tab_ai_tech,
    tab_australia,
    tab_india,
) = st.tabs(["🌍 World", "💹 Finance", "🤖 AI & Tech", "🌏 Australia", "🌐 India"])

with tab_world:
    render_domain_tab("world")

with tab_finance:
    render_domain_tab("finance")

with tab_ai_tech:
    render_domain_tab("ai_tech")

with tab_australia:
    render_domain_tab("australia")

with tab_india:
    render_domain_tab("india")

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


with st.sidebar:
    st.header("⚙️ Pipeline")

    all_noise = get_noise_log_since(hours=876000)
    if not all_noise:
        st.caption("No pipeline runs yet.")
    else:
        last_logged_at = max(entry["logged_at"] for entry in all_noise)
        st.caption(f"Last run: {_format_run_timestamp(last_logged_at)}")

    col1, col2 = st.columns([3, 1])
    with col1:
        user_query = st.text_input("", placeholder="e.g. Dharavi rehabilitation FSI Mumbai", label_visibility="collapsed", key="query_input")
    with col2:
        research_clicked = st.button("🔍", help="Research this topic with Gemini")

    if research_clicked and user_query:
        with st.spinner("Researching with Gemini..."):
            from pipeline.engine import research_card
            from db.cards import create_card
            from db.delta_events import append_delta_event
            import re as _re
            from datetime import date

            result = research_card(user_query)
            raw = result["raw_text"]

            def extract_field(text, field):
                pattern = f"{field}:(.*?)(?=\\n[A-Z_]+:|$)"
                match = _re.search(pattern, text, _re.DOTALL | _re.IGNORECASE)
                return match.group(1).strip() if match else ""

            umbrella_title = extract_field(raw, "UMBRELLA_TITLE")
            domain = extract_field(raw, "DOMAIN").lower().strip()
            anchor_text = extract_field(raw, "ANCHOR")
            tldr = extract_field(raw, "TLDR")
            event_headline = extract_field(raw, "EVENT_HEADLINE")
            what_happened = extract_field(raw, "WHAT_HAPPENED")
            chain = extract_field(raw, "CHAIN")
            nodes = extract_field(raw, "NODES")

            if domain not in ['world', 'finance', 'ai_tech', 'australia', 'india']:
                domain = 'world'

            card_id = create_card(
                domain=domain,
                umbrella_title=umbrella_title or user_query,
                anchor_text=anchor_text
            )

            append_delta_event(
                card_id=card_id,
                event_headline=event_headline or f"Research: {user_query}",
                what_happened=what_happened,
                dialogue=[],
                event_date=date.today(),
                tldr=tldr
            )

            from db.transmissions import upsert_transmission
            upsert_transmission(
                card_id=card_id,
                chain_latex=chain,
                nodes_markdown=nodes
            )

            st.success(f"Research card created: {umbrella_title}")
            st.rerun()

    if st.button("🚀 Run Pipeline"):
        progress_placeholder = st.empty()

        def _update_progress(results):
            counts = {"created": 0, "updated": 0, "noise": 0, "capped": 0, "error": 0}
            for result in results:
                counts[result["status"]] = counts.get(result["status"], 0) + 1
            progress_placeholder.info(
                f"⚙️ Processing... Articles processed: {len(results)} | "
                f"Created: {counts['created']} | Updated: {counts['updated']} | "
                f"Noise: {counts['noise']}"
            )

        with st.spinner("Fetching and filtering news sources..."):
            run_results = run_pipeline(
                extra_queries=[user_query] if user_query else None,
                progress_callback=_update_progress,
            )
        progress_placeholder.empty()
        st.session_state["last_run_results"] = run_results
        st.success("Pipeline complete.")
        st.rerun()

    if FRESHNESS_HOURS > 48:
        st.caption(f"⚠️ Bootstrap mode: fetching articles from last {FRESHNESS_HOURS // 24} days")
    else:
        st.caption(f"Daily mode: fetching articles from last {FRESHNESS_HOURS} hours")

    last_run_results = st.session_state.get("last_run_results")
    if last_run_results:
        results = last_run_results["results"]

        col_fetched, col_survived, col_processed = st.columns(3)
        col_fetched.metric("Fetched", last_run_results["fetched"])
        col_survived.metric("Survived Filter", last_run_results["survived_filter"])
        col_processed.metric("Total Processed", len(results))

        run_stats = last_run_results.get("run_stats", {})
        col_time, col_haiku, col_sonnet, col_cost = st.columns(4)
        col_time.metric("Run time", format_elapsed(run_stats.get('elapsed_seconds', 0)))
        col_haiku.metric("Haiku calls", run_stats.get("haiku_calls", 0))
        col_sonnet.metric("Sonnet calls", run_stats.get("sonnet_calls", 0))
        col_cost.metric("Est. cost", f"${run_stats.get('estimated_cost_usd', 0):.2f}")

        status_counts = {"created": 0, "updated": 0, "noise": 0, "capped": 0, "error": 0}
        for result in results:
            status_counts[result["status"]] = status_counts.get(result["status"], 0) + 1
        st.markdown(
            " · ".join(f"**{status}**: {count}" for status, count in status_counts.items())
        )

        st.subheader("Cards Created or Updated")
        created_or_updated = [r for r in results if r["status"] in ("created", "updated")]
        if not created_or_updated:
            st.caption("No cards created or updated in this run.")
        else:
            for result in created_or_updated:
                card = get_card_by_id(result["card_id"])
                if not card:
                    continue
                col_title, col_badge = st.columns([4, 1])
                col_title.write(card["umbrella_title"])
                col_badge.badge(result["status"])

    with st.expander("⚠️ Danger Zone", expanded=False):
        st.caption("This will permanently delete all cards, delta events, transmissions, noise log, and processed articles. This cannot be undone.")
        if st.button("🗑️ Hard Delete All Data", type="secondary"):
            from db.cards import hard_delete_all_cards
            result = hard_delete_all_cards()
            st.success(f"Database wiped: {result}")
            st.rerun()

    st.divider()
    st.header("🗄️ Archive")

    all_archived = get_archived_cards()
    if not all_archived:
        st.caption("No archived cards yet.")
    else:
        for domain_label, domain_key in DOMAIN_KEYS.items():
            domain_cards = get_archived_cards(domain=domain_key)
            with st.expander(f"{domain_label} ({len(domain_cards)})"):
                for card in domain_cards:
                    render_card(
                        {
                            "card": card,
                            "delta_events": get_delta_events_for_card(card["id"]),
                            "transmission": get_transmission_for_card(card["id"]),
                        }
                    )
