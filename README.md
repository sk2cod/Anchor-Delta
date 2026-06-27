# ⚓ Anchor & Delta

A personal intelligence briefing system that transforms daily news into structured, evolving story cards — delivered through a clean dashboard.

## What It Does

Instead of scrolling through headlines, Anchor & Delta builds **living story cards** that deepen over time. Each card has three layers:

- **The Core Anchor** — the structural reality driving the story. What is fundamentally true that will still be true in six months.
- **Live Status Tracker** — dated delta events, most recent first. Each new development appends to the same card.
- **Conceptual Transmission** — the causal chain explaining why this story matters and where it leads.

## Tech Stack

- **Pipeline**: Python 3.11, Anthropic API (Haiku + Sonnet), Tavily, RSS feeds
- **Research**: Google Gemini 2.5 Flash with real-time web grounding
- **Database**: Supabase (PostgreSQL)
- **UI**: Streamlit
- **Deduplication**: SimHash + TF-IDF

## Features

- 5 domain tabs — World, Finance, AI & Tech, Australia, India
- Domain-specific pipeline buttons — run only the domains you need
- Gemini research button — type any topic, get a full intelligence card with current web data
- Auto-archiving — cards with no updates for 7 days move to archive automatically
- Per-card delete and manual archive
- Body enrichment — fetches full article text, not just RSS teasers
- Cost guard — never exceeds $0.50 per domain run, $0.60 for all domains

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

- Click a domain button to run that domain's pipeline (~$0.10-0.20 per domain)
- Click **🚀 All Domains** for a full briefing run (~$0.50-0.60)
- Use the **🔍 Research** button to investigate any topic with Gemini
- Cards auto-archive after 7 days of inactivity

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

├── db/                    # Supabase database layer

├── ui/app.py              # Streamlit dashboard

├── tests/                 # Diagnostic scripts

└── DESIGN_LESSONS.md      # Lessons learned and gotchas

## Design Lessons

See [DESIGN_LESSONS.md](DESIGN_LESSONS.md) for a comprehensive reference of all issues encountered, root causes, and fixes applied during development.
