# ⚓ Anchor & Delta

A personal intelligence briefing system that transforms daily news into structured, evolving story cards — delivered through a clean dashboard.

## What It Does

Instead of scrolling through headlines, Anchor & Delta builds **living story cards** that deepen over time. Each card has three layers:

- **The Core Anchor** — the structural reality driving the story. What is fundamentally true that will still be true in six months.
- **Live Status Tracker** — dated delta events, most recent first. Each new development appends to the same card.
- **Conceptual Transmission** — the causal chain explaining why this story matters and where it leads.

## Carousel Engine

Converts finalised Story Cards into publish-ready Instagram
carousels. Eight slide PNGs + caption + pinned comment +
hashtag list per carousel.

**Status:** v1.0 — operational, local use only.

**How it works:**
1. Click 🎠 on any World / Finance / AI & Tech card in the dashboard
2. The engine generates 8 slides via a single Sonnet call (~$0.036)
3. Review slides, caption, and pinned comment in the preview UI
4. Click Approve & Sync to export the bundle to outputs/bundles/
5. Transfer PNGs to phone and post to Instagram manually

**Cost per carousel:** ~$0.037 (1 Sonnet call + 1 Haiku call)

**Architecture:** 7-stage pipeline —
CardLoader → ContextBuilder → CarouselPlanner → CarouselWriter →
LayoutPicker → SlideRenderer → PostAssembler

See [CAROUSEL_BLUEPRINT_v1.md](CAROUSEL_BLUEPRINT_v1.md) for the
architectural spine and [CAROUSEL_DECISIONS.md](CAROUSEL_DECISIONS.md)
for the decisions log.

**Note:** Carousel generation requires local Streamlit only.
Playwright (slide renderer) is not supported on Streamlit Cloud.

## Tech Stack

- **Pipeline**: Python 3.11, Anthropic API (Haiku + Sonnet), Tavily, RSS feeds
- **Research**: Google Gemini 2.5 Flash with real-time web grounding
- **Database**: Supabase (PostgreSQL)
- **UI**: Streamlit
- **Deduplication**: SimHash + TF-IDF

## Features

- 5 domain tabs — World, Finance, AI & Tech, Australia, India
- 6 pipeline buttons — World, Finance, AI Tech, Australia, India, All Domains — run only the domains you need
- Gemini research button — type any topic, get a full intelligence card with current web data
- Source tagging — pipeline cards vs Gemini research cards shown with different badges (🔴 NEW vs 🔍 RESEARCH)
- Auto-archiving — cards with no updates for 7 days move to archive automatically
- Per-card archive and delete buttons
- Body enrichment — fetches full article text, not just RSS teasers
- Cost guard — never exceeds $0.50 per domain run, $0.80 for all domains
- Mobile-friendly layout — no sidebar, all controls inline
- run_id tracking — every pipeline run gets a short ID shown in the stats caption, noise log entries tagged per run

## Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env` and add your API keys:
   - `ANTHROPIC_API_KEY`
   - `TAVILY_API_KEY`
   - `SUPABASE_URL`
   - `SUPABASE_KEY`
   - `GEMINI_API_KEY`
5. Set up Supabase database using the schema in `db/schema.sql`
6. Run: `streamlit run ui/app.py`

## Daily Use

- Click a domain button to run that domain's pipeline (~$0.05-0.16 maintenance, ~$0.10-0.30 discovery)
- Click **🚀 All Domains** for a full briefing run (~$0.40-0.60)
- Use the **🔍 Research** button to investigate any topic with Gemini — creates a research-tagged card
- Cards auto-archive after 7 days of inactivity
- Each run shows a Run #ID in the stats caption for noise log tracing

## Project Structure
Anchor-Delta/

├── config.py              # Settings and constants

├── pipeline/

│   ├── fetcher.py         # RSS + Tavily fetch, body enrichment

│   ├── filter.py          # 4 filter gates

│   ├── engine.py          # Haiku router, Sonnet extractor/composer, Gemini research

│   ├── models.py          # Pydantic models

│   ├── orchestrator.py    # Article processing orchestration

│   └── runner.py          # Pipeline runner with cost guard

├── carousel/              # Instagram Carousel Engine (scaffolded, empty)

│   ├── prompts/           # (scaffolded, empty)

│   ├── templates/         # (scaffolded, empty)

│   ├── fonts/             # (scaffolded, empty)

│   └── assets/            # (scaffolded, empty)

├── outputs/               # Render output and export bundles (scaffolded, empty)

│   ├── renders/           # (scaffolded, empty)

│   └── bundles/           # (scaffolded, empty)

├── db/                    # Supabase database layer

├── ui/app.py              # Streamlit dashboard

├── tests/                 # Diagnostic scripts

│   └── carousel/          # (scaffolded, empty)

└── DESIGN_LESSONS.md      # Lessons learned and gotchas

## Design Lessons

See [DESIGN_LESSONS.md](DESIGN_LESSONS.md) for a comprehensive reference of all issues encountered, root causes, and fixes applied during development.
