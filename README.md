# ⚓ Anchor & Delta

A personal intelligence briefing system that transforms daily news into structured, evolving story cards — delivered through a clean dashboard.

## What It Does

Instead of scrolling through headlines, Anchor & Delta builds **living story cards** that deepen over time. Each card has three layers:

- **The Core Anchor** — the structural reality driving the story. What is fundamentally true that will still be true in six months.
- **Live Status Tracker** — dated delta events, most recent first. Each new development appends to the same card.
- **Conceptual Transmission** — the causal chain explaining why this story matters and where it leads.

## Carousel Engine

Converts finalised Story Cards into publish-ready Instagram
carousels. 5–10 slide PNGs (story-length-driven, not a fixed count)
+ caption + pinned comment + hashtag list per carousel, with an
AI-generated cover image on slide 1.

**Status:** Operational, local use only — kept current through
Decision #73 (see the decisions log).

**How it works:**
1. Click 🎠 on any World / Finance / AI & Tech card in the dashboard (optionally supply cover-image keywords first)
2. The writer decides the carousel's own shape and generates as many slides as the story needs via a single Sonnet call, then generates the cover image via one gpt-image-1 call
3. Review slides, caption, and pinned comment in the preview UI — regenerate any single slide, or just the cover image, independently
4. Click Approve & Sync to export the bundle to outputs/bundles/
5. Transfer PNGs to phone and post to Instagram manually

**Cost per carousel:** ~$0.07–0.08 — fully measured, not estimated (2 Haiku calls ~$0.007 + 1 Sonnet call ~$0.03 + 1 gpt-image-2/medium call $0.041, all computed from real usage/pricing, folded into `CarouselSpec.generation_metadata.cost_usd`). Was ~$0.28-0.29 at gpt-image-1/high (Decision #74) before switching to gpt-image-2/medium (Decision #76) — 84% cheaper on the image, based on real side-by-side testing.

**Architecture:** 7-stage pipeline —
CardLoader → ContextBuilder → CarouselWriter (decides shape) →
CarouselPlanner (validates shape) → LayoutPicker → SlideRenderer →
PostAssembler

See [CAROUSEL_BLUEPRINT_v1.md](CAROUSEL_BLUEPRINT_v1.md) for the
architectural spine and [CAROUSEL_DECISIONS.md](CAROUSEL_DECISIONS.md)
for the decisions log. See [ARCHITECTURE_SNAPSHOT.md](ARCHITECTURE_SNAPSHOT.md)
for a whole-system, point-in-time reference (both engines + hosting),
frozen as the pre-migration baseline for the Streamlit→Railway move
tracked in [INFRA_DECISIONS.md](INFRA_DECISIONS.md).

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
   - Optional, for Google Drive upload on Approve & Sync (Stage 3 —
     see `INFRA_DECISIONS.md` #02): `GOOGLE_OAUTH_CLIENT_ID`,
     `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`
     (obtained via `scripts/get_drive_refresh_token.py`), and
     `GOOGLE_DRIVE_FOLDER_ID` (auto-created and logged on first run if left
     unset). Leave all four unset to keep the existing local
     `outputs/bundles/` export exactly as-is.
   - Optional, for a password gate on a public Railway deployment (Stage
     4): `APP_PASSWORD`. Leave unset for local dev — the app runs with no
     gate at all, same as before.
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

├── carousel/              # Instagram Carousel Engine — built and operational

│   ├── models.py          # Pydantic schemas (StoryContext, CarouselSpec, Slide, ...)

│   ├── loader.py, context_builder.py, writer.py, planner.py,

│   │   layout_picker.py, renderer.py, assembler.py, image_generator.py

│   ├── prompts/           # versioned writer/regenerate prompt files (writer_v2_0.md current)

│   ├── templates/         # HTML/CSS slide templates (statement, cover, quote, cta, + dormant ones)

│   ├── fonts/              # self-hosted Playfair Display + Inter .woff2 files

│   └── assets/             # brand mark, wordmark files

├── outputs/               # Render output and export bundles

│   ├── renders/           # render cache PNGs (gitignored)

│   ├── cover_images/       # AI-generated cover images (gitignored)

│   └── bundles/           # per-carousel export bundles (gitignored)

├── db/                    # Supabase database layer

├── ui/                    # Streamlit dashboard

│   ├── app.py              # main dashboard + carousel generation entry point

│   └── carousel_view.py    # carousel preview/edit/regenerate/approve UI

├── tests/                 # Diagnostic scripts

│   └── carousel/          # carousel-engine test/reference scripts

└── DESIGN_LESSONS.md      # Lessons learned and gotchas

## Design Lessons

See [DESIGN_LESSONS.md](DESIGN_LESSONS.md) for a comprehensive reference of all issues encountered, root causes, and fixes applied during development.
