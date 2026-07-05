# Anchor & Delta — Carousel Engine Decisions Log

Living record of architectural decisions for the Instagram Carousel Engine.

**Format:** Decision / Date / Why / Alternatives considered / Status

**Status values:** `Active` · `Superseded by #N` · `Open` · `Deferred to v1.5` · `Deferred to v2`

**Rules of the log:**
- Every architectural decision is recorded here before code is written
- When a decision is superseded, it is not deleted — it is marked superseded and linked to the new decision
- The log is updated as we go, not retroactively

---

## #01 — Carousel engine is a separate system, triggered per card

**Date:** 2026-06-30
**Decision:** The Instagram Carousel Engine consumes finalised Story Cards but is architecturally independent from the Intelligence Engine. Triggered explicitly per card via a UI button, not run automatically on every new card.
**Why:** The Intelligence Engine is stable and should not be perturbed. Not every card deserves a carousel; explicit triggering keeps cost predictable and lets the user curate.
**Alternatives considered:**
- Append carousel generation as an 8th stage of the existing pipeline. Rejected: pollutes a stable pipeline and forces carousels on every card.
- Auto-generate carousels for "interesting" cards. Rejected: requires defining "interesting" with no real signal yet.
**Status:** Active

---

## #02 — Single Sonnet call per generation (Model B for regenerates)

**Date:** 2026-06-30
**Decision:** One Sonnet call produces all slide text, caption, pinned comment, and hashtag themes per generation. Targeted slide regenerate is a separate call (Model B). Free-text full regenerate is a third mode (Model A). Inline edit is no LLM call (Model C).
**Why:** Voice consistency across slides requires single-pass writing. Splitting into per-slide calls produces drift, wastes tokens, increases latency. Targeted regenerate is the primary fix path for solo daily use.
**Alternatives considered:**
- Per-slide Sonnet calls. Rejected: drift between slides, higher cost.
- Planner + writer + captioner as three calls. Rejected: needless complexity.
- Whole-script regenerate only (no targeted). Rejected: forces user to regenerate fine slides to fix one broken one.
**Status:** Active

---

## #03 — Python owns determinism, LLM owns creativity

**Date:** 2026-06-30
**Decision:** Planning, layout, hashtags, rendering, caption assembly, persistence — Python. Slide text, caption draft, hashtag themes — LLM. No third category.
**Why:** Determinism reduces variance the user must review. Every LLM call is a surprise to babysit; fewer calls means faster approval and more carousels shipped.
**Alternatives considered:** Use LLM for layout selection, hashtag generation. Rejected: needless cost and non-determinism for tasks with deterministic correct answers.
**Status:** Active

---

## #04 — No LangGraph, no agent frameworks

**Date:** 2026-06-30
**Decision:** Linear pipeline orchestrated by plain Python. No LangGraph, no LangChain, no agent abstractions.
**Why:** Linear 7-stage transformation with one creative LLM call. No branching, no loops, no workflow orchestration genuinely benefits from a graph framework. Function composition is correct.
**Alternatives considered:** LangGraph for orchestration. Rejected: adds dependencies and indirection for zero benefit.
**Status:** Active

---

## #05 — Pydantic contracts at every stage boundary

**Date:** 2026-06-30
**Decision:** Every pipeline stage takes a typed Pydantic input and returns a typed Pydantic output. No dicts passed between stages. Pydantic validation enforces the contract.
**Why:** Schema is the spine. Components evolve; contracts must stay typed to prevent ripple failures.
**Alternatives considered:** Loose dicts for speed. Rejected: previous project experience showed this leads to re-engineering.
**Status:** Active

---

## #06 — 7-stage pipeline locked

**Date:** 2026-06-30
**Decision:** CardLoader → ContextBuilder → CarouselPlanner → CarouselWriter → LayoutPicker → SlideRenderer → PostAssembler.
**Why:** Each stage has one responsibility. Adding features means adding to stages, not restructuring them. Future Publisher component (v2) is a swap-in for the PostAssembler's export action, not a new stage.
**Alternatives considered:** Combine ContextBuilder into Writer (skip the trim step). Rejected: loses the highest-leverage Python optimisation point.
**Status:** Active

---

