import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from db.cards import get_active_cards
from db.delta_events import get_delta_events_for_card
from db.transmissions import get_transmission_for_card

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


def _chain_latex_to_text(chain_latex):
    text = chain_latex.replace("\\longrightarrow", "→")
    return re.sub(r"\\text\{([^}]*)\}", r"\1", text)


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
        return
    for card in cards:
        render_card(
            {
                "card": card,
                "delta_events": get_delta_events_for_card(card["id"]),
                "transmission": get_transmission_for_card(card["id"]),
            }
        )


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

with tab_pipeline:
    st.info("Pipeline controls will appear here.")

with tab_archive:
    st.info("Archived cards will appear here.")
