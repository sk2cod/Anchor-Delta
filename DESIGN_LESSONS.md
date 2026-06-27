# Anchor & Delta — Design Lessons & Gotchas

A living reference document capturing every issue encountered, root cause, and fix applied during the build of this system. Feed this to Claude at the start of any new project to avoid repeating the same mistakes.

---

## 1. Architecture Decisions

### RSS over pure Tavily
- Tavily free tier exhausts quickly (80 requests/month). RSS feeds are free and unlimited.
- Tavily is now used only for dynamic card-aware queries and user-supplied research queries.
- RSS feeds are the primary source. Tavily is supplementary.

### Body enrichment is essential
- RSS feeds return 150-300 char teasers. The LLM cannot extract named actors, quotes, or consequences from 150 chars.
- After RSS fetch, visit each article URL and fetch full body text using httpx + BeautifulSoup.
- Average content jumps from 164 chars to 1743 chars after enrichment.
- Body enrichment must happen AFTER Gate 3 and Gate 4 (cheap gates first) — no point enriching articles that will be filtered.
- Some sites are paywalled (NYT, FT, WSJ) — enrichment returns thin content. Replace with open-access alternatives.

### Domain-specific pipeline buttons
- Single "Run All" button causes Finance and AI Tech cards to be capped when World/Australia/India fill all slots.
- Solution: one button per domain. Each domain run only fetches and processes that domain's RSS feeds.
- Per-domain cost guard: $0.50. All Domains cost guard: $0.60.

### Gemini for research vs Anthropic
- Gemini 2.5 Flash has real-time web grounding built in — no Tavily needed for research queries.
- Use Gemini for the Research button (user-specified topics).
- Use Anthropic (Haiku + Sonnet) for the pipeline (RSS-based daily briefing).
- Two separate API keys, two separate billing accounts, zero cross-contamination.

---

## 2. RSS Feed Lessons

### Feeds that work
- CNBC Finance (`/100727362/`) and CNBC Economy (`/10000664/`) — strong macro signal, 30 entries each
- Guardian AU, ABC News AU, SMH — strong Australia signal
- The Hindu Business, Indian Express Business — strong India signal
- Ars Technica Tech Lab — strong AI/tech signal
- VentureBeat — excellent AI signal, low volume
- TechCrunch — strong AI/tech signal
- Al Jazeera — good geopolitics, scrapeable
- DW News, France24, Guardian World — good open-access geopolitics

### Feeds that failed
- NYT World/Business — paywalled, body enrichment returns nothing
- FT — paywalled, same issue
- Reuters (feeds.reuters.com) — DNS dead, 0 entries
- Guardian Business (theguardian.com/business/rss) — serves AU general news, not finance
- Wired — lifestyle, shopping, Amazon Prime Day noise
- Yahoo Finance — headline-only RSS (0 chars), consumer savings rates, analyst opinions
- Investing.com — headline-only RSS, routine equity calls
- BBC Business — lifestyle noise, energy bill tips
- Sky News Business — broken HTML in entries

### Why checking headlines is not enough
- Yahoo Finance showed "Micron chip earnings" in headline check — looked like finance signal
- But article bodies were consumer savings comparisons and routine analyst calls
- Router correctly rejected them all as noise
- Always check: (1) headline, (2) article body after enrichment, (3) router decision on sample articles

---

## 3. LLM Prompt Engineering

### Router prompt evolution
- Started simple → too aggressive, rejected Venezuela earthquake, Fed stress tests
- Added Gemini-inspired "conceptual match" approach — evaluate structural thesis not keywords
- Key addition: "err on the side of inclusion" safety valve
- Key addition: domain-specific examples (what always passes for Finance, India, AI Tech)
- Key addition: card clustering by structural thesis — "South Korea drones + Ukraine drones = ONE card"
- Domain priority order: AUSTRALIA > INDIA > FINANCE > AI_TECH > WORLD

### Composer voice rewrite
- Original: textbook-style, passive voice, analyst quotes doing the explaining
- Target: "sharp well-informed friend explaining something fascinating at dinner"
- Key rules:
  - Name the move — explain what it IS not just what happened
  - Zero specialist knowledge — explain every concept before using it
  - Short sentences with punch, then explain
  - YOU explain, not the analysts — quotes are supporting evidence only
  - One quote per speaker maximum — the sharpest line only
  - 2-3 sentences maximum for what_happened
  - Active voice always