## #07 — Haiku for entity / number / quote extraction in ContextBuilder

**Date:** 2026-06-30
**Decision:** Use a single Haiku call in ContextBuilder to extract named entities, dominant numbers, and sourced quotes from the Story Card. Add to StoryContext.
**Why:** Regex catches approximately 70% of entities reliably. Haiku catches approximately 95%. Cost difference is approximately $0.005 per generation. Quality gain (better writer input, fewer regenerates) justifies the cost. Aligns with project philosophy of "build the right thing from day one, not the cheap thing first."
**Alternatives considered:**
- Regex / heuristic extraction. Rejected: misses entities mentioned once, numbers written as words, qualified attribution phrases. Would force re-engineering at first quality disappointment.
- Sonnet for extraction. Rejected: Haiku is sufficient and 10× cheaper.
**Status:** Active

---

## #08 — Prompt versioning from day one

**Date:** 2026-06-30
**Decision:** Every CarouselSpec records `prompt_version` (e.g. "writer-v3.2"). When the writer prompt is changed, the version bumps. Old carousels remain attached to the prompt version that generated them.
**Why:** Allows A/B comparison of prompt changes on a fixed card set. Allows clean rollback if a prompt change degrades output. Builds a quality regression suite naturally. Cheap to add upfront, painful to retrofit.
**Alternatives considered:** No versioning. Rejected: previous project pain.
**Status:** Active

---

## #09 — Render at 2x resolution, downscale for final

**Date:** 2026-06-30
**Decision:** Render PNGs at 2160×2700, downscale to 1080×1350. Pillow handles downscale.
**Why:** Sharp typography on high-DPI phones. Slight render cost (~250ms vs ~150ms per slide cold), zero LLM cost, large visual quality gain.
**Alternatives considered:** Render at target resolution. Rejected: typography looks soft on retina phones.
**Status:** Active

---

## #10 — Self-hosted fonts, not Google Fonts CDN at render time

**Date:** 2026-06-30
**Decision:** Fonts downloaded into the repo and loaded via @font-face. No external font CDN calls at render time.
**Why:** Deterministic rendering, no flaky network, no surprise visual drift if Google updates a font version.
**Alternatives considered:** Google Fonts CDN. Rejected: introduces external dependency at render time.
**Status:** Active

---

## #11 — HTML/CSS templates rendered via Playwright

**Date:** 2026-06-30
**Decision:** Jinja2 HTML templates + CSS variables + Playwright headless Chromium screenshot to PNG. Pillow only as a last-resort utility.
**Why:** Typography quality. Custom fonts, kerning, line-height, dark/light variants are trivial in CSS, painful in Pillow. Templates will iterate 100+ times during the project; CSS makes that cheap.
**Alternatives considered:**
- Pillow direct composition. Rejected: typographic quality ceiling too low.
- html2image. Rejected: flakier than Playwright.
- wkhtmltopdf. Rejected: dying project.
**Status:** Active

---

## #12 — Three cache layers, all by content hash

