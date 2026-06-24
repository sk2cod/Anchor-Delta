import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from db.cards import get_active_cards, get_archived_cards, get_card_by_id
from db.delta_events import get_delta_events_for_card
from db.noise_log import get_noise_log_since
from db.transmissions import get_transmission_for_card
from pipeline.runner import run_pipeline

st.set_page_config(
    page_title="Anchor & Delta",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="collapsed",
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


def render_card(card_data):
    card = card_data["card"]
    delta_events = card_data["delta_events"]
    transmission = card_data["transmission"]

    last_updated = datetime.fromisoformat(str(card["last_delta_at"]).replace("Z", "+00:00"))
    last_updated_str = last_updated.astimezone(ZoneInfo("Australia/Sydney")).strftime("%d %b %Y")

    with st.expander(f"📌 {card['umbrella_title']} — last updated {last_updated_str}"):
        st.caption("THE CORE ANCHOR")
        st.markdown(
            f'<div class="ad-card">{card["anchor_text"]}</div>',
            unsafe_allow_html=True,
        )

        st.caption("⚡ LIVE STATUS TRACKER")
        for index, event in enumerate(delta_events):
            st.subheader(f"{event['event_date']} — {event['headline']}")
            st.write(event["what_happened"])
            for turn in event.get("dialogue") or []:
                st.markdown(f'> **{turn["speaker"]}:** *"{turn["quote"]}"*')
            if index < len(delta_events) - 1:
                st.divider()

        st.caption("🧩 THE CONCEPTUAL TRANSMISSION")
        if transmission:
            st.markdown(_chain_latex_to_text(transmission["chain_latex"]))
            st.markdown(transmission["nodes_markdown"])
        else:
            st.caption("Transmission not yet generated.")


DOMAIN_KEYS = {
    "🌍 Geopolitics": "geopolitics",
    "📰 Top Stories": "top_stories",
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


(
    tab_geopolitics,
    tab_top_stories,
    tab_finance,
    tab_ai_tech,
    tab_australia,
    tab_india,
    tab_pipeline,
    tab_archive,
) = st.tabs(
    [
        "🌍 Geopolitics",
        "📰 Top Stories",
        "💹 Finance",
        "🤖 AI & Tech",
        "🌏 Australia",
        "🌐 India",
        "⚙️ Pipeline",
        "🗄️ Archive",
    ]
)

DOMAIN_PLACEHOLDER = "No active cards in this domain yet. Run the pipeline to fetch stories."

with tab_geopolitics:
    render_domain_tab(DOMAIN_KEYS["🌍 Geopolitics"])

with tab_top_stories:
    render_domain_tab(DOMAIN_KEYS["📰 Top Stories"])

with tab_finance:
    render_domain_tab(DOMAIN_KEYS["💹 Finance"])

with tab_ai_tech:
    render_domain_tab(DOMAIN_KEYS["🤖 AI & Tech"])

with tab_australia:
    render_domain_tab(DOMAIN_KEYS["🌏 Australia"])

with tab_india:
    render_domain_tab(DOMAIN_KEYS["🌐 India"])

def _format_run_timestamp(ts):
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(
        ZoneInfo("Australia/Sydney")
    )
    date_str = dt.strftime("%A, %d %B %Y")
    time_str = dt.strftime("%I:%M %p").lstrip("0")
    return f"{date_str} at {time_str}"


with tab_pipeline:
    st.header("⚙️ Pipeline Control")

    all_noise = get_noise_log_since(hours=876000)
    if not all_noise:
        st.caption("No pipeline runs yet.")
    else:
        last_logged_at = max(entry["logged_at"] for entry in all_noise)
        st.caption(f"Last run: {_format_run_timestamp(last_logged_at)}")

    if st.button("🚀 Run Pipeline"):
        with st.spinner("Fetching and filtering news sources..."):
            run_results = run_pipeline()
        st.session_state["last_run_results"] = run_results
        st.success("Pipeline complete.")
        st.rerun()

    last_run_results = st.session_state.get("last_run_results")
    if last_run_results:
        results = last_run_results["results"]

        col_fetched, col_survived, col_processed = st.columns(3)
        col_fetched.metric("Fetched", last_run_results["fetched"])
        col_survived.metric("Survived Filter", last_run_results["survived_filter"])
        col_processed.metric("Total Processed", len(results))

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

with tab_archive:
    st.header("🗄️ Archive")

    all_archived = get_archived_cards()
    if not all_archived:
        st.info("No archived cards yet.")
    else:
        for domain_label, domain_key in DOMAIN_KEYS.items():
            domain_cards = get_archived_cards(domain=domain_key)
            st.subheader(f"{domain_label} ({len(domain_cards)})")
            for card in domain_cards:
                render_card(
                    {
                        "card": card,
                        "delta_events": get_delta_events_for_card(card["id"]),
                        "transmission": get_transmission_for_card(card["id"]),
                    }
                )
