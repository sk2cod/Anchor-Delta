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

## #52 — Per-carousel sync folders in configurable Google Drive directory

**Date:** 2026-07-06
**Decision:** "Approve & Sync" writes each carousel's bundle into a
per-carousel subfolder inside a configurable `CAROUSEL_SYNC_DIR`
(env-driven, default `G:\My Drive\Anchor & Delta\Outbox`). Subfolder
name is `YYYY-MM-DD_domain_slug`, where the date is the generation
date, domain is the card's domain, and slug is a filesystem-safe slug
of the card's `umbrella_title`. If the target subfolder already exists
(same-day regenerate of the same card), a short suffix is appended —
never overwrite an existing bundle. Failures (unwritable path, drive
unavailable) raise loudly and surface in the Streamlit UI.
**Why:** Eliminates the manual copy-to-Drive step and keeps the
native-app music/photo sync workflow the user already has. ISO date
prefix sorts subfolders chronologically with zero stored state.
**Alternatives considered:** A flat `Outbox/` folder with no
subfolders — rejected, gets messy fast once more than a few carousels
accumulate. A sequential counter (`C1`, `C2`, ...) — rejected, requires
stored counter state, collides on resets, and doesn't sort
chronologically the way an ISO date does.
**Note:** This mildly strengthens the future case for Decision #49's
domain-field fix (folder naming currently depends on the same
card-lookup reverse-inference) without resolving it — that fix stays
parked for v1.5.
**Status:** Active.

---

## #53 — Cover template archetype for slide-1 hook role

