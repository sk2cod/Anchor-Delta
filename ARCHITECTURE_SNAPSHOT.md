# Anchor & Delta — Architecture Snapshot

**Snapshot date:** 2026-07-16
**Status:** Pre-migration baseline. This document is a static, point-in-time
reference of the whole system — Intelligence Engine + Carousel Engine +
hosting — as it exists today, frozen as the diff baseline for the upcoming
Streamlit → Railway hosting migration (see `INFRA_DECISIONS.md` Decision #01).

This is **not a living doc**. It will not be updated as the code changes
after this date — that is the point of a frozen baseline. For current,
maintained descriptions of each engine, see:

- **Intelligence Engine** — narrated across `README.md` and
  `DESIGN_LESSONS.md`; this document adds the frozen structural spec that
  neither of those provides.
- **Carousel Engine** — `CAROUSEL_BLUEPRINT_v1.md` (architectural spine,
  19 sections) and `CAROUSEL_DECISIONS.md` (decisions log). This document
  summarizes and links rather than re-describing them.
- **Hosting/infra decisions going forward** — `INFRA_DECISIONS.md`.

---

## 1. System at a glance

Anchor & Delta is two engines sharing one repository, one Supabase project,
and one Streamlit UI process:

```
                     ┌─────────────────────────┐
   RSS / Tavily /    │   Intelligence Engine    │
   Gemini research ─▶│  (pipeline/, this doc §2)│
                     └───────────┬─────────────┘
                                 │ writes/reads
                                 ▼
                     ┌─────────────────────────┐
                     │   Supabase (Postgres)    │
                     │   cards, delta_events,   │
                     │   transmissions, ...     │
                     └───────────┬─────────────┘
                                 │ reads only (never writes back)
                                 ▼
                     ┌─────────────────────────┐
                     │    Carousel Engine       │
                     │  (carousel/, see         │
                     │  CAROUSEL_BLUEPRINT_v1)  │
                     └───────────┬─────────────┘
                                 │
                                 ▼
                     ┌─────────────────────────┐
                     │   ui/ (Streamlit)        │
                     │  app.py + carousel_view  │
                     └─────────────────────────┘
```

Boundary discipline (Decision #41 in `CAROUSEL_DECISIONS.md`): `carousel/`
reads from `pipeline/` and `db/`, never modifies them; `pipeline/` never
imports from `carousel/`. Verified in code — `pipeline/orchestrator.py` and
`pipeline/engine.py` have no imports from `carousel/`.

---

## 2. Intelligence Engine — frozen architecture spec

Unlike the Carousel Engine, the Intelligence Engine has no standalone
blueprint document — it's narrated piecemeal across `README.md` and
`DESIGN_LESSONS.md`. This section is the structural spec those two don't
provide, verified directly against `pipeline/`, `db/`, and `config.py`.

### 2.1 Pipeline stages

`pipeline/runner.py:run_pipeline()` is the entry point, called from
`ui/app.py`'s domain buttons. Sequence per run:

1. **Auto-archive** — `db.cards.archive_stale_cards(days=STALE_CARD_DAYS)`
   (7 days) runs first, before any fetching.
2. **Fetch** (`pipeline/fetcher.py`, class `TavilyFetcher`) — three sources
   combined: `fetch_rss_articles()` (primary), `fetch_user_queries()`
   (Research-box text input), `fetch_dynamic_queries()` (Tavily queries
   built from existing active cards; wrapped in try/except — Tavily's free
   tier exhausts at ~80 requests/month, DESIGN_LESSONS.md §9).
3. **In-batch URL dedup** — a local `seen_urls` set collapses exact-duplicate
   URLs across the three fetch sources before filtering.
4. **Filter pipeline** (`pipeline/filter.py:run_filter_pipeline()`) — four
   gates, deliberately ordered so cheap checks run before expensive ones:
   - **Gate 3** (keyword blocklist, `pipeline/keywords.json`) and **Gate 4**
     (freshness — 48h default via `FRESHNESS_HOURS`, 96h for `ai_tech` via
     `_AI_TECH_FRESHNESS_HOURS`) run first — no DB lookups, no network calls.
   - Body enrichment (`fetcher.enrich_articles_with_body()`) runs only on
     gate-3/4 survivors.
   - **Gate 1** (URL uniqueness — checks an in-memory batch set *and*
     `db.processed_articles.is_url_seen()`, not DB-only — see
     `[[anchor_delta_filter_gates]]` memory) and **Gate 2** (near-duplicate
     detection — SimHash on title first, TF-IDF on title+content as a
     second pass only if SimHash finds nothing; both compare against
     in-batch survivors, not the DB) run last, on enriched content.
5. **Routing + composition** (`pipeline/orchestrator.py:process_article()`
   per surviving article):
   - A cheap **keyword pre-match** (`_find_keyword_match()`) against active
     card titles skips the Haiku call entirely when a strong match is found.
   - Otherwise `pipeline/engine.py:route_article()` (Haiku) classifies as
     `noise` / `existing_card` / `new_frame`.
   - Every routing decision (not just noise) is written to `routing_log` via
     `log_routing_decision()`, which swallows its own failures so a missing
     table can never turn a real result into a false error.
   - `existing_card` → `extract_article()` (Sonnet) +
     `compose_delta_update()` (Haiku) → `append_delta_event()`.
   - `new_frame` → blocked if `get_active_card_count() >= MAX_ACTIVE_CARDS`
     (20); otherwise `extract_article()` + `compose_new_card()` (both
     Sonnet) → `create_card()` + `append_delta_event()`.
   - A per-run cost guard (`DOMAIN_COST_GUARD_USD` $0.50 single-domain,
     `ALL_DOMAINS_COST_GUARD_USD` $0.80 for the grouped/all-domains button)
     halts processing mid-run, logged as `cost_guard` noise.

### 2.2 Domain model

Five domains (`config.VALID_DOMAINS`): `world`, `finance`, `ai_tech`,
`australia`, `india`. Only three (`config.CAROUSEL_DOMAINS`) have a carousel
path. `ui/app.py` wires one pipeline button per domain plus a grouped
"🚀 Carousel Domains" button that runs world+finance+ai_tech together under
one cost budget, one run_id, one fetch/filter pass — not three separate
runs.

### 2.3 Persistence — Supabase schema

`db/schema.sql` defines the original five tables (verified — the file on
disk today has exactly these, no more):

| Table | Key columns | Notes |
|---|---|---|
| `cards` | `domain`, `umbrella_title`, `anchor_text`, `is_archived`, `last_delta_at` | The Anchor |
| `delta_events` | `card_id` FK, `event_date`, `headline`, `what_happened`, `dialogue` jsonb, `tldr` | Append-only, never updated/deleted |
| `transmissions` | `card_id` FK unique, `chain_latex`, `nodes_markdown` | One row per card, upsert-only |
| `processed_articles` | `url_hash`, `headline_hash` | Gate 1 dedup log |
| `noise_log` | `gate_failed`, `reason`, `rerouted_to` | Surfaced in UI's "Noise Log" expander |

Two further tables exist in the live Supabase project but are **not** in
`db/schema.sql` — they were created directly via the Supabase SQL editor
because the anon key cannot run DDL (`DESIGN_LESSONS.md` §6):
- `routing_log` (`db/routing_log.py`) — full audit trail of every routing
  decision, not just rejections.
- `carousels` (`db/carousel_queries.py`) — stores `CarouselSpec` as JSONB;
  its `CREATE TABLE` SQL lives as a string constant
  (`CAROUSELS_TABLE_SQL`) in that same file, not in `schema.sql`.

See `[[anchor_delta_supabase_project]]` memory for the project ref and
`[[anchor_delta_filter_gates]]` for the gate 1/2 dedup detail above.

### 2.4 Pydantic contracts (`pipeline/models.py`)

Four LLM-facing DTOs, all with `field_validator`s that coerce list-typed LLM
output back to scalar strings (`_coerce_to_str`) and dedupe repeated-speaker
dialogue turns (`_dedupe_dialogue`) — defensive validation against known
LLM output quirks, not speculative:

- `RouteResult` — `classification`, `card_id`, `confidence`, `reason`.
- `ExtractionResult` — `named_actors`, `dialogue`, `tactical_moves`,
  `event_date`, `named_consequences`, `event_headline`, `what_happened`.
- `NewCardResult` — full new-card payload including `domain`,
  `umbrella_title`, `anchor_text`, `chain_latex`, `nodes_markdown`.
- `DeltaUpdateResult` — same shape minus card-identity fields, plus
  `transmission_needs_update: bool`.

### 2.5 UI (`ui/app.py`)

Single-file Streamlit dashboard: custom CSS block (narrow 860px column,
hidden Streamlit chrome), a Research text input (Gemini-backed, writes
research-tagged cards), six pipeline-trigger buttons with a confirm/cancel
step, a live run-stats caption (fetched/survived-filter/processed counts,
Haiku/Sonnet call counts, estimated cost), five domain tabs, an Archive
expander, and a "Danger Zone" hard-delete expander. Card rendering
(`render_card()`) reads three-layer story cards (tldr hook → latest delta →
core anchor → collapsed previous chapters → transmission) and, for the three
carousel-eligible domains, exposes the 🎠 button that invokes the full
carousel pipeline inline and hands off to `ui/carousel_view.py` for the
preview/approve UI.

---

## 3. Carousel Engine — summary (see Blueprint for detail)

Full spec: `CAROUSEL_BLUEPRINT_v1.md` (19 sections, frozen "kept current
through Decision #73" per its own header). Full reasoning history:
`CAROUSEL_DECISIONS.md` (60+ decisions as of this snapshot). This section
intentionally does not re-describe them — only the shape, verified against
`carousel/models.py` and `ui/`:

- **7-stage pipeline:** CardLoader → ContextBuilder → CarouselWriter
  (decides the carousel's own shape, narrative-driven since Decision #67) →
  CarouselPlanner (validates shape post-hoc) → LayoutPicker → SlideRenderer
  (Playwright) → PostAssembler.
- **One creative LLM call per generation** (Sonnet, writer) plus one Haiku
  extraction call upstream and one image-generation call
  (gpt-image-2/medium as of Decision #76) for the cover.
- **Pydantic spine** in `carousel/models.py`: `StoryCard` is redefined here
  (not imported from `pipeline/models.py`, which has no persisted-card
  contract — Decision #47) through `StoryContext` → `CarouselSpec` (the
  load-bearing model, `schema_version`-tagged) → `EnrichedSpec` →
  `Carousel` (the persisted record).
- **Templates:** 8 archetypes (`TemplateID` enum) — statement, number,
  quote, timeline, concept, hook (superseded by cover for slide 1), cover,
  cta, portrait (inert v1.5 seam). Dark theme only in v1.0. Self-hosted
  Playfair Display + Inter fonts.
- **Cost:** ~$0.07–0.08/carousel, measured from real
  `generation_metadata.cost_usd`, not estimated (README.md, Decision #76).
- **Output:** exported bundle to `outputs/bundles/`, optionally synced to a
  configurable local folder (`CAROUSEL_SYNC_DIR`, Decision #52) for manual
  transfer to phone and posting — no Instagram Graph API integration exists
  today (`carousel/assembler.py`, Blueprint §7).

---

## 4. Hosting & Infrastructure — today's setup (pre-migration)

This is the section this snapshot exists to capture — the other docs don't
describe deployment topology.

### 4.1 Current deployment model

**Local Streamlit only. There is no hosted deployment today.** Verified: no
`Dockerfile`, `railway.json`, `Procfile`, or any CI/deployment config exists
in the repository as of this snapshot — only `requirements.txt`.

- Run command: `streamlit run ui/app.py` (README.md Setup step 6), executed
  on the user's own machine.
- Secrets: `config.py` loads from a local `.env` file via `python-dotenv`,
  falling back to `st.secrets` if present (`ANTHROPIC_API_KEY`,
  `TAVILY_API_KEY`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `GEMINI_API_KEY`).
  `config.py` raises `RuntimeError` at import time if any of the first four
  are missing — there is no degraded-mode startup.
- Database: Supabase (hosted Postgres, external to this deployment
  question) — reached via `supabase-py`'s `create_client()` in
  `db/client.py`. Supabase itself is unaffected by the hosting migration;
  only the Streamlit process's location changes.
- File-based side effects that assume a local filesystem: rendered slide
  PNGs cached under `outputs/renders/`, cover images under
  `outputs/cover_images/`, export bundles under `outputs/bundles/` (all
  gitignored per README's Project Structure section), and the optional
  `CAROUSEL_SYNC_DIR` sync target (`config.py`, default a local Google
  Drive path — `G:\My Drive\Anchor & Delta\Outbox` — which is itself a
  Windows-local-machine assumption).

### 4.2 The hard constraint: Playwright/Chromium

The Carousel Engine's `SlideRenderer` stage renders HTML/CSS slide
templates to PNG via Playwright headless Chromium
(`CAROUSEL_BLUEPRINT_v1.md` §5, Decision #11). This requires system-level
Chromium binary dependencies.

**This is the one constraint driving the entire hosting decision.**
Confirmed in two independent places:
- `DESIGN_LESSONS.md` §14: *"Playwright requires system-level Chromium
  dependencies unavailable on Streamlit Cloud's containerised environment.
  Design carousel generation as a local tool from day one. Do not attempt
  to make it cloud-compatible until v2 with a proper rendering API."*
- `CAROUSEL_DECISIONS.md` Decision #50 ("Playwright local-only for v1.0"):
  *"Playwright will not be supported on Streamlit Cloud in v1.0... Cloud
  rendering is v2 work."* Status: Active, deferred to v2.
- `README.md`: *"Carousel generation requires local Streamlit only.
  Playwright (slide renderer) is not supported on Streamlit Cloud."*

The constraint is specifically **Streamlit Cloud's managed container**
(no ability to install system packages), not Streamlit-the-framework and
not Playwright itself — Playwright runs fine in any environment where its
Chromium system dependencies can be installed. This distinction is the
basis for the migration decision logged in `INFRA_DECISIONS.md` Decision
#01: moving to a host that allows a custom Dockerfile (Railway) removes the
constraint without touching the renderer, the UI framework, or any
application code.

### 4.3 What changes vs. what doesn't (forward-looking, not yet done)

Tracked in detail in `INFRA_DECISIONS.md` going forward. At the time of
this snapshot, none of the following has happened yet — recorded here only
so future readers can diff against this baseline:
- No Dockerfile exists.
- No Railway project is provisioned.
- `CAROUSEL_SYNC_DIR`'s Windows-local-path default and the phone-transfer-
  by-hand step (README "Daily Use") are both local-machine assumptions that
  a hosted deployment will need to address, but are out of scope for this
  document — this is a snapshot, not a plan.

---

## 5. What this document is not

- Not a substitute for `CAROUSEL_BLUEPRINT_v1.md` — that remains the
  authoritative Carousel Engine spec.
- Not a substitute for `CAROUSEL_DECISIONS.md` or the future
  `INFRA_DECISIONS.md` — those hold the *why*; this holds *what was true
  on 2026-07-16*.
- Not maintained after this date. If the system changes, this document
  becomes historically inaccurate by design — that's what makes it useful
  as a diff baseline for the Railway migration.