### Card clustering
- Wrong: "when in doubt — cluster" → causes unrelated stories to merge
- Correct: "cluster when articles share the same STRUCTURAL THESIS"
- Test: does this article's core argument fit within the existing card's anchor thesis?
- Example: South Korea drones + Ukraine drones = same thesis (drone warfare reshaping military doctrine) = ONE card
- Example: Ukraine drones + India drone manufacturing policy = different thesis = TWO cards

---

## 4. Pipeline Architecture Gotchas

### Diagnostic runs pollute processed_articles
- Running run_filter_pipeline() in a diagnostic writes URLs to processed_articles
- Next real pipeline run: Gate 1 blocks all those URLs as "already seen"
- Fix: always build read-only diagnostics that simulate gates without DB writes
- Or: delete processed_articles entries after diagnostic runs

### Gate order matters for cost
- Wrong order: enrich bodies → Gate 3 → Gate 4 → Gate 1 → Gate 2
- Correct order: Gate 3 → Gate 4 → enrich bodies → Gate 1 → Gate 2
- Run cheap gates first (keyword blocklist, freshness) before expensive body enrichment

### Content gate blocks headline-only feeds
- Old: filter articles with content < 150 chars in fetch_rss_articles()
- Problem: Yahoo Finance, Investing.com send 0-char summaries — all blocked before enrichment
- Fix: remove content length gate from fetch_rss_articles() — let body enrichment fill content downstream

### Card cap blocking new domain cards
- With MAX_ACTIVE_CARDS=10, World and Australia cards fill all slots
- Finance and AI Tech articles get capped before creating cards
- Fix 1: per-domain pipeline buttons — each domain has its own run
- Fix 2: auto-archiving after 7 days — stale cards free up slots
- Fix 3: MAX_ACTIVE_CARDS=20 gives more headroom

### Cost guard stopping pipeline too early
- $0.60 guard stops full pipeline before Finance/AI Tech articles are processed
- Articles processed in queue order — Finance/AI Tech often at the back
- Fix: domain-specific pipeline buttons so Finance runs independently

---

## 5. Pydantic/LLM Output Issues

### event_headline returned as list
- LLM returns ["Headline 1", "Headline 2"] instead of "Headline 1 | Headline 2"
- Fix 1: _preprocess_input() to convert list to string — not sufficient alone
- Fix 2: force dict() conversion on tool_use_block.input before preprocessing
- Fix 3 (root fix): @field_validator on all scalar string fields in models.py
- lesson: always add field_validator for any field that could be mistyped by LLM

### chain_latex null constraint
- Composer sometimes returns None for chain_latex when LLM skips transmission
- Database has NOT NULL constraint on chain_latex column
- Fix: guard at application layer — check if chain_latex is not None before calling upsert_transmission()
- Do not change DB constraint — guard at application layer instead

### LLM date anchoring
- LLM uses dates from article body (historical context dates) instead of article's published_date
- Fix: pass published_date explicitly in extract_article() user message
- Add EVENT DATE RULE to both composer prompts

---

## 6. Database

### Supabase anon key limitations
- Supabase anon key cannot run DDL (ALTER TABLE, CREATE TABLE)
- Use Supabase SQL editor for schema changes
- Only PostgREST operations (SELECT, INSERT, UPDATE, DELETE) work via anon key

### hard_delete_all_cards wipes everything
- Deletes cards, delta_events, transmissions, processed_articles, noise_log
- Use for clean test resets only
- Never use in production — use per-card delete or archive instead

### Auto-archiving
- Cards with no delta events for 7 days auto-archive at start of each pipeline run
- STALE_CARD_DAYS = 7 in config.py
- Archived cards free up slots for new stories
- Without auto-archiving: card cap fills up, new Finance/AI Tech cards never created

---

## 7. UI/Streamlit Lessons

### layout="wide" breaks sidebar
- Streamlit sidebar collapse toggle becomes invisible against dark background
- CSS overrides with !important cause slow sidebar loading
- Fix: remove all custom sidebar CSS, let Streamlit handle natively
- Browser localStorage stores sidebar collapsed state — clear to reset