**Date:** 2026-07-06
**Decision:** A dedicated, bottom-anchored Cover template is selected
by LayoutPicker for the hook role, replacing the interior-styled Hook
template for slide 1. Composition: kicker (the card's umbrella_title),
a provocative headline with an accent-coloured italic emphasis
fragment, a thin accent rule (max one per slide, Decision #45), a
curiosity sub-line, a "swipe →" indicator, and the existing domain tag
and footer chassis retained. The writer prompt is bumped to
`writer-v1.1` with a cover-copy sub-rule carrying a provocative-but-
grounded guardrail: punchy phrasing is allowed, but every claim in the
kicker/headline/sub-line must be directly supported by the card's
anchor_text or transmission — no fabricated drama, no accusatory
framing on World/geopolitical content (Decision #17 anti-patterns
still bind).
**Why:** Slide 1's job in the feed grid — earn a tap from a stranger
who has never seen the account — differs from the interior slide's
job of sustaining swipe-pull once someone is already in the carousel.
The old Hook template rendered too close to the interior Statement
slide's visual register to do that job. This is the highest-leverage
visual change available for follower growth from a scratch account.
**Alternatives considered:** Background or flag imagery behind the
headline — rejected on credibility-risk grounds (Decision #27 already
ruled out photographic/AI-generated imagery for v1.0 on the same
brand-safety basis). Keeping the centred Statement-style hook —
rejected, it fails to stop the scroll; it reads as just another
interior slide.
**Status:** Active.

---

## #54 — Regenerate-gap fix: kicker preserved and regenerated on Model B cover-slide path

**Date:** 2026-07-06
**Decision:** `regenerate_slide()` now extracts the existing `kicker`
from the target slide in the current `CarouselSpec` and passes it as
context ("current kicker: ...") when the target is the hook/cover
slot. `regenerate_v1_1.md` (new file; `regenerate_v1_0.md` untouched
per Decision #08) adds a cover-copy sub-rule matching `writer_v1_1.md`
exactly — kicker returned unchanged unless the editor's instruction
asks otherwise, headline ≤2 lines/≤14 words, body carries the
curiosity sub-line, same provocative-but-grounded guardrail (Decision
#17 anti-patterns bind). Validation now raises if the model returns
`kicker: null` for a hook/cover slide, feeding the existing one-retry
mechanism, instead of silently constructing a slide with a blank
kicker.
**Why:** A targeted regenerate of slide 1 was resetting `kicker` to
`None` (the `Slide(...)` construction in `regenerate_slide()` never
passed it through), breaking the cover template's most-used edit path
until the next full-carousel regenerate.
**Status:** Active.

---

## #55 — Quote slot as dedicated 9th slide when both dominant number and strong quote present

**Date:** 2026-07-06
**Decision:** A dedicated `quote` slot is added to `planner.py`,
inserted immediately after `proof` and before `contrast`/`payoff` in
`SLOT_ORDER`. It fires only when `dominant_numbers` AND
`available_quotes` are BOTH non-empty simultaneously — never for
either alone, since `proof` already handles the number-only case.
When it fires, the per-carousel cap resolves to 9 slots (a local
`max_slots` variable in `plan_carousel()`, not a change to the global
`MAX_SLOTS = 8` constant); otherwise the cap stays 8. `DROP_PRIORITY`
is extended with `quote` last — most protected of all optional slots.
`quote` is `is_optional: True`. Writer prompt bumped to `writer-v1.2`
(new file; `writer_v1_1.md` untouched per Decision #08) with a
dedicated `## quote` slot guide: select the single strongest sourced
quote from `available_quotes`, populate `Slide.quote` as a structured
`{text, attribution, role}` object, headline = attribution name only,
body = empty, emphasis_word = the quote's strongest word or null.
Hard guardrail: the quote must be copied verbatim from
`available_quotes` — never fabricated or paraphrased; if no quote is
strong enough to stand alone, the slot falls back to a Statement-style
slide with `quote: null`. A parallel `## proof` guide clarifies proof
always takes the number and never populates `quote`. `SlotRole.quote`
added to the enum in `models.py` (the only place `SlotRole` is
defined). The Number template gets a ghost-number treatment (same
value, ~260px Playfair 900, accent colour at 7% opacity, centred
behind the foreground content via an explicit `z-index` stacking
context). The Quote template gets oversized decorative quotation marks
(~180px Playfair 900, accent colour at 15% opacity, top-left/
bottom-right, clear of the domain tag and footer) plus a `role` line
under the attribution and correct emphasis-word treatment on the quote
text — `renderer.py`'s existing `quote` dispatch branch was missing
both, extended in the same pattern as the `cover` branch (Decision
#53).
**Why:** The diagnostic pass confirmed all downstream components
(assembler, renderer, writer, UI) are already slide-count agnostic —
the only structural blocker to a 9th slide was `planner.py`'s hard
cap. Separately, quote content was being buried in body prose with no
dedicated slot or visual treatment, and no writer instruction ever
populated the structured `quote` field, so the existing Quote template
never fired. A direct, high-authority attribution is stronger
follower-growth content than a generic contrast slide when the card
actually has one.
**Note:** Because `quote`'s condition is a strict superset of
`proof`'s (both require `dominant_numbers` non-empty), and `proof` is
first/least-protected in `DROP_PRIORITY` while `quote` is
last/most-protected, a cap-overflow carousel can in principle drop
`proof` while `quote` survives — a quote slide without a corresponding
number slide in the same carousel. This follows the literal spec as
given; flagging it as worth confirming is intentional, not a defect.
**Status:** Active.

---

## #56 — Real quotes reach extraction + deterministic anti-fabrication guard

**Date:** 2026-07-07
**Root cause:** `context_builder.py`'s `_extraction_input_text()` built
the Haiku quote/entity/number extraction input from only
`umbrella_title + anchor_text + latest_delta.headline/tldr +
transmission_summary.nodes` — it never read `delta_events[*].dialogue`,
and `DeltaSummary` (what `latest_delta` actually is) drops dialogue
before extraction even sees it. Confirmed on the Canada/Alberta
pipeline card: `available_quotes` was empty despite the card
containing four real sourced quotes (Carney, Smith, Eby, Slett) in
`dialogue`. With no real quotes available, the writer fabricated a
"quote" by lifting the transmission's editorial *"so what"* prose
verbatim and self-labelling it `attribution: "Article text"`,
`role: "Editorial conclusion"` — `writer_v1_2.md`'s existing `## quote`
guardrail (verbatim-from-`AVAILABLE QUOTES`, never fabricate, fall back
to a Statement slide otherwise) was correct and unchanged; it was
simply ignored by the model.
**Fix 1 (`context_builder.py`):** `delta_events[*].dialogue` is
flattened into `"speaker: quote"` lines and appended as a genuinely
additional `QUOTES:` block to the extraction input — the four existing
inputs are untouched and unreordered. Its budget is reserved off the
total *before* truncating the rest (not simply appended-then-truncated)
so real quotes survive regardless of how long `anchor_text`/
transmission happen to be; `MAX_EXTRACTION_INPUT_CHARS` raised
2000 → 3000 for headroom. Verified against the real Canada/Alberta
card: `available_quotes` now returns all four quotes with correct
`attribution`/`role` (e.g. `text="Move faster, build bigger and work
together.", attribution="Mark Carney", role="Canada's Prime
Minister"`).
**Fix 2 (`writer.py`):** a deterministic Python guard,
`_quote_attribution_matches_card()`, runs inside
`_build_spec_from_response()` after every full-carousel generation.
For any slide with a populated `Slide.quote`, its `attribution` must
match (case-insensitive, substring-tolerant) a real speaker in
`context.available_quotes`; if not, it raises — feeding the *existing*
one-retry-with-error-feedback mechanism already used for every other
writer validation failure, same philosophy as the kicker-`None` guard
in `regenerate_slide()` (Decision #54). Verified with a mocked client:
persistent fabrication across both attempts raises a clear
`CarouselWriteError` (the fabricated quote is never rendered); a
fabricated first attempt corrected by a real quote on retry succeeds
normally; a real quote on the first attempt passes straight through.
**Why code, not the LLM:** Decision #03 — Python owns determinism. The
model already had an explicit, correct guardrail in the prompt and
ignored it; asking it to self-verify its own fabrication would be
circular. The judgment (does this attribution match a real card
speaker?) is now a deterministic string check with zero LLM
involvement — only the retry's replacement *content* still comes from
the model, exactly as for every other validation failure in this file.
**Scope note:** this guard is wired into `write_carousel()`'s
full-carousel path only, where `context.available_quotes` is already
available. `regenerate_slide()` (Model B) has no access to the card's
real quotes at all today (no `StoryContext`/card data is threaded
through it) — extending the same guard there would require adding new
parameters and updating its caller in `ui/carousel_view.py`, which is
out of scope for this fix.
**Status:** Active.

---

## #57 — Fact sheet replaces single-number proof template

**Date:** 2026-07-07
**Decision:** The Number template is rebuilt from scratch as a
multi-figure fact sheet: a writer-generated title above up to 4 rows,
each row a description (left) and its figure (right), with thin accent
dividers between rows. `Slide.dominant_number: Optional[DominantNumber]`
is renamed to `Slide.dominant_numbers: Optional[list[DominantNumber]]`
(additive/Optional — no schema-version bump, no Supabase migration).
`Slide.factsheet_title: Optional[str]` added for the creative title.
`layout_picker.py`'s number-selection rule updated to
`slide.dominant_numbers is not None and len(slide.dominant_numbers) > 0`.
Writer bumped to `writer-v1.3` (new file; `writer_v1_2.md` untouched
per Decision #08): the `## proof` guide now instructs selecting up to 4
hook-grade figures from `KEY NUMBERS` (dramatic scale, alarming
dependency, counterintuitive ratio, visceral speed/time/distance;
routine figures may ride alongside genuinely hook-grade ones but don't
qualify alone) plus a punchy ≤8-word `factsheet_title`. The old
single-`dominant_number` instruction is removed entirely.
**Why:** A single dominant number stops one scroll; multiple hook-grade
figures together convey cumulative scale — confirmed on the Space
Force card, where 17,500 mph orbital speed + the 2019 Space Force
founding + the July 3 intercept date read as a stronger set than any
one figure alone. A routine figure (e.g. a founding year) earns
presence alongside dramatic ones without overclaiming on its own.
**Verification:** ran the full pipeline (`build_context` →
`plan_carousel` → `write_carousel`) live against the real Space Force
card. The writer correctly populated `dominant_numbers` (3 real
figures, each with `value`/`label`/`context` copied from `KEY NUMBERS`)
and `factsheet_title` ("The numbers behind the orbital race."). Test-
rendered at 2160×2700 → 1080×1350 with the per-domain accent (ai_tech
cyan) resolving correctly — no hardcoded domain hex.
**Note:** `regenerate_slide()` in `writer.py` constructed `Slide(...)`
with the old `dominant_number=` kwarg — updated to
`dominant_numbers=`/`factsheet_title=` so the rename doesn't silently
break Model-B regenerates of the proof slot. `regenerate_v1_1.md`
itself still describes the old singular field in its output schema and
was not updated (out of scope for this change) — a proof-slot targeted
regenerate won't populate the new fields correctly until that prompt is
separately updated.
**Status:** Active.

---

## #58 — Domain-aware hook-grade examples in writer prompt — all three domains

**Date:** 2026-07-08
**Problem:** The `## proof` slot's hook-grade definition (Decision #57)
was a single universal bar — "dramatic scale, alarming dependency,
counterintuitive ratio, or visceral speed/time/distance" — that reads
naturally for World/geopolitical content but was quietly biased toward
it. Finance cards with genuinely hook-grade numbers (yield curve
inversions, debt-to-GDP extremes, rate-decision persistence) and
AI&Tech cards (hallucination-rate drops, parameter efficiency ratios,
named-competitor benchmark differentials) were being passed over
because none of them read as "visceral scale" the way a military speed
or a chokepoint percentage does — even though they're exactly as
significant to their own technically-literate audience.
**Fix:** Added a `DOMAIN-SPECIFIC HOOK-GRADE EXAMPLES` section to
`writer_v1_5.md` (new file; `writer_v1_4.md` untouched per Decision
#08), inserted immediately after the existing universal hook-grade
definition — which stays intact and unchanged. Three domain blocks,
each with its own hook-grade bar, GOOD examples, and an explicit
NOT-hook-grade list: World/geopolitical (chokepoint percentages,
diplomatic deadlines, military speeds/distances), Finance/
macroeconomics (yield curves, debt ratios, rate-decision history,
currency extremes, market-cap comparisons — using the Canada pipeline's
C$150B investment and 97% US export dependency as canonical examples),
and AI & Tech (hallucination/error-rate changes, parameter efficiency,
named-competitor benchmark differentials, hardware efficiency — using
Tencent Hy3's hallucination-rate drop from 12.5% to 5.4% as the
canonical example, with an explicit ALWAYS-include instruction when
that kind of data is present). A closing CRITICAL RULE explicitly
forbids applying the World visceral-scale bar or the Finance yield/rate
bar to AI&Tech numbers, and vice versa.
**Why:** Each domain has its own technically-literate audience with its
own sense of what's alarming or surprising — a macro trader finds a
190bps sovereign spread hook-grade; a general reader would not, and
wouldn't need to. A universal visceral-scale bar systematically
under-selects for Finance and AI&Tech cards, leaving their fact sheet
slides thinner (or entirely proof-less) even when the underlying card
has strong, genuinely hook-grade numbers available.
**Status:** Active.

---

## #59 — Transmission truncation bug drops hook-grade numbers from later nodes — dedicated full-transmission number extraction pass added

**Date:** 2026-07-08
**Root cause:** `_build_transmission_summary()`'s 6-line truncation
heuristic (used to build `transmission_summary.nodes` for writer
context and slot planning — correct for that purpose, left untouched)
only ever reaches roughly the first node of a transmission before the
line cap is exhausted. Confirmed via `pipeline/engine.py`'s
`COMPOSE_NEW_CARD_SYSTEM_PROMPT`: "The so what:" lines are explicitly
scoped as one-sentence editorial conclusions ("why this matters right
now"), not data carriers — nothing instructs the composer to put
numbers there. The actual numbers-bearing content is the node body
prose, per Voice Rule 5 ("the reader needs... the specific numbers...
give them everything"), which applies to **every** node, not just the
first. Confirmed directly on the real Tencent Hy3 card
(`e0670639-b34f-4a40-a1bf-27537a190fbb`): its hallucination-rate
figures (12.5% → 5.4%) live in Node 4 of 4, entirely past the 6-line
cutoff — `context.dominant_numbers` was empty before this fix. Same
structural pattern as Decision #56's dialogue-truncation bug.
**Fix:** `_extraction_input_text()` in `context_builder.py` adds a
`TRANSMISSION NUMBERS:` block built from the full raw
`card.transmission.nodes_markdown` (all nodes, untruncated) — reserved
in full and appended after truncating the rest of the input, exactly
like the Decision #56 dialogue block, so it can never be silently cut
by the length cap. `_build_transmission_summary()` and the existing
quote/entity extraction logic are untouched. `MAX_EXTRACTION_INPUT_CHARS`
raised 3000 → 10000 (a real transmission body alone runs ~6-7k
characters; a tighter cap would starve the base context — title/
anchor/headline/tldr — down to nothing whenever a reserved block is
large, which is now the common case, not the exception). Also raised
`max_tokens` on the Haiku extraction call 1024 → 4096: the fuller input
gave Haiku proportionally more to report, and 1024 was cutting the
JSON response off mid-string, failing to parse and silently falling
back to empty lists for quotes/entities/numbers alike — a direct,
necessary side effect of feeding Haiku more material that had to be
fixed for the primary fix to actually work.
**Why the full-transmission-body fix over a higher line cap or
targeting "so what" lines:** a higher line cap is still an arbitrary
heuristic that breaks again on a long enough transmission — line count
doesn't map cleanly to node boundaries. "So what" lines are explicitly
not designed to carry data per the composer prompt itself. The full
transmission body is the only source that's structurally guaranteed to
contain every node's numbers, because Voice Rule 5 mandates specific
numbers in the body prose of every node, not any one section.
**Verified end-to-end** against the real Tencent Hy3 card:
`context.dominant_numbers` now returns 15 figures spanning all 4
nodes — including `value='12.5%', label='Hy3 hallucination rate in
April preview'` and `value='5.4%', label='Hy3 hallucination rate in
full release'`. `available_quotes` and `key_entities` (16 entities)
confirmed still populated correctly — no regression from the larger
input.
**Status:** Active.

---

## #60 — Proof and quote slots are purely additive — cap raises dynamically to 9 or 10, never drops these slots

**Date:** 2026-07-08
**Problem:** `proof` was first in `DROP_PRIORITY` — the very slot that
exists because the card has genuine data was the *first* one sacrificed
whenever a card was rich enough to fill the base 8 slots. Worse: the
9-slide expansion only fired when the `quote` slot was present, so a
card with both `dominant_numbers` and a strong quote would expand to 9,
then `proof` (still first in `DROP_PRIORITY`) got dropped to bring the
count back down — leaving `quote` alone and defeating the entire point
of having both.
**Fix:** `proof` and `quote` removed from `DROP_PRIORITY` entirely —
`carousel/planner.py`'s `DROP_PRIORITY` is now `(concept, mechanism,
contrast)` only. The cap is no longer a single fixed 8/9 branch; it
resolves dynamically in `plan_carousel()`: `effective_cap = MAX_SLOTS
(8) + 1 if proof present + 1 if quote present` — 8 baseline, 9 for
either alone, 10 for both. Verified against four scenarios:
- No numbers, no quotes → 8 slides, neither proof nor quote, concept/contrast intact
- Numbers only → 9 slides, proof added, nothing else dropped
- Both numbers and quotes → 10 slides, both proof and quote added, nothing else dropped
- Quotes only, no numbers → did NOT produce a quote slot as might be
  assumed from the label alone — this task's scope was the cap/drop
  logic only, not the quote slot's firing condition. `quote` still
  requires `dominant_numbers` non-empty AND `available_quotes`
  non-empty simultaneously (Decision #55's deliberate, narrower-than-
  proof condition, left untouched) — a quote-only card with zero
  dominant_numbers produces 8 slides with neither, identical to the
  no-numbers-no-quotes case. Flagged, not silently changed.
**Why:** Proof and quote are evidence slots — they exist only because
the card has genuine data to show. Dropping evidence to preserve a
fixed structural slot budget was backwards; the cap should expand to
serve content that's actually present, not constrain it down to fit an
arbitrary count. `concept`/`mechanism`/`contrast` remain droppable
because they're structural/interpretive additions, not evidence.
**Status:** Active.

---

## #61 — Quote slot fires independently of dominant numbers

**Date:** 2026-07-08
**Why they were originally clubbed:** Decision #55 required BOTH
`dominant_numbers` AND `available_quotes` non-empty before `quote`
would fire. The reasoning at the time was that quote was conceived as
paired with proof — a number-plus-quote combination slide, treated as
a variant of "the card has hard evidence" rather than a slot in its
own right.
**Why this was wrong:** A strong sourced quote is standalone evidence
on its own merits — a named speaker saying something sharp doesn't
need a number sitting next to it to justify a slide. The
anti-fabrication guard (Decision #56) already does the real work of
keeping weak or unsourced quotes out of `available_quotes` in the
first place, so gating `quote` on `dominant_numbers` too was a second,
redundant guard — one that actively hurt content quality by burying
genuinely strong quotes back into body prose on cards that had a great
quote but no notable number.
**Fix:** `carousel/planner.py`'s quote condition changed from
`len(context.dominant_numbers) > 0 and len(context.available_quotes) > 0`
to `len(context.available_quotes) > 0` — one line. Proof and quote are
now fully independent; `effective_cap` (Decision #60) already handles
the dynamic 8/9/9/10 cap correctly with no further changes needed.
Verified all four scenarios:
- No numbers, no quotes → 8 slides, neither proof nor quote
- Numbers only → 9 slides, proof present, no quote
- Quotes only, no numbers → 9 slides, quote present, no proof
- Both → 10 slides, proof and quote both present
**Status:** Active.

---

## #62 — DROP_PRIORITY reordered — concept protected above mechanism and contrast

**Date:** 2026-07-08
**Why:** Concept is the educational backbone of AI&Tech and Finance
cards — it's the slot that explains open-weight models, MoE
architecture, Apache 2.0 licensing, yield curves, and similar concepts
the reader needs before the rest of the card lands. Dropping it first
loses the explanatory layer that makes content valuable to a
technically-literate audience, which is exactly the audience Decision
#58's domain-specific hook-grade work was written for. Mechanism is
the most replaceable of the three: its content (the "because"/"this is
why" causal explanation) frequently already gets covered inside
concept's own explanation when both would otherwise fire. Contrast is
structural rather than explanatory — payoff already covers similar
ground (the resolution/consequence) if a contrast beat has to go.
**Fix:** `carousel/planner.py`'s `DROP_PRIORITY` reordered from
`(concept, mechanism, contrast)` to `(mechanism, contrast, concept)` —
mechanism drops first, then contrast, concept last (most protected).
`proof` and `quote` remain absent from `DROP_PRIORITY` entirely
(Decision #60, confirmed still in place).
**Status:** Active.

---

## #63 — Regenerate-gap fix for quote slot (Model B)

**Date:** 2026-07-08
**The gap:** `regenerate_slide()` (Model B — targeted single-slide
regenerate) never passed `Slide.quote` through when rebuilding a
quote-role slide, and never validated the result. A targeted
regenerate of the quote slide silently reset `Slide.quote` to null —
the same class of bug as Decision #54's cover/kicker gap, just for the
quote slot instead.
**The fix:** Same pattern as Decision #54. `regenerate_slide()` now:
passes the slide's existing `Slide.quote` (text/attribution/role)
through as `current quote:` context in the user message when
`target.role == SlotRole.quote`, mirroring the existing `current
kicker:` line; raises `CarouselWriteError` if the regenerated slide
comes back with `quote: null` on a quote-role slide (same validation
pattern as the kicker-None guard), feeding the existing one-retry
mechanism rather than crashing hard; and re-validates the returned
quote's attribution with the existing `_quote_attribution_matches_card()`
helper (Decision #56) before accepting it.
**Anti-fabrication note:** `regenerate_slide()` has no access to the
full `StoryContext` — only `CarouselSpec` is available at the UI call
site (`ui/carousel_view.py`, untouched). So the anti-fabrication check
validates the regenerated quote's attribution against the slide's own
existing `target.quote` — the only real, already-validated quote
available here, itself already having passed the Decision #56 guard
when the carousel was first generated — rather than against a fresh
`available_quotes` list. If `target.quote` is also `None` (the slide
was already broken by this exact bug before the fix), there is nothing
real to validate against and the regenerate fails validation rather
than accepting an unverifiable quote.
**New prompt:** `carousel/prompts/regenerate_v1_2.md` created (copy of
`regenerate_v1_1.md`, which is untouched — Decision #08). Adds a
"Quote sub-rule" section mirroring `writer_v1_5.md`'s `## quote` guide:
attribution/role must match the given current quote exactly (they are
facts, not something a regenerate can change); text may be tightened
for punch but must stay a faithful rendering, never a paraphrase into
a different meaning; quote must never be null; and — unlike the main
writer's quote guide — there is no Statement-slide fallback here,
since a quote-role slide's `role` field is fixed by `regenerate_slide()`
and can't switch roles mid-regenerate. `carousel/writer.py`:
`REGEN_PROMPT_PATH` → `regenerate_v1_2.md`, default `prompt_version`
→ `"regenerate-v1.2"`.
**Verified:** ran `regenerate_slide()` against a synthetic quote-role
slide with a real quote (Shunyu Yao / Tencent) — the returned
`Slide.quote` preserved the exact attribution and role, confirming the
gap no longer resets the field to null.
**Status:** Active.

---

## #64 — New cover format promoted to production: AI image, punchy one-line headline + sub-heading

**Date:** 2026-07-09
**Decision:** The image-forward cover format iteratively built and
validated in `tests/carousel/test_new_cover.py` / `test_new_cover.html`
this session (real Supabase cards, real Sonnet/Haiku/gpt-image-1 calls,
several rounds of user-approved visual/copy tuning) is promoted to the
live pipeline — including real AI image generation, per explicit user
confirmation, not just the layout/copy changes.

**What changed:**
- `carousel/prompts/writer_v1_7.md` (new — `writer_v1_5.md` untouched,
  Decision #08): the old 4-pattern Hook Taxonomy (two of whose patterns
  were literally two-sentence structures) replaced by Hook Rules — one
  line, ≤8 words, names the specific subject, states the surprise
  directly, no colon/two-sentence, plus a new Sub-Heading Rules section
  (one sentence, ≤15 words, completes not repeats). Kicker removed from
  the hook slot entirely. `carousel/writer.py`'s `PROMPT_PATH` →
  `writer_v1_7.md`, default `prompt_version` → `"writer-v1.7"`.
- `carousel/prompts/regenerate_v1_3.md` (new — `regenerate_v1_2.md`
  untouched): "Cover-copy sub-rule" updated to match — 2-piece output,
  no kicker. `REGEN_PROMPT_PATH` → `regenerate_v1_3.md`, default
  `prompt_version` → `"regenerate-v1.3"`.
- `carousel/image_generator.py` (new): `generate_cover_image()` —
  `gpt-image-1` (`quality="high"`, bounded `timeout=45.0`) + duotone
  treatment (brand shadow → domain accent, with a gamma-0.7 brightness
  lift validated during the test phase), saves to
  `outputs/cover_images/{uuid}.png`, returns an `ImageAsset` or `None`.
  Never raises — a failure just leaves the cover typography-only,
  matching the Decision #54/#56/#63 "never crash on a soft dependency"
  philosophy. `write_carousel()` calls this internally, after the
  Sonnet call succeeds, attaching the result to the hook slide before
  returning — `ui/app.py`'s call site needed zero changes.
- `carousel/context_builder.py`: new `_derive_visual_subject()` Haiku
  call — a "documentary filmmaker" framing that identifies the concrete,
  story-specific visual subject (e.g. "a Ukrainian drone approaching a
  Russian oil refinery," not just "Ukraine") for the DALL-E prompt.
  Deliberately a separate call from the existing entity/quote/number
  extraction (Decisions #07/#56/#59), not folded into it — that
  extraction has survived three tuning rounds and mixing in a
  differently-shaped new output risked regressing it. `StoryContext`
  gains `visual_subject`/`visual_subject_is_person` (`carousel/models.py`).
- `carousel/templates/cover.html` rebuilt: full-bleed AI image (`file://`
  URI, never inline base64), gradient overlay, content fixed at 60% down
  (replacing the `--content-top`/`--content-bottom` band technique),
  180px headline (unchanged size), 60px sub-heading, 48px swipe styled
  like the domain tag and moved into normal flow below the sub-heading
  (was crowding a fixed `top:1804px` position against longer
  sub-heading text), new top-right `@anchordelta` handle replacing the
  old bottom-right wordmark. Sub-heading kept inside a
  `{% if sub_heading %}` guard — the one deliberate difference from the
  test template — since `ui/carousel_view.py`'s inline-edit path can
  blank the body text with no validation, and only a template-level
  guard covers that path.
- `carousel/writer.py`'s `regenerate_slide()`: preserves the hook
  slide's `image_asset` unchanged across a text-only regenerate (same
  pattern as kicker/quote preservation in Decisions #54/#63); the old
  kicker-null guard replaced with a stronger one — raises
  `CarouselWriteError` if a hook regenerate returns an empty
  sub-heading, since it's now load-bearing narrative content, not
  decoration.
- Two bugs caught by a Plan-agent review before implementation, both
  resolved by construction rather than patched after the fact:
  (1) render-cache staleness — `carousel/cache.py`'s
  `render_cache_key()` gained an `image_key` param, hashed in by
  `renderer.py`'s `_cache_key()`, so two generations with identical
  (now word-capped, more repeat-prone) headline/sub_heading text but a
  different AI image no longer silently reuse a stale cached PNG;
  (2) Supabase JSONB bloat — `ImageAsset.url` is a local file path, not
  an inline base64 blob, so the persisted `CarouselSpec` stays small
  (confirmed: 6.4KB for a real 9-slide carousel) with no changes needed
  to `carousel/assembler.py` or `db/carousel_queries.py`.
- `BRAND_VERSION` (`carousel/renderer.py`) `"1.9"` → `"2.0"` — a
  structural template overhaul, not an incremental CSS tweak.
**Why:** Every visual and copy decision was independently validated in
isolation against real cards over several rounds this session before
being asked to promote; the two-sentence/colon-twist headline patterns
and the missing sub-heading were named, concrete readability problems
(`spec.md`, "Cover Slide Overhaul — Phase A"), and the generic
entity-label DALL-E prompting produced stereotyped imagery unrelated to
the specific story — all three fixed and confirmed working before this
promotion.
**Explicitly out of scope:** `regenerate_slide()` (Model B) does not
gain image-regeneration capability — text-only, image always preserved.
**Verified end-to-end** against a real Supabase card through the exact
production call sequence (`build_context` → `plan_carousel` →
`write_carousel` → `pick_layouts` → `render_carousel` →
`assemble_carousel`): `visual_subject` populated correctly;
`write_carousel()`'s image-generation call hit a real OpenAI billing
hard limit (from this session's cumulative test image generations, not
a code defect) and correctly caught it, logged a warning, left
`image_asset=None`, and the carousel still generated and rendered all
9 slides cleanly with a typography-only cover — a genuine, unplanned
real-world confirmation that the fallback path works, not just a
simulated one. Separately confirmed: the render-cache fix produces
distinct keys for identical text with different/absent images; the
image-generation module itself (`generate_cover_image()`) succeeds in
isolation, producing a real duotoned image file; the rebuilt
`cover.html` renders correctly end-to-end via Playwright with a real
generated image (domain tag, handle, headline with emphasis word, rule,
sub-heading, swipe all correct); `regenerate_slide()` preserves
`image_asset` unchanged on a hook regenerate and correctly raises
(feeding the existing one-retry mechanism) when the model returns an
empty sub-heading. `git status` confirms changes confined to the files
listed above — no other template, and no production file outside this
list, touched.
**Status:** Active.

---

## #65 — Strip narrative dates from body prose

**Date:** 2026-07-09
**Decision:** The writer stops writing "On July 7..." / "Last
Tuesday..." style datelines into setup/pivot/mechanism/concept/
contrast/payoff body prose. If timing matters, it's framed relatively
("just", "this week", "last month", "days after"), never as a bare
calendar date. `carousel/prompts/writer_v1_8.md` (new — `writer_v1_7.md`
untouched, Decision #08): a new "No narrative dates" Brand Voice
sub-rule, plus a one-line summary added to Hard Constraints > Structural
rules. `carousel/writer.py`'s `PROMPT_PATH` → `writer_v1_8.md`, default
`prompt_version` → `"writer-v1.8"`. Extended to the targeted-regenerate
path (Model B) so a single-slide regenerate can't reintroduce a
narrative date the full writer would now avoid:
`carousel/prompts/regenerate_v1_4.md` (new — `regenerate_v1_3.md`
untouched), same rule plus the same event-slot exception added to its
brand-voice summary list. `REGEN_PROMPT_PATH` → `regenerate_v1_4.md`,
default `prompt_version` → `"regenerate-v1.4"`.
**Why:** A specific calendar date reads like a dateline, not a story —
and it drops out of a reader's head the moment they screenshot or
reshare a slide days or weeks later. Relative framing stays legible
regardless of when the post is actually seen.
**Scope note — event slot is the deliberate exception:** the event
slot's `## event` guide already instructs a real "Month Day, Year"
date, because `carousel/renderer.py`'s `_extract_date_label()` parses
one out of `slide.body` (never `slide.headline`) to populate the
timeline template's separate date-tag element. This rule explicitly
carves that slot out.
**Bug found and fixed while verifying this change:** the pre-existing
`## event` guide's "≤10 words headline + date label" phrasing was
genuinely ambiguous about *where* the date should go, and a live test
run against a real card (Space Force / Victus Haze) proved it out —
the model wrote the date into the headline ("...— July 3, 2026")
instead of body. Since `_extract_date_label()` only ever reads body,
`date_label` would have rendered empty on that timeline slide — a
latent bug that predates this decision, now surfaced and fixed by
rewording the event guide to state unambiguously that the date belongs
in body, mid-sentence, never as a headline suffix or a leading dateline
opener (which would have contradicted the new no-narrative-dates rule
this same decision adds).
**Verified end-to-end** against a real Supabase card
(9783c332-aedf-4b05-8311-e41694845225, Space Force/Victus Haze, 9
slides): setup/pivot/contrast/payoff bodies confirmed free of narrative
dates, with pivot and payoff naturally using "just" for relative timing
exactly as the rule intends; event slide re-verified after the fix —
date now lands in body and `_extract_date_label()` correctly extracts
it. `regenerate_slide()` separately verified on the setup slot with an
instruction explicitly nudging toward a date mention ("mention when
the Space Force was created") — result used "launched in 2019" (a bare
founding year, not a narrative dateline), confirming the rule holds
under the regenerate path too.
**Status:** Active.

---

## #66 — Introduce non-obvious entities on first mention, anchor on repeat

**Date:** 2026-07-09
**Decision:** The writer gives every non-obvious entity (company, agency,
strategist, startup, private equity firm, named analyst) a one-phrase
identifier the first time it's named — not a full explanation, just
enough to orient the reader instantly. Every mention after that gets a
short anchor back to who they are ("the strategist", "the startup") —
never a bare surname or acronym floating with no context several slides
later. Household names (Google, Apple, NATO, Russia) need no
introduction. `carousel/prompts/writer_v1_9.md` (new — `writer_v1_8.md`
untouched, Decision #08): new "Introduce non-obvious entities" Brand
Voice sub-rule, plus a Hard Constraints summary line.
`carousel/writer.py`'s `PROMPT_PATH` → `writer_v1_9.md`, default
`prompt_version` → `"writer-v1.9"`.
**Why:** Surfaced directly from user review of the flowing-narrative
mockups (see `carousel_narrative_mockups.md`) — "Rheinmetall builds
tanks. That's now a problem." gives a non-expert reader zero context
(a country? a program? a person?), and a strategist introduced by name
and title on slide 5 reads as a bare surname by slide 7, several beats
after the reader would have forgotten who they are. The account's whole
value proposition is intelligence and specificity delivered to a
non-expert audience — an unintroduced or un-anchored name breaks that
exact promise mid-carousel.
**Verified end-to-end** against a real Supabase card (the Canada
submarine deal / finance card): the event slide correctly introduced
both "TKMS, a German-Norwegian defence consortium" and "Hanwha Ocean,
South Korea's leading shipbuilder" on first mention, unprompted.
**Status:** Active.

---

## #67 — Narrative-driven pipeline: writer decides shape, planner validates it after the fact

**Date:** 2026-07-09
**Decision:** Inverted the pipeline's core discipline. Before this
decision, `carousel/planner.py` decided slide count and role
deterministically in Python *before* the writer ran (Decision #03/#13 —
"the LLM never decides slide count or structure"), via keyword-matching
against the transmission's nodes, and the writer filled exactly that
pre-built slot plan. As of this decision, the writer reads the full
`StoryContext` itself and decides the carousel's own narrative shape —
how many beats it needs, where a quote or a number earns its own slide —
and `planner.py` validates the result afterward instead of dictating it
beforehand.

`SlotRole` gains a 12th member, `beat` — a generic flowing-narrative
story beat. The 7 structural roles it replaces (setup, event, pivot,
mechanism, concept, proof, contrast) are retired from new generations
but kept on the enum unchanged, since old persisted `CarouselSpec` rows
in Supabase still use those exact string values and Pydantic's strict
enum validation would fail to deserialize them otherwise. `hook`,
`quote`, and `cta` remain in active use exactly as before.

`carousel/planner.py` is fully rewritten: `plan_carousel()` and its
keyword-matching/`DROP_PRIORITY`/`SLOT_ORDER` machinery are removed,
replaced by `validate_carousel_shape(spec)` — a deterministic
post-write check (same "deterministic Python judgment, not LLM
self-verification" philosophy as the Decision #56 quote-fabrication
guard) enforcing: first slide is `hook`, last is `cta`, total count is
5–10 (5 is the user's stated minimum — no padding; 10 is Instagram's
actual platform limit on carousel media items, not an arbitrary
number), at most 2 dedicated `quote`-role slides, and zero slides with
populated `dominant_numbers` (hard-blocking the retired proof/fact-sheet
slot as code, not just a prompt instruction).

New prompt `carousel/prompts/writer_v2_0.md` (`writer_v1_9.md`
untouched, Decision #08) — version jump to 2.0, not 1.10, matching the
Decision #64 precedent for a structurally different prompt. Brand
Voice, Hook Rules, Domain Vocabularies, and Caption/Pinned
Comment/Hashtag rules carry over unchanged. The old 11-section
`# Slot-Role Writing Guides` is replaced by one `# Story Arc & Beat
Writing Guide`: the writer reads the transmission's nodes as a natural
but non-binding map, finds the story's actual shape, writes each beat's
headline+body as one continuous thought that answers the previous
beat's question and raises the next one, lands numbers inline in the
sentence that needs them, and defaults quotes to inline prose unless
one is strong enough to stand alone as its own beat. Word budget for
`beat`: ≤14 words headline, ≤40 words body (widened from the old
25-word cap — a beat carrying an inline number or quote clause needs
more room than an isolated statement did).

`carousel/writer.py`: `PROMPT_PATH` → `writer_v2_0.md`, default
`prompt_version` → `"writer-v2.0"`. `write_carousel()` drops its
`slot_plan` parameter — `_build_user_message()` no longer builds a
`SLOT PLAN` section. `_build_spec_from_response()` now calls
`planner.validate_carousel_shape(spec)` alongside the existing
quote-fabrication check, feeding the same one-retry mechanism on
failure. `regenerate_slide()` and `_attach_cover_image()` needed no
logic changes — both already worked generically via `SlotRole.hook`/
`SlotRole.quote` checks that remain valid for `beat`-role slides.

`ui/app.py`'s carousel-generation call site drops the
`plan_carousel(context)` call and the `plan` argument to
`write_carousel()` — the one call site that could not stay untouched,
since the whole point is inverting who decides structure.

No template, `layout_picker.py`, `assembler.py`, or `ui/carousel_view.py`
changes were needed: `layout_picker.py`'s existing content-signal
fallthrough (`cta`→cta, `hook`→cover, has quote→quote, else→statement)
already routes a `beat`-role slide with no quote straight to
`statement.html`, which already serves as a generic flowing-prose
template. `ui/carousel_view.py`'s `ROLE_ABBREV` already falls back
gracefully for an unrecognized role string.
**Why:** Viewer feedback was that carousels built from a fixed slot
structure read as disconnected facts, not a story — each slide standing
alone, numbers and quotes parked on isolated slides instead of landing
where they matter. `carousel_narrative_mockups.md` (the hand-written
mockup exercise validated against explicit user feedback on entity
introduction, name-anchoring, and regional-angle compression) proved
the target shape works; this decision makes the real pipeline produce
that shape directly instead of leaving the mockups a one-off exercise.
The user explicitly chose to relax Decision #03/#13's original
determinism guarantee in exchange for a carousel that actually flows,
on the condition that a deterministic safety net still validates the
result rather than trusting the LLM to self-certify its own shape.
**Note:** the user referred to this as "Decision #65" when requesting
it, but #65 and #66 were already taken by the narrative-dates and
entity-introduction decisions earlier in this same session — using the
correct next number here rather than silently renumbering or creating
a conflicting duplicate #65.
**Status:** Active — pending end-to-end verification against a real
Supabase card (in progress).

---

## #68 — Beat body word budget tightened and actually enforced; body text left-aligned

**Date:** 2026-07-09
**Decision:** A real carousel generated from Streamlit (world domain,
"crypto goes mainstream," carousel id `7bda4152-c493-4654-b43c-9e92a3b4c7e4`)
surfaced two compounding problems: every beat body ran 48-56 words
against `writer_v2_0.md`'s stated ≤40-word cap — a cap that was never
actually checked anywhere in code — and `statement.html` rendered that
long body as a single centre-aligned block with no paragraph structure,
producing 9-11 line walls of text on every interior slide.

Two fixes, kept independent of Decision #67's "one continuous thought,
not a bulleted list" narrative style (deliberately not adopting the
literal bulleted/segmented block format from the viewer feedback that
prompted this — that would partially reverse #67, not just restyle it):

1. **Word budget tightened 40 → 30 words per beat body, and enforced.**
   `carousel/planner.py`'s `validate_carousel_shape()` gained per-role
   word-count checks (`MAX_HOOK_HEADLINE_WORDS`=8, `MAX_HOOK_BODY_WORDS`=15,
   `MAX_BEAT_HEADLINE_WORDS`=14, `MAX_BEAT_BODY_WORDS`=30), feeding the
   same one-retry mechanism as the existing shape/quote-fabrication
   guards — "stated in the prompt, enforced in code," same pattern as
   everything else in that file. `writer_v2_0.md`'s Shape section, Hard
   Constraints word-limits table, and "On malformed output" checklist
   updated to match.
2. **`statement.html`'s `.body-text` left-aligned** with a modest
   `max-width: 1100px` inset (narrower than the headline's 1250px
   measure) and `line-height` 1.65 → 1.75. Headline stays centred
   (unaffected — inherits `.content`'s `text-align: center`). Verified
   the real 51-word beat_1 body from the crypto carousel through the
   new CSS (still readable, clearly improved), then verified a
   budget-compliant ~34-word version of the same content: 6 lines
   instead of 9, flush-left edge, real whitespace at the bottom.
**Why:** Direct viewer feedback on a real generated carousel: dense
centre-aligned paragraphs read as "homework" and force the eye to
hunt for each new line's start. Investigating the claim against the
actual rendered slides found the real driver was the un-enforced word
budget (25-40% over spec on every beat), not primarily alignment —
alignment was a secondary but genuine readability win on top of it.
Deliberately did not adopt the feedback's literal bulleted-list
proposal, since Decision #67 was validated against
`carousel_narrative_mockups.md` specifically to move away from a
list-of-facts read.
**Status:** Active.

---

## #69 — Quote fabrication guard degrades gracefully instead of failing the whole carousel

**Date:** 2026-07-10
**Decision:** A real generation (ai_tech card `6a5f1a8f-c307-4594-882a-ea93b78657a7`,
"Claude's Hidden Mind") hard-failed twice in a row: the card's one sourced
quote has a malformed `attribution` field — a full citation string
("Anthropic's 16-author research paper, 'Verbalizable Representations
Form a Global Workspace in Language Models' (Research team)") rather
than a person's name, because the source has no individual human
speaker. The writer tried "Anthropic Research Team," then "Anthropic
research paper" as shortened attributions; the Decision #56
anti-fabrication guard correctly rejected both (neither is a substring
of the real citation string), but after the one retry the entire
carousel generation raised `CarouselWriteError` and failed outright.

Three changes, none weakening the anti-fabrication guard itself —
attribution still must match verbatim, never approximately:

1. **`carousel/writer.py`** — `_build_spec_from_response()` gains a
   `strict_quotes: bool` parameter. `True` (first attempt) behaves as
   before, raising a new `QuoteFabricationError(CarouselWriteError)`.
   `False` (the retry) drops the offending slide instead of raising —
   logged as a warning, not surfaced as an error. `write_carousel()`
   passes `strict_quotes=True` on the first call, `False` on the retry,
   so a fabricated quote gets one chance to self-correct and then is
   silently dropped rather than failing the whole generation. Same
   "degrade gracefully, never hard-fail on a soft dependency" pattern
   already used for cover-image generation (Decision #64).
2. **Sharper retry message** — when the first failure is specifically a
   `QuoteFabricationError`, the retry prompt now explicitly says to
   drop the quote beat entirely rather than trying another attribution.
   Previously the retry just echoed the raw validation error back with
   a generic "fix it," which is why the second attempt made the same
   mistake in a different way.
3. **`writer_v2_0.md`** — restored an explicit "no forced quote"
   fallback that existed in `writer_v1_9.md` but was dropped when the
   Story Arc & Beat Writing Guide replaced the old per-slot guides for
   Decision #67. Also hardened the verbatim-attribution instruction:
   copy the attribution character-for-character, never shorten or
   clean it up for a better-looking slide headline — a felt need to
   shorten it is itself the signal that quote shouldn't be a dedicated
   beat at all.
**Why:** The guard did exactly what Decision #56 designed it to do —
refuse a fabricated attribution. The bug was the *recovery* path: a
card can have a genuinely strong, quote-worthy finding attached to
metadata that just isn't a clean person-name (an anonymous paper, a
press release, an institutional statement), and the old behavior threw
the whole carousel away rather than the one slide that didn't work.
Since Decision #67 already made quote beats optional narrative garnish
rather than a required slot, failing generation entirely over one
was inconsistent with that architecture — confirmed by comparing
against a same-session card (Australia/India nuclear deal) that
generated successfully with zero quote beats, because the model
correctly judged nothing available was quote-worthy there. Same
system, two different card data shapes — one degrades gracefully by
design (no quote), the other should too (bad-metadata quote).
**Status:** Active.

---

## #70 — Split overloaded beats instead of cutting content; word budget is a readability constraint, not a content ceiling

**Date:** 2026-07-10
**Decision:** Tracing why the Albanese quote (Australia/India uranium
card, `13eb60e5-cfa9-434e-a4be-17adb2be73bd`) disappeared across
regenerations found it wasn't dropped by extraction or judged
unimportant by the writer — it was cut to fit the Decision #68
word budget, because `writer_v2_0.md` had no instruction telling the
model that splitting an overloaded beat into two was even an option.
The only guidance pointed toward compression ("fold into a neighbour
or cut"), and — worse — a leftover line in the `## Shape` section
still explicitly said "cut a supporting clause before you cut the
number or the quote," directly contradicting the fix once added.
Separately, the same word-budget guard was still hard-failing
generations outright on a near-miss (`beat_2` at 34, then 35 words on
retry — got worse, not better), because the retry message just echoed
the raw error back with no specific instruction.

Three changes:
1. **`carousel/planner.py`** — new `WordBudgetExceededError
   (PlannerValidationError)`, structured the same way as Decision
   #69's `QuoteFabricationError`, replacing the four generic
   `PlannerValidationError` raises for hook/beat headline/body checks.
2. **`carousel/writer.py`** — `write_carousel()`'s retry logic detects
   `WordBudgetExceededError` specifically and appends a targeted hint:
   split the overloaded beat into two, preserving every piece of
   content, instead of trying to trim further.
3. **`writer_v2_0.md`** — new `## The essence` section opens the Story
   Arc & Beat Writing Guide: the carousel must be both concise/
   well-paced AND carry everything genuinely good from the source
   material — neither goal ever trades against the other; when they
   seem to conflict, the fix is to give content the space it needs
   (more slides), never to cut it. 10 slides is a hard ceiling
   (Instagram's platform limit), explicitly not a target — most
   readers' attention holds through ~7, but the ceiling is set higher
   specifically so real content is never forced out just to stay
   short. New `## Splitting an overloaded beat` section gives the
   concrete mechanic (split, don't cut) with a worked example. The
   contradictory `## Shape` line was rewritten: the 30-word budget is
   now explicitly framed as a single-slide readability constraint,
   not a content ceiling — hitting it is the signal to split, not to
   delete the quote/number/idea that made the beat worth writing.
**Why:** User's framing, direct: the word budget exists "for ease of
reading so there is more white space," never as license to drop good
content. A carousel that's easy to read but has quietly cut real
substance to hit a number has failed exactly as much as one that's
complete but exhausting to read — visual polish and content richness
must marry into one carousel, not trade off against each other. The
writer needs to actually understand this intent and write with real
judgment, not pattern-match a word-count rule.
**Verified:** re-ran the real Australia/India card after the
`WordBudgetExceededError` + retry-hint fix (before the essence
rewrite) — generation succeeded without hard-failing, though that run
still didn't preserve the quote (a valid creative call the model made
without hitting an overload situation, not a bug) — which is what
motivated writing the essence section explicitly rather than relying
on implicit prompt inference.
**Status:** Active.

---

## #71 — Cover images were too dark to read; softened prompt darkness language and strengthened duotone gamma

**Date:** 2026-07-10
**Decision:** Real generated cover images (checked directly against saved
files in `outputs/cover_images/`, not just described) were reading as
near-featureless dark voids — a uranium-ore rock and its treaty
document, and a mining excavator, were both barely legible even
zoomed in. Root cause traced through the actual pipeline, not
guessed: `image_generator.py`'s prompt templates stacked 4-5 redundant
darkness/contrast descriptors ("dark near-black... extreme dramatic
chiaroscuro... ultra high contrast... dramatic shadows") with nothing
telling the model to keep the *subject itself* legible, so
`gpt-image-1`'s raw output was genuinely low-luminance across most of
the frame before any post-processing touched it. `apply_duotone()`'s
`gamma=0.7` brightening pass wasn't strong enough to counteract that —
most pixels stayed on the dark half of the shadow (`#1A1612`) →
accent-colour gradient, which is also why the accent colour barely
showed up in either broken image.

Two changes, both in `carousel/image_generator.py`:
1. Both prompt templates (person and non-person) rewritten: darkness
   descriptors collapsed from 4-5 redundant ones down to a single
   "moody {domain_tone} background" cue, explicit new instruction that
   the subject itself must be "clearly lit and easy to make out" /
   "easy to identify," and "extreme/ultra/dramatic" contrast language
   replaced with "strong but readable contrast."
2. New `DUOTONE_GAMMA = 0.55` constant (was hardcoded default `0.7` on
   `apply_duotone()`), passed explicitly at the call site so it's
   independently tunable from the function's own general-purpose
   default.
**Verified:** three real test generations after the fix — the same
uranium-ore and excavator subjects (for direct before/after
comparison) plus a new person-portrait test on the finance domain
(untested before this) — all fully legible, on-brand moody tone
preserved, and for the first time the domain accent colour (silver-
blue) is actually visible rather than swallowed by near-black.
**Why:** User couldn't tell what several generated cover images
actually depicted. Confirmed by inspecting the actual saved PNGs
before proposing any fix, not by theorizing from the prompt text
alone — the CSS gradient overlay in `cover.html` (a separate,
downstream darkening layer for text legibility) was ruled out as the
cause, since the raw duotoned images were already unreadable before
that overlay is even applied.
**Status:** Active.

---

## #72 — Quote template attribution and quote text were too small/cramped to read

**Date:** 2026-07-10
**Decision:** User feedback on a real rendered quote slide: the
attribution name and role line below the quote were "very small,
viewer have to get phone closer to read it," and the quote text
itself read cramped, particularly because it's bold italic. Checked
the actual numbers before changing anything: the attribution name
(16px final render size) was smaller than the footer page-indicator
chrome text (18px) — a person's name was less prominent than page
furniture. The quote text's `-0.5px` letter-spacing was actively
tightening already-dense bold italic strokes, and `line-height: 1.2`
left too little room between wrapped lines.

`carousel/templates/quote.html` changes (all sizes at 2x render
resolution; final is half):
- `.attribution` (name): `32px → 48px`, `letter-spacing 2px → 3px`,
  `margin-bottom 8px → 16px`.
- `.quote-role` (designation): `28px → 38px`, `letter-spacing
  1px → 1.5px`.
- `.quote-text`: `letter-spacing -0.5px → 0px`, `line-height
  1.2 → 1.35`, `font-size 100px → 108px`.
- `.content --measure`: `1300px → 1400px` — wider column so lines
  flex out before wrapping instead of breaking early.
**Why:** A dedicated quote slide has no competing content fighting
for space, unlike a beat (word-budget constrained per Decision #68)
— there was room to let both the quote text and its attribution
breathe, and nothing about the cramped look was serving a design
purpose.
**Verified:** re-rendered a real quote slide (the Vina Nadjibulla /
TKMS quote used earlier this session) against the new CSS — name and
role both clearly legible, quote text no longer crowds itself.
**Status:** Active.

---

## #73 — Footer wordmark and page indicator were nearly invisible from slide 2 onwards

**Date:** 2026-07-10
**Decision:** User feedback: the "ANCHOR & DELTA" brand mark in the
bottom-right of every interior slide (and the CTA slide) was nearly
invisible, and the page counter ("2 / 7") was too small to read
comfortably. Checked the actual values: both `.page-indicator` and
`.wordmark` in `base.css` used `color: var(--text-footer)` (`#4A4540`)
against the `#1A1612` background — very low contrast — while
`cover.html`'s `.handle` (slide 1's equivalent, top-right) already
used the much brighter `var(--text-muted)` (`#B0A898`) at 48px.

`carousel/templates/base.css`:
- `.page-indicator, .wordmark` shared rule: `color` → `var(--text-muted)`,
  `font-size` `36px → 40px` (2x).
- `.wordmark`-specific override: `font-size` → `48px` (2x, matching
  `.handle` exactly), plus `text-transform: none` — the shared rule's
  `uppercase` would otherwise turn `@anchordelta` into `@ANCHORDELTA`,
  not matching slide 1's lowercase rendering.

`carousel/renderer.py`: `WORDMARK` constant changed from
`"ANCHOR & DELTA"` to `"@anchordelta"` — same text slide 1's handle
already shows. `BRAND_VERSION` `"2.0" → "2.1"` to invalidate the
render cache for this shared-CSS change.

Position deliberately untouched on every template — still governed by
`base.css`'s `.footer` flex layout (page-indicator bottom-left,
wordmark bottom-right), exactly as requested.

One thing verified rather than assumed: `cta.html` has its own local
`.cta-footer` rule with different (also-dim) font-size/color, but
since it targets the ancestor `<footer>` element and not the
`.wordmark` span directly, those properties never actually reached the
span — `.wordmark`'s own explicit declarations (from `base.css`) won
for every property that matters. So the single shared-CSS fix
corrected the CTA slide's footer too, with zero changes to `cta.html`
itself — confirmed by rendering it, not just reasoned about.
**Status:** Active.

---

## Open questions to revisit

- **Anonymous handle name.** Pending account creation.
- **Final accent colour hex values per domain.** Pinned during template-design week.
- **Display font selection.** Pinned during template-design week. Candidates: Space Grotesk (free), Inter Display (free), Founders Grotesk (paid), Pangram Sans (paid for commercial use).
- **Body font selection.** Pinned during template-design week. Candidates: Inter, IBM Plex Sans.
- ~~**Exact sync-to-folder path.**~~ Resolved by Decision #52 —
  configurable `CAROUSEL_SYNC_DIR`, defaults to a Google Drive path.
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
- 2026-07-06: Decision #52 added — "Approve & Sync" now writes into
  per-carousel `YYYY-MM-DD_domain_slug` subfolders under a configurable
  `CAROUSEL_SYNC_DIR`, resolving the "exact sync-to-folder path" open
  question. Blueprint §5.7 and §12.4 updated.
- 2026-07-06: Decision #53 added — new Cover template archetype takes
  over the hook role from the interior-styled Hook template. Writer
  prompt bumped to `writer-v1.1` (new file, `writer_v1_0.md` untouched
  per Decision #08) with a cover-copy sub-rule. `Slide.kicker` added as
  an Optional seam. Blueprint §5.5 and §10 updated.
- 2026-07-06: Decision #54 added — `regenerate_slide()` (Model B) now
  preserves and re-validates `kicker` on hook/cover-slide regenerates.
  New `regenerate_v1_1.md` (`regenerate_v1_0.md` untouched per Decision
  #08) adds the matching cover-copy sub-rule.
- 2026-07-06: Decision #55 added — dedicated `quote` slot in
  `planner.py` (fires only when both a dominant number and a strong
  quote exist; 9-slot cap for that carousel only). Writer bumped to
  `writer-v1.2` (new file, `writer_v1_1.md` untouched) with `## quote`
  and `## proof` slot guides. Number template gets a ghost-number
  treatment; Quote template gets oversized decorative marks, a `role`
  line, and correct emphasis-word rendering.
- 2026-07-07: Decision #56 added — `context_builder.py` now feeds
  `delta_events[*].dialogue` into quote extraction (was never read
  before, so `available_quotes` was always empty). `writer.py` adds a
  deterministic post-generation guard: a quote slide's attribution must
  match a real card speaker or the generation raises and retries,
  never rendering a fabricated quote.
- 2026-07-07: Decision #57 added — Number template rebuilt as a
  multi-figure fact sheet (writer-generated title + up to 4 rows).
  `Slide.dominant_number` renamed to `Slide.dominant_numbers` (list,
  Optional, no migration); `Slide.factsheet_title` added. Writer bumped
  to `writer-v1.3` (new file, `writer_v1_2.md` untouched) selecting up
  to 4 hook-grade figures per card. Verified end-to-end against the
  real Space Force card.
- 2026-07-08: Decision #58 added — writer bumped to `writer-v1.5`
  (new file, `writer_v1_4.md` untouched) with domain-specific
  hook-grade examples for World, Finance, and AI & Tech, so the fact
  sheet's number selection stops applying a World-biased
  visceral-scale bar to Finance and AI&Tech cards.
- 2026-07-08: Decision #59 added — `context_builder.py` now feeds the
  full raw transmission body into number extraction (was truncated to
  6 lines, dropping numbers from nodes 2-4). Same reserved-block
  pattern as Decision #56's dialogue fix. `MAX_EXTRACTION_INPUT_CHARS`
  3000 → 10000, Haiku extraction `max_tokens` 1024 → 4096.
- 2026-07-08: Decision #60 added — `proof`/`quote` removed from
  `planner.py`'s `DROP_PRIORITY`; cap now resolves dynamically
  (8/9/9/10) instead of a fixed 8/9 branch, so evidence slots are
  never sacrificed to make room for structural ones.
- 2026-07-08: Decision #61 added — `planner.py`'s `quote` condition no
  longer requires `dominant_numbers` too; fires on `available_quotes`
  alone. All four cap scenarios (8/9/9/10) now match spec exactly.
- 2026-07-08: Decision #62 added — `planner.py`'s `DROP_PRIORITY`
  reordered to `(mechanism, contrast, concept)`; concept is now the
  most protected structural slot, mechanism the most droppable.
- 2026-07-08: Decision #63 added — regenerate-gap fix for the quote
  slot (Model B), same pattern as Decision #54's kicker fix. New
  `regenerate_v1_2.md` (`regenerate_v1_1.md` untouched); `writer.py`
  passes/validates `Slide.quote` on regenerate instead of losing it.
- 2026-07-09: Decision #64 added — new image-forward cover format
  promoted to production from `tests/carousel/`: AI-generated duotone
  image, punchy one-line headline + completing sub-heading, kicker
  removed. New `writer_v1_7.md`, `regenerate_v1_3.md`,
  `carousel/image_generator.py`. `cover.html` rebuilt.
  `BRAND_VERSION` → `"2.0"`.
- 2026-07-09: Decision #65 added — writer stops writing narrative
  dates ("On July 7...") into body prose; relative framing ("just",
  "this week") instead. New `writer_v1_8.md` (`writer_v1_7.md`
  untouched). Also fixed a latent bug found while verifying: the
  event slot's date was landing in headline, not body, so
  `_extract_date_label()` never found it. Extended to the regenerate
  path: new `regenerate_v1_4.md` (`regenerate_v1_3.md` untouched).
- 2026-07-09: Decision #66 added — non-obvious entities get a one-phrase
  identifier on first mention, a short anchor on every repeat mention.
  New `writer_v1_9.md` (`writer_v1_8.md` untouched). Surfaced from user
  review of `carousel_narrative_mockups.md`.
- 2026-07-09: Decision #67 added — narrative-driven pipeline. Writer
  decides carousel shape itself instead of filling a pre-built slot
  plan; `planner.py` rewritten from `plan_carousel()` to
  `validate_carousel_shape()`, a post-write deterministic check.
  `SlotRole` gains `beat`; 7 structural roles retired from new
  generations, kept on the enum for old Supabase rows. New
  `writer_v2_0.md`. `writer.py` and `ui/app.py` updated to drop
  `slot_plan`.
- 2026-07-09: Decision #68 added — beat body word budget tightened
  40 → 30 words and actually enforced (`validate_carousel_shape()`
  gains per-role word-count checks; real generation had been running
  48-56 words per beat with nothing catching it). `statement.html`
  body text left-aligned with a modest inset, line-height 1.65 → 1.75.
- 2026-07-10: Decision #69 added — quote-fabrication guard degrades
  gracefully instead of hard-failing the whole carousel. New
  `QuoteFabricationError`; `_build_spec_from_response()` gains
  `strict_quotes` (raise-and-retry on first attempt, drop-the-slide on
  retry). Sharper retry message when the failure is quote-specific.
  `writer_v2_0.md` gets back the "no forced quote" fallback dropped
  during the Decision #67 rewrite, plus a verbatim-attribution
  hardening. Also this session: cover-image keyword override at both
  generation entry points, image-controls UI layout fix, and
  `IMAGE_TIMEOUT_SECONDS` 45s → 90s.
- 2026-07-10: Decision #70 added — split overloaded beats instead of
  cutting content. New `WordBudgetExceededError`; retry gets a
  targeted "split, don't trim" hint. `writer_v2_0.md` gains a `## The
  essence` section (content and readability never trade off; 10-slide
  ceiling is deliberately above the ~7-slide attention span so content
  is never forced out) and fixes a real contradiction where `## Shape`
  still said to cut a quote/number to hit the word budget.
- 2026-07-10: Decision #71 added — cover images were too dark to read.
  Prompt darkness descriptors collapsed from 4-5 redundant ones to one
  "moody" cue plus an explicit "subject clearly lit" instruction; new
  `DUOTONE_GAMMA = 0.55` (was hardcoded 0.7). Verified against real
  saved images before and after.
- 2026-07-10: Decision #72 added — quote template attribution/role
  text and quote text itself were too small/cramped. `quote.html`:
  attribution 32px→48px, role 28px→38px, quote-text letter-spacing
  -0.5px→0, line-height 1.2→1.35, size 100px→108px, measure
  1300px→1400px.
- 2026-07-10: Decision #73 added — footer wordmark/page indicator
  nearly invisible from slide 2 onwards (`--text-footer` low contrast).
  `base.css` bumped both to `--text-muted`; wordmark text changed
  "ANCHOR & DELTA" → "@anchordelta" (`renderer.py`) to match slide 1's
  handle exactly, including preserving lowercase. `BRAND_VERSION`
  2.0→2.1. Position unchanged on every template.