**Date:** 2026-06-30
**Decision:** Writer output cache (keyed by `(card_id, card_version, prompt_version, slot_plan_hash)`), render cache (keyed by `hash(template_id + content + accent + theme + brand_version)`), hashtag rotation log (last 10 carousels' sets).
**Why:** Iteration on text and templates must be free for unchanged slides. This is the property that makes solo daily use sustainable.
**Alternatives considered:** No caching, time-based caching. Rejected: time-based is wrong for content; hash-based is correct.
**Status:** Active

---

## #13 — Slot-driven generation, deterministic planner

**Date:** 2026-06-30
**Decision:** CarouselPlanner is pure Python rules. The LLM never decides slide count or slot structure; it fills slots given to it.
**Why:** Eliminates approximately 80% of "carousel is the wrong shape" failures. Structure follows card content; only content writing is creative.
**Alternatives considered:** LLM-driven slot decisions. Rejected: variance for no quality gain.
**Status:** Active

---

## #14 — Hard cap of 8 slides (7 content + 1 CTA)

**Date:** 2026-06-30
**Decision:** Carousel limited to 8 slides total, with priority-based dropping when conditional slots would exceed the cap. Drop order: proof → concept → mechanism → contrast (contrast last as load-bearing).
**Why:** Swipe-completion psychology — drop-off accelerates after slide 6. Instagram allows up to 20 but engagement falls off.
**Alternatives considered:** 10-slide cap, no cap. Rejected: 8 is the sweet spot for editorial content.
**Status:** Active

---

## #15 — Stable slot IDs as role slots, not instance UUIDs

**Date:** 2026-06-30
**Decision:** Slide `slot_id` is a stable role-based string like `"hook"`, `"timeline_1"`. Not a UUID per instance. If a script has two timeline slides, they are `timeline_1` and `timeline_2`, deterministically assigned.
**Why:** Targeted regenerate addresses positions. Render cache stable across regenerates. LayoutPicker keys off role directly.
**Alternatives considered:** UUID per slide. Rejected: breaks render cache and complicates targeted regenerate.
**Status:** Active

---

## #16 — `manually_edited` flag on Slide

**Date:** 2026-06-30
**Decision:** Slide model has a boolean `manually_edited` field, set to true when user edits inline. Targeted regenerate of other slides respects this flag and does not overwrite manually-edited slides.
**Why:** Without this, editing slide 4 inline then regenerating slide 6 could overwrite slide 4 because the prompt template re-emits all slides. The flag locks user changes.
**Alternatives considered:** No protection. Rejected: would break the regenerate UX immediately.
**Status:** Active

---

## #17 — Hook taxonomy: 4 patterns, anti-patterns named

**Date:** 2026-06-30
**Decision:** Writer selects hooks from 4 patterns: Contrast / Negative fact + reveal / Number shock / Insider declaration. Anti-patterns: pure questions (weak swipe pull), accusatory framing on geopolitical content (brand risk), witty setups as default (unsustainable). Hard constraints: ≤2 lines, ≤14 words.
**Why:** Bounds creative space to a known library. Eliminates 90% of bad hooks. Validated across 5 real Story Cards before lock-in.
**Alternatives considered:** Free-form hooks. Rejected: produces variance the user must review.
**Status:** Active

---

## #18 — Domain vocabularies in writer prompt

**Date:** 2026-06-30
**Decision:** World runs on consequences/events/casualties. Finance runs on reframes/experts/deadlines/percent-moves. AI&Tech runs on named entities and second-order ironies. These are hints to the writer, not hard rules.
**Why:** Different domains have different drama vocabularies, validated across 5 real cards.
**Alternatives considered:** Single universal hook approach across domains. Rejected: produced weaker hooks in Finance and AI&Tech test cards.
**Status:** Active

---

## #19 — Named-entity density rule for AI & Tech

**Date:** 2026-06-30
**Decision:** For AI & Tech only, every slide should carry at least one named entity (model, person, company, agency, product). Vague references ("a company", "an executive") signal weakness.
**Why:** Validated on Anthropic export controls test card. Named entities are AI & Tech's credibility currency.
**Alternatives considered:** Universal entity-density rule. Rejected: World cards have natural entity sparsity (events, casualties) that the rule would force.
**Status:** Active

---

## #20 — Structural contrast preservation rule

**Date:** 2026-06-30
**Decision:** When a card's transmission has explicit X-did-A / Y-did-B contrast, the writer must preserve at least one contrast slide. Contrast is structural, not decorative.
**Why:** Discovered while walking the Anthropic export controls card — the OpenAI-complies-while-Anthropic-resists contrast was load-bearing and dropping it weakened the carousel.
**Alternatives considered:** Let writer judge. Rejected: writer collapsed the contrast in test runs.
**Status:** Active

---

## #21 — Metaphor reuse permitted

**Date:** 2026-06-30
**Decision:** Writer is permitted to surface and reuse the card's strongest metaphor as slide copy when slide-grade (e.g. "weapon disposal unit" → "defusing the bomb").
**Why:** Voice continuity between card and carousel. The Intelligence Engine's composer already produces these; not using them wastes work.
**Alternatives considered:** Require original metaphors. Rejected: hurts voice continuity and adds creative load without quality gain.
**Status:** Active

---

## #22 — Narrative thread via echo, not conjunctions

**Date:** 2026-06-30
**Decision:** Narrative thread between slides comes from echoed language, setup-payoff pairs, escalation, and definite articles. Leading conjunctions ("But," "And," "However," "Meanwhile," "Now") are banned as slide openers.
**Why:** Conjunctions soften punch. Each slide is read in ~2 seconds; opener words eat the budget. Thread can be created without them.
**Alternatives considered:** Allow leading conjunctions. Rejected: produces softer hooks for no quality gain.
**Status:** Active

---

## #23 — 7 template archetypes for v1.0

**Date:** 2026-06-30
**Decision:** Statement, Number, Quote, Timeline, Concept, Hook, CTA. Portrait template added in v1.5 as 8th archetype.
**Why:** Validated across 5 real cards. Statement is the workhorse; Number and Quote handle "dominant element" slides; Concept handles mechanism and framework; Timeline handles dated event chapters.
**Alternatives considered:**
- 4 templates only. Rejected: misses Number/Quote/Concept patterns that strengthen carousels.
- 10+ templates. Rejected: each additional template multiplies design effort. 7 is the sweet spot.
**Status:** Active

---

## #24 — Mechanism slide and Concept slide use same template

**Date:** 2026-06-30
**Decision:** Mechanism slides (explaining how something works) and Concept slides (stating a framework) use the same Concept template visually. They are different writer jobs but render identically.
**Why:** Visually they are both text-heavy, no numbers, no quotes, mid-carousel slides. No need for two templates.
**Alternatives considered:** Distinct templates. Rejected: needless template multiplication.
**Status:** Active

---

## #25 — Distinct domain palettes, single accent each

**Date:** 2026-06-30
**Decision:** Three accent colours, one per domain. World: warm red. Finance: deep gold. AI & Tech: electric cyan. (Exact hex pinned during template-design week.)
**Why:** Domain-distinct accents give feed-grid recognition. Going against type (red for World instead of neutral; gold for Finance instead of green; cyan for AI instead of blue) makes the brand feel intentional rather than generic.
**Alternatives considered:** Single unified palette across domains. Rejected: weaker grid identity for editorial content.
**Status:** Active

---

## #26 — Dark theme default for v1.0

**Date:** 2026-06-30
**Decision:** All v1.0 templates use a dark theme (near-black background, cream off-white body text, single accent). Light theme variant supported in schema but not used in v1.0.
**Why:** Editorial intelligence content reads more serious on dark. The chassis is fixed; the variant is optional and reserved.
**Alternatives considered:** Light theme default. Rejected: less serious register. Mixed dark/light per card. Deferred — too many variables at once.
**Status:** Active

---

## #27 — Typography-only visual system in v1.0 (Path A)

**Date:** 2026-06-30
**Decision:** v1.0 carousels use heavy display typography only. No photographic backgrounds, no AI imagery, no illustrations, no portraits. Portrait template added in v1.5; editorial imagery in v2.
**Why:** Long discussion (see chat log). Considered Path B (@wealth-style cinematic imagery) and Path C (typography + portraits). v1.0 commits to typographic chassis first; portrait support is a clean additive upgrade once we have post performance data.
**Alternatives considered:**
- Path B (@wealth-style imagery, AI-generated backgrounds). Rejected for v1.0: AI imagery has credibility risk for editorial content; pipeline complexity multiplies; not worth it before audience data exists.
- Path C (typography + portraits in v1.0). Considered. Decided to defer portraits to v1.5 to keep v1.0 scope tight and ship in ~3 weeks. All seams for portrait support wired in from day one.
**Status:** Active

---

## #28 — Sync-to-folder publishing for v1.0 (Option 2)

**Date:** 2026-06-30
**Decision:** v1.0 ships with "Approve & Sync" — writes bundle to a configured local directory that auto-syncs to phone via iCloud or Google Drive. Manual posting via Instagram app from phone. Graph API publishing is v2.
**Why:** Zero Meta dependency in v1. No app review, no account risk, no OAuth, no image hosting. Architecture has clean seam for v2 Publisher swap-in. 90 seconds of phone friction per post is acceptable for v1.
**Alternatives considered:** Option 1 (Graph API in v1). Rejected for v1.0: 2–4 weeks of Meta app review, account-revocation risk, fragility of most-external dependency, premature before audience data.
**Status:** Active

---

## #29 — CTA copy locked: "Follow @handle for daily intelligence"

**Date:** 2026-06-30
**Decision:** Final slide of every carousel reads "Follow @handle for daily intelligence." Fixed copy, fixed slot.
**Why:** CTA needs to be consistent across feed to build the follow pattern. "Daily intelligence" frames the value proposition.
**Alternatives considered:** "Link in bio," "Save for later." Less direct; weaker action.
**Status:** Open — actual handle pending (anonymous account to be created)

---

## #30 — Pinned comment: lifted screenshot line from payoff

**Date:** 2026-06-30
**Decision:** The writer identifies the single most screenshot-worthy sentence (typically from the payoff slide) and restates it as `pinned_comment`. No hashtags, no @mentions, no questions. Standalone line.
**Why:** Pinned comments drive engagement and save rates on Instagram. The screenshot-line move is the @wealth pattern. Low effort for writer; the line already exists.
**Alternatives considered:**
- Question to drive comments. Rejected: feels engagement-baity.
- Repeat the CTA. Rejected: redundant.
**Status:** Active

---

## #31 — Hashtag selection from curated YAML pool, never LLM-generated

**Date:** 2026-06-30
**Decision:** Maintain `hashtags.yaml` with 30–50 curated tags per domain plus 10–15 cross-domain tags. For each carousel, sample 18–22 tags based on `hashtag_themes` from the spec, weighted with rotation to avoid repeating exact sets.
**Why:** LLM-generated hashtags hallucinate inactive or banned tags. Curated pool + rotation is the reliable approach.
**Alternatives considered:** LLM generation. Rejected for hallucination risk.
**Status:** Active

---

## #32 — JSONB for spec storage in Supabase

**Date:** 2026-06-30
**Decision:** The `carousels` table stores the full `CarouselSpec` as JSONB. Pydantic validates at the application layer.
**Why:** The spec evolves through v1.0 → v1.5 → v2. Hard schema columns require migrations on every field addition. JSONB + Pydantic gives flexibility without sacrificing type safety.
**Alternatives considered:** Hard columns from day one. Rejected: would force schema migration on every Slide field addition.
**Status:** Active

---

## #33 — Anonymous Instagram account for experiment

**Date:** 2026-06-30
**Decision:** Carousels publish to an anonymous Instagram account, not to the user's personal account. Account to be set up before v1.0 ships.
**Why:** Project is a learning experiment. Building from zero audience is intentional — measure organic discovery, follower growth, what content resonates. Personal account would contaminate the signal.
**Alternatives considered:** Personal account. Rejected: contaminates audience signal and risks personal brand.
**Status:** Open — account creation pending

---

## #34 — Schema versioning on CarouselSpec

**Date:** 2026-06-30
**Decision:** `CarouselSpec` has a `schema_version` field. Initial value `"1.0"`. Bumps on breaking changes. Older spec versions remain readable by upgraded code via read-time migration.
**Why:** The spec is the load-bearing model. Versioning lets us evolve without breaking existing stored carousels.
**Alternatives considered:** No versioning. Rejected: previous project pain.
**Status:** Active

---

## #35 — Future-feature seams wired in from day one

**Date:** 2026-06-30
**Decision:** v1.0 Slide model includes `Optional` fields for `image_asset` (v1.5), `audio_clip_id` (v2), `animation_hint` (v2). LayoutPicker has the portrait selection rule wired in but inert. Streamlit UI has the "Add image" and "Publish to Instagram" buttons present but disabled.
**Why:** "Backend infra needs to be great" — adding seams later requires touching every component. Adding fields as Optional from day one is free now and saves rework later.
**Alternatives considered:** Add fields when needed. Rejected: previous project pain from this exact pattern.
**Status:** Active

---

## #36 — Reels companion deferred to v2, not v1.0

**Date:** 2026-06-30
**Decision:** Reels are not generated in v1.0. In v2, an optional Reel companion is generated alongside each carousel: condensed script from CarouselSpec, ElevenLabs voiceover with pronunciation overrides, synced captions, ken-burns background. Carousel remains the primary format.
**Why:** Reels have algorithm advantages on IG but ElevenLabs voiceover has reliability issues with proper nouns (geopolitical names, AI products). Pronunciation database is a real ongoing cost. Defer until carousels prove the content works.
**Alternatives considered:**
- Reels instead of carousels in v1. Rejected: throws away most architecture work; harder to iterate solo; format is wrong for editorial intelligence audience initially.
- Reels in v1 alongside carousels. Rejected: scope creep before any audience signal exists.
**Status:** Deferred to v2

---

## #37 — Build templates before any pipeline code

**Date:** 2026-06-30
**Decision:** Template-design week comes before any Python implementation. Hand-coded HTML/CSS in a browser, no project code. Hard limit: 2 weeks.
**Why:** Templates are the load-bearing creative decision. If templates are mediocre, every carousel is mediocre forever. Time investment here is the right place.
**Alternatives considered:** Build pipeline first, design templates parallel. Rejected: templates dictate the Slide schema in practice. Wrong order.
**Status:** Superseded by #46

---

## #38 — 4-week learning phase, then v1.5 scoping review

**Date:** 2026-06-30
**Decision:** After v1.0 ships, run for 4 weeks (approximately 28 carousels) before deciding v1.5 scope. v1.5 decisions are made on real performance data, not theory.
**Why:** Experimentation is the project's success criterion. Without post data, v1.5 planning is guessing.
**Alternatives considered:** Plan v1.5 fully now. Rejected: premature.
**Status:** Active

---

## #39 — DIY template design, AI-assisted HTML/CSS

**Date:** 2026-06-30
**Decision:** Templates designed by user. AI assistance (Claude / Cursor) for generating HTML/CSS from prose descriptions. No external designer commission. No Figma. No Canva. No design subscriptions.
**Why:** Templates evolve through usage; commissioning blocks iteration. AI-assisted CSS generation has matured enough to be a primary tool. User keeps ownership of taste.
**Alternatives considered:** Commission designer for visual system spec. Rejected: user prefers DIY for learning.
**Status:** Active

---

## #40 — One creative LLM call per carousel as the discipline

**Date:** 2026-06-30
**Decision:** Discipline statement: the v1.0 generation pipeline makes one Sonnet call (writer) and one Haiku call (ContextBuilder extraction). Regenerates add calls only when triggered by user. Steady-state target: 1.0–1.3 LLM call sequences per approved carousel.
**Why:** Variance is the expensive resource, not cost. Each LLM call is a surprise to babysit. Fewer calls = faster approval = more carousels shipped.
**Alternatives considered:** Multi-call planner/writer/captioner chain. Rejected.
**Status:** Active

---

## #41 — Same repository, new top-level `carousel/` module

**Date:** 2026-06-30
**Decision:** The carousel engine lives in the same repository as the existing Intelligence Engine, as a new top-level `carousel/` module. Not a separate repo, not a git submodule. Boundary discipline: `carousel/` reads from `pipeline/` and `db/`, never modifies them; `pipeline/` never imports from `carousel/`.
**Why:**
- Shared Story Card contract — one Pydantic definition used by both engines, no cross-repo schema drift.
- Shared infrastructure (Supabase client, env handling, Streamlit scaffold, Anthropic client, logging, cost tracking) already exists and gets reused.
- One Streamlit UI — the "Generate Carousel" button lives inside the existing card view.
**Alternatives considered:**
- Separate repo. Rejected: forces duplicate Story Card schema definitions, duplicate infrastructure, and a third shared-library repo — over-engineering for a solo project.
- Git submodule. Rejected: adds commit/sync/checkout complexity for benefits that don't exist at this scale.
- Feature branch until "ready." Rejected: the carousel module is inert until invoked; no risk of breaking the Intelligence Engine because it doesn't touch anything the engine uses. Direct commits to default branch are correct.
**Status:** Active

---

## #42 — Background colour: warm dark brown `#1A1612`, not cold black

**Date:** 2026-06-30
**Decision:** Background for all v1.0 slides is `#1A1612` — a very dark warm brown. Not `#0E0E0E` (cold near-black), not `#000000` (pitch black). The warm brown reads like aged leather or a dimly lit library. Cold black reads like a dark mode UI. The distinction is what makes the slides feel "cozy and dense" rather than "harsh and digital."
**Why:** Validated by rendering three slides at preview size and user confirming "yes, exactly what I had in mind." Fine hex value to be confirmed during template-design week but warm dark brown direction is locked.
**Alternatives considered:** Cold near-black `#0E0E0E` (first mockup — user reaction: "jarring, repelling"). Pure black `#000000`. Rejected both.
**Status:** Active

---

## #43 — Headline font locked: Playfair Display 700 and 900

**Date:** 2026-06-30
**Decision:** Headline font is Playfair Display, weights 700 and 900 only, self-hosted as `.woff2` files. Not Space Grotesk, not Archivo Black, not Inter Display. Playfair Display is a high-contrast serif with ink-trap detail that renders dramatically at large sizes and gives the slides genuine editorial character. Body font remains Inter 400 and 500.
**Why:** Validated by rendering three slides. The Playfair Display / Inter pairing is what makes these slides read as editorial rather than generic. It is the single decision most responsible for the "cozy dense premium" register. Also matches the visual approach of the ankitgraphic reference account the user approved.
**Alternatives considered:** Space Grotesk (sans, punchy but no editorial weight), Archivo Black (display sans, too aggressive), Inter Display only (capable but loses the serif/sans contrast). All rejected.
**Status:** Active — final, not subject to template-week revision

---

## #44 — World domain accent changed to amber gold `#C8813A`

**Date:** 2026-06-30
**Decision:** World domain accent is amber gold `#C8813A`, not warm red `#E63946` (earlier decision #25). On a warm dark brown background, amber reads like candlelight — inviting and editorial. Red on warm brown can feel muddy or alarming. Finance and AI & Tech domain accents TBD during template-design week; Finance should be cooler than World to create contrast; AI & Tech stays at electric cyan `~#00D9FF`.
**Why:** Discovered during mockup iteration. The warm background changed the colour dynamics; what works on cold black (red) doesn't work on warm brown (amber does).
**Alternatives considered:** Keeping warm red `#E63946` from Decision #25. Rejected on visual grounds — muddy on warm background.
**Supersedes:** Decision #25 (World domain accent portion only). Finance and AI & Tech portions of #25 carry forward as-is.
**Status:** Active

---

## #45 — Thin rule line as structural design element

**Date:** 2026-06-30
**Decision:** A single thin horizontal rule in the domain accent colour (at 15–25% opacity) is used as a structural divider between the headline and the emphasis/body text. Maximum one per slide. This is a design element, not decoration — it tells the eye where to move and adds refinement without adding visual noise.
**Why:** Validated in the mockup. The rule line on slide 1 (between "Putin doesn't admit problems" and "Today, he did.") is the move that makes the slide read as composed rather than just text-on-background.
**Alternatives considered:** No rule lines (feels flat), full-opacity rules (too heavy), multiple rules (clutter). All rejected.
**Status:** Active

---

## #46 — Render script included in Phase 1 template design

**Date:** 2026-06-30
**Decision:** A minimal Playwright render script is created during Phase 1
template-design week alongside the HTML/CSS templates. It lives in
`tests/carousel/test_render.py`, imports nothing from `carousel/*.py`, and
has one job: HTML file path + output path → PNG at 1080×1350. It is a design
feedback tool, not a pipeline component. When SlideRenderer (Phase 3) is
built, it decides independently whether to reuse this script.
**Why:** Blueprint §11.6 names the phone-render check as the only true
quality gate. Getting to a real PNG on day one shortens the feedback loop
from days to hours without creating pipeline code.
**Constraint:** If any prompt during Phase 1 tries to import from
`carousel/*.py` in this script, or add Pydantic models to it, that is scope
creep and must be refused.
**Alternatives considered:** Browser-only preview (slower feedback, no true
resolution check). Full renderer from day one (violates Phase 1 scope). Both
rejected.
**Supersedes:** Decision #37 (letter only, not spirit).
**Status:** Active

---

## #47 — StoryCard defined in carousel/models.py, not imported from pipeline

**Date:** 2026-06-30
**Decision:** StoryCard is defined independently in carousel/models.py,
sourced from db/schema.sql and the db layer files — not imported from
pipeline/models.py.
**Why:** pipeline/models.py contains LLM DTOs only, not a persisted-card
contract. The db layer is the correct source of truth for the carousel
engine's StoryCard definition. Importing from pipeline would create a
coupling to the wrong abstraction.
**Alternatives considered:** Option A (import from pipeline/models.py)
— rejected because pipeline/models.py has no persisted-card contract.
**Supersedes:** The Option A recommendation made earlier this session.
**Status:** Active

---

## #48 — DeltaEvent.dialogue as list[dict], not list[DialogueTurn]

**Date:** 2026-06-30
**Decision:** DeltaEvent.dialogue is typed as list[dict] in
carousel/models.py, not list[DialogueTurn].
**Why:** DialogueTurn is an unrelated pipeline DTO. Importing it would
violate Decision #41's boundary discipline — carousel imports from
pipeline only for genuine shared contracts, not convenience. JSONB
passthrough is correct for a field the carousel only reads.
**Alternatives considered:** Redefine DialogueTurn in carousel/models.py
(3 lines). Rejected — adds a type that carousel never validates or
generates. Unnecessary complexity.
**Status:** Active

---

## #49 — Domain not stored in EnrichedSpec

**Date:** 2026-07-05
**Decision:** Domain is not a field on CarouselSpec or EnrichedSpec.
When domain is needed after generation (renderer, carousel_view),
it is recovered via reverse lookup against DOMAIN_ACCENTS in
layout_picker.py.
**Why:** Adding domain to CarouselSpec would require a models.py
change and a Supabase migration. Reverse lookup is a pragmatic
v1.0 fix.
**Status:** Open — domain should be added to CarouselSpec in v1.5
to eliminate the reverse lookup dependency.

---

## #50 — Playwright local-only for v1.0

**Date:** 2026-07-05
**Decision:** Carousel generation runs locally only. Playwright
will not be supported on Streamlit Cloud in v1.0.
**Why:** Playwright requires system-level Chromium dependencies
not available on Streamlit Cloud's containerised environment.
Cloud rendering is v2 work.
**Status:** Active. Deferred to v2.

---

## #51 — Body text centred for social media register

**Date:** 2026-07-05
**Decision:** All slide content (headline and body) is centred
horizontally. Left-aligned body was considered but rejected.
**Why:** Primary use is Instagram carousel posts. Centred text
performs better visually in the feed and matches the social
media register.
**Status:** Active.

---

## Open questions to revisit

- **Anonymous handle name.** Pending account creation.
- **Final accent colour hex values per domain.** Pinned during template-design week.
- **Display font selection.** Pinned during template-design week. Candidates: Space Grotesk (free), Inter Display (free), Founders Grotesk (paid), Pangram Sans (paid for commercial use).
- **Body font selection.** Pinned during template-design week. Candidates: Inter, IBM Plex Sans.
- **Exact sync-to-folder path.** Pinned at v1.0 ship — depends on user's iCloud vs Google Drive choice.
- **Hashtag pool initial seeding.** Pre-launch task — build curated tag lists for World / Finance / AI & Tech.

---

## Change log

- 2026-06-30: Log seeded with decisions #01–#40 from 8 design exchanges. Blueprint v1.0 written. Template-design week begins next.
- 2026-06-30: Decision #41 added — repository structure and boundary discipline. Blueprint updated with new section 18 (Repository layout) covering directory structure, boundary rules, pre-implementation scaffolding, branch strategy, and Claude Code context requirements.
- 2026-06-30: Decisions #42–#45 added — visual system locked after mockup validation and user approval. Background warm dark brown `#1A1612`, headline font Playfair Display 700/900 (final, not subject to template-week revision), World accent changed to amber gold `#C8813A` (supersedes #25 World portion), thin rule line as structural design element. Blueprint Section 11 fully rewritten to reflect these locks.
- 2026-06-30: Decisions #47–#48 added — deviations from Blueprint §6
  recorded. StoryCard defined from db schema, not pipeline. dialogue
  field typed as list[dict] per boundary discipline.
- 2026-06-30: Decision #46 added — Phase 1 template design includes a
  minimal Playwright render script as a design feedback tool. Supersedes
  #37 in letter only. Constraint recorded: the script must not import from
  `carousel/*.py` and must not carry Pydantic models.
- 2026-07-05: Decisions #49–#51 added — domain schema gap,
  Playwright local-only, body text centring for social media.