### Dividers create too much whitespace
- st.divider() renders thick line with large padding — makes cards feel long
- Replace with: st.markdown("<hr style='margin:8px 0;border:none;border-top:0.5px solid rgba(255,255,255,0.1);'>", unsafe_allow_html=True)

### Card visual hierarchy
- Problem: 6+ different font sizes creating visual confusion
- Solution: 3 levels only
  - Level 1: tldr hook — 17px, font-weight 500, red left border — first thing reader sees
  - Level 2: body text — 14px, line-height 1.7, consistent throughout
  - Level 3: section labels — 11px, uppercase, muted — navigation only

### Reading order matters
- Wrong: Anchor (hardest) → Delta events → Transmission (hardest)
- Correct: tldr hook → Latest delta event → Core Anchor → Previous Chapters (collapsed) → Transmission
- Reader hits easiest content first, goes deeper by choice

---

## 8. Cost Management

### Always diagnose before running pipeline
- Diagnostic costs $0 — no LLM calls
- Shows exactly what will reach the LLM before spending money
- Run: fetch RSS → enrich bodies → run filter pipeline → show survivors by domain
- WARNING: diagnostic pollutes processed_articles — delete entries after or build read-only version

### Per-domain cost guards
- DOMAIN_COST_GUARD_USD = 0.50 (per domain button click)
- ALL_DOMAINS_COST_GUARD_USD = 0.60 (All Domains button)
- Sonnet calls per article = 2 (extraction + composition) — divide displayed count by 2 for articles processed

### Body enrichment cost
- Enriching all 115 articles wastes time and money on articles that get filtered
- Run Gate 3 and Gate 4 first (free), then enrich only survivors

---

## 9. External Services

### Tavily
- Free tier: ~80 requests/month — exhausts quickly with multiple test runs
- When exhausted: pipeline fails with ForbiddenError — wrap in try/except, fall back to []
- RSS is primary source — Tavily adds marginal value for dynamic card queries
- Consider: remove dynamic queries entirely, rely on RSS only

### Paywalled sources (NYT, FT, WSJ)
- RSS teasers are fine for headlines but body enrichment returns paywall/login pages
- Thin content = LLM cannot extract quotes, actors, consequences
- Replace with open-access equivalents

### Gemini API
- Free tier: 500 requests/day for Gemini 2.5 Flash — generous for research queries
- Use google-genai package (not deprecated google-generativeai)
- Temperature 0.7 — slightly more focused than default 1.0
- Always use JSON output mode for reliable structured parsing

---

## 10. What to Build First Next Time

1. **Read-only diagnostic script** — before writing any pipeline code
2. **SimHash + TF-IDF deduplication** — before building LLM calls
3. **Body enrichment** — before writing LLM prompts
4. **Domain-specific pipeline from day one** — not as an afterthought
5. **Per-domain card caps** — prevents one domain monopolising all slots
6. **Auto-archiving** — before going live, not after cards fill up
7. **Feed quality check** — headline + body + router decision on samples before adding any feed
8. **Cost tracking per domain** — know what each domain costs before running at scale

---

## 11. Git History Reference

Key commits in order:
- `b8d6fb1` — feat: full article body fetcher, replace NYT with Guardian/DW/France24
- `dbdc910` — fix: pydantic validators, extract prompt, gate4 year check, router prompt rewrite
- `6f9d2f4` — fix: expand finance router, bootstrap settings
- `9276d92` — revert: bootstrap settings back to daily mode
- `866819d` — fix: raise tfidf threshold to 0.25
- `90be85d` — fix: reading order, tldr display, date anchoring
- `e712e43` — fix: live progress display, run time format
- `f99291b` — fix: world tab merge, single quote per speaker, 5 tab restructure
- `ed4a0be` — fix: card visual hierarchy redesign
- `dc638e1` — feat: Gemini research button with real-time web grounding
- `e6b9b24` — feat: domain-specific pipeline buttons
- `b85e56b` — feat: automatic card archiving after 7 days
- `d3e4af2` — feat: manual archive button per card
- `4ecf70c` — fix: null chain_latex guard
