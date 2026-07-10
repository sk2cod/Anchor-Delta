# Anchor & Delta — Instagram Carousel Engine

## Blueprint v1.0

Date frozen: 2026-06-30
Status: Active — kept current through Decision #73. This document
describes the system as actually built today; `CAROUSEL_DECISIONS.md`
holds the historical reasoning behind each change. Where the two
appear to disagree, the decisions log is the record of *why*, this
document is the record of *what currently is*.

---

## 1. Purpose

Convert finalised Story Cards from the existing Intelligence Engine into publish-ready Instagram carousels. 5–10 slide PNGs (story-length-driven, not fixed — Decision #67) + caption + pinned comment + hashtag list per carousel. Solo-use, human-approved, manual-publish in v1.

The Story Card produced by the existing pipeline is treated as a frozen contract. This engine reads cards. It does not modify, augment, or write back to them.

---

## 2. Goals and non-goals

**v1.0 goals (updated to reflect what actually shipped):**

- One-click carousel generation from any Story Card
- Production-grade typographic visual system across three domains (World / Finance / AI & Tech)
- Editor-quality content compression: hook rules, domain vocabularies, narrative-driven writing (Decision #67 — revised from the original "slot-driven planning" goal; see §3)
- AI-generated cover imagery (Decision #64 — pulled forward from the original v1.5 plan, see §14)
- Solo daily use sustainable: targeted regenerate, inline edit, fast caching
- Architecture forward-compatible with a Wikimedia/editorial-photo image source (v1.5/v2), Reels companion (v2), Graph API publish (v2)

**v1.0 non-goals (updated — AI image generation moved from here to a goal, Decision #64):**

- Photographic/illustrated content beyond the current AI-generated cover — no per-beat imagery, no Wikimedia source yet (verified: zero implementation exists)
- Reels, video, or audio output
- Instagram Graph API publishing
- Multi-account, multi-user, or team workflows
- Performance analytics ingestion
- Scheduling or queueing
- LangGraph, agent frameworks, multi-model abstraction

Each non-goal has a defined re-evaluation point in section 13 [now section 14 — Roadmap].

---

## 3. Design philosophy

Five principles. Every component honours all five.

1. **Python owns determinism. LLM owns creativity.** Planning, layout, hashtags, rendering, caption assembly, persistence: Python. Slide text, caption draft, hashtag themes: LLM. No third category.

2. **One LLM creative call per generation.** A single Sonnet call produces all slide text, caption draft, and hashtag themes in one pass for voice consistency. Targeted regenerates are additional calls only when needed. Plus one cheap Haiku call upstream for entity/number/quote extraction.

3. **Narrative-driven generation (revised, Decision #67).** Originally
   this principle was slot-driven: Python decided slide count and role
   before the writer ran, and the model only filled a pre-built
   structure — deliberately, to eliminate "wrong shape" failures. Real
   viewer feedback showed the cost of that guarantee: carousels built
   from a fixed slot structure read as disconnected facts, not a
   story, because numbers and quotes got parked on isolated slides
   instead of landing where they mattered. The guarantee was
   deliberately relaxed: the writer now reads the full `StoryContext`
   itself and decides the story's own shape — how many beats it needs,
   where a quote or number earns its own slide. `CarouselPlanner`'s
   role inverted to match: instead of deciding structure before
   writing, it validates the writer's chosen structure *after* writing
   (`validate_carousel_shape()`) — same "deterministic Python
   judgment, not LLM self-verification" discipline, just applied to
   shape after the fact rather than dictating it beforehand.

4. **Cache by content hash. Aggressively.** Three cache layers. Re-render after a text edit is free. Re-render after a template tweak is free for unchanged slides. This is the property that makes daily solo use sustainable.

5. **Architecture stays legible at 50,000 lines.** Seven pipeline stages, one responsibility each, Pydantic contracts at every boundary, no shared mutable state. Adding features means adding to stages, not restructuring them.

---

## 4. System overview

Seven sequential stages. Each stage takes a typed Pydantic input and returns a typed Pydantic output. There are no dicts passed between stages.
`CarouselPlanner` moved from stage 3 to stage 5 as of Decision #67 — it
now validates the writer's output instead of deciding structure before
the writer runs.

```
StoryCard (Supabase)
       │
       ▼
[1] CardLoader              Python      ~50 ms
       │
       ▼
[2] ContextBuilder          Python + 1 Haiku call    ~1.5 s
       │
       ▼
[3] CarouselWriter          1 Sonnet call + 1 gpt-image-1 call    ~5-15 s
       │  (decides the carousel's own shape — 5-10 slides, not fixed)
       ▼
[4] CarouselPlanner         Python, post-write validation    <10 ms
       │
       ▼
[5] LayoutPicker            Python      <10 ms
       │
       ▼
[6] SlideRenderer           Python (Playwright)      ~2 s for a typical 7-slide carousel cold
       │
       ▼
[7] PostAssembler           Python      <50 ms
       │
       ▼
Carousel record (Supabase)
       │
       ▼
Streamlit preview → human approval → sync-to-folder
```

Total cold-path latency: ~9-20 seconds for a fresh generation, most of
the range explained by the cover image call (bounded at 90s timeout,
typically much faster) and variable slide count. Warm-path (cache hits): under 1 second.

---

## 5. Component-by-component specification

Each component below is specified with: purpose, inputs, outputs, Python or LLM, why, cacheability, cost, latency. Future-feature seams are marked **[SEAM v1.5]** or **[SEAM v2]**.

### 5.1 CardLoader

**Purpose:** Retrieve a single Story Card from Supabase. Pure database read.

**Input:** `card_id: str`

**Output:** `StoryCard` Pydantic model mirroring the existing `cards`, `delta_events`, `transmissions` schema.

**Python or LLM:** Python.

**Why this exists:** Decouples the carousel engine from the database layer. The rest of the pipeline never touches Supabase directly. Trivially mockable for testing.

**Cache:** Keyed by `(card_id, card.updated_at)`. The card itself is the cache key.

**Cost:** $0. **Latency:** ~50 ms.

---

### 5.2 ContextBuilder

**Purpose:** Transform the full Story Card into a trimmed, prompt-optimised `StoryContext`. Single highest-leverage piece of Python in the entire engine.

**Input:** `StoryCard`

**Output:** `StoryContext` containing:
- `umbrella_title`
- `anchor_text` (full anchor, approximately 150 words)
- `latest_delta` (headline + tldr + event_date)
- `previous_deltas` (maximum 2, headline + tldr only)
- `transmission_summary` (node chain compressed to 4–6 bullets)
- `domain` (literal: `"world"`, `"finance"`, `"ai_tech"`)
- `card_age_days`
- `available_quotes` (extracted by Haiku call: text + attribution + role)
- `key_entities` (extracted by Haiku call: people, companies, agencies, models, products)
- `dominant_numbers` (extracted by Haiku call: value + label + context)

**Python or LLM:** Python orchestration plus one Haiku call for entity/number/quote extraction.

**Why Haiku, not regex:** Locked decision (see CAROUSEL_DECISIONS.md entry #07). Regex catches approximately 70% of entities. Haiku catches approximately 95%. Quality gain justifies the cost.

**Cache:** Keyed by card content hash. Identical card → identical context.

**Cost:** ~$0.005 per generation. **Latency:** ~1.5 seconds.

---

### 5.3 CarouselPlanner (Decision #67 — inverted from pre-write planner to post-write validator)

**Purpose:** Validate the shape of the carousel the writer already
produced. Deterministic Python rules — but applied *after* generation,
not before. There is no more slot deciding, no keyword matching against
the transmission, no drop-priority machinery. The writer reads the full
`StoryContext` and decides count, roles, and where quotes/numbers land
itself; this stage's only job is confirming the result is structurally
sound, and rejecting-and-retrying (via the same mechanism as the
quote-fabrication guard) when it isn't.

**Input:** `CarouselSpec` (the writer's already-generated output)

**Output:** `None` — raises `PlannerValidationError` (or the more
specific `WordBudgetExceededError` subclass, Decision #70) on any
violation; returns silently on success. Called from
`writer.py`'s `_build_spec_from_response()`, feeding the existing
one-retry mechanism.

**Checks performed by `validate_carousel_shape(spec)`:**

| Check | Rule |
|---|---|
| First slide | must have `role == hook` |
| Last slide | must have `role == cta` |
| Slide count | 5–10 total (`MIN_SLIDES`/`MAX_SLIDES`) — 5 is the user-stated minimum (no padding below it), 10 is Instagram's actual platform limit on carousel media items |
| Quote slides | at most 2 dedicated `quote`-role slides (`MAX_QUOTE_SLIDES`) |
| Dominant numbers | **zero** slides may have `dominant_numbers` populated — the retired proof/fact-sheet slot is hard-blocked as code, not just discouraged in the prompt |
| Word budgets | hook headline ≤8 words, hook sub-heading (body) ≤15 words, beat headline ≤14 words, beat body ≤30 words — each with a 10% tolerance (Decision #69/#70's `_max_words()`, e.g. 30→33) so a small near-miss doesn't burn the one retry the way a genuinely broken response should |

**Why the tolerance exists:** a real generation ran a beat body at
33-34 words against the 30-word target on both the first attempt and
the retry — a 10-13% miss, not a broken response. Hard-failing on that
near-miss wasted the retry instead of catching an actual problem.

**Why this still matters:** it's the same discipline the original
slot-deciding design had (avoid "wrong shape" carousels) — just applied
as a safety net after the writer's creative pass instead of a
straitjacket before it.

**Cache:** none — it's a pure function, no caching needed. **Cost:** $0. **Latency:** <1 ms.

---

### 5.4 CarouselWriter — the single LLM creative call, plus one image call

**Purpose:** Given `StoryContext` alone, produce all slide text, caption, pinned comment, and hashtag themes in one Sonnet call with structured JSON output — the writer decides the carousel's own shape (Decision #67), not a pre-built slot plan. After the Sonnet call succeeds, one `gpt-image-1` call (Decision #64, `carousel/image_generator.py`) generates and duotone-treats the cover slide's background image, inside the same `write_carousel()` function so the call site never needs its own separate step.

**Input:** `StoryContext` (no `SlotPlan` — dropped entirely in Decision #67)

**Output:** `CarouselSpec` (full schema in section 6), with the hook slide's `image_asset` populated on success or left `None` on image-generation failure (never blocks the overall call).

**Prompt architecture (`writer_v2_0.md`, system prompt sections, in order):**

1. **Role definition.** Carousel writer for Anchor & Delta; explicitly told it decides the carousel's own narrative shape rather than filling a pre-built plan.

2. **Brand voice rules.** Active voice, present tense for stakes, no leading conjunctions, no hedging, no narrative dates in body prose (Decision #65 — relative framing like "just"/"this week" instead), non-obvious entities get a one-phrase identifier on first mention and a short anchor on every repeat (Decision #66).

3. **Hook Rules.** Headline ≤8 words/one sentence/no colon + a completing sub-heading ≤15 words, for the image-forward Cover template (Decision #64). Replaces the original 4-pattern taxonomy in section 9 below, which was never what got implemented.

4. **Domain vocabularies.** World runs on consequences/events/casualties; Finance runs on reframes/experts/deadlines/percent-moves; AI&Tech runs on named entities and second-order ironies. See section 9.

5. **Story Arc & Beat Writing Guide** (Decision #67, replacing the old per-slot writing guides). Subsections: **The essence** (Decision #70) — content and readability are never traded against each other; a beat over its word budget is a signal to split into another beat, never to cut real content; the 10-slide ceiling exists specifically so content is never forced out, even though most carousels should land closer to ~7 (typical attention span). **Finding the arc** — read the transmission's nodes as a non-binding map, not a checklist. **Writing a beat** — headline+body as one continuous thought; numbers and quotes land inline by default; a quote only earns its own beat when strong enough to stand alone, and is never forced when nothing in `AVAILABLE QUOTES` clears that bar (Decision #69's fallback). **Splitting an overloaded beat** (Decision #70) — the concrete mechanic for the essence principle above.

6. **Hard constraints.**
   - Word budgets: hook headline ≤8, hook body ≤15, beat headline ≤14, beat body ≤30 (Decision #68/#69, actually enforced by `CarouselPlanner`, not just stated)
   - No dedicated numbers/fact-sheet slide — `dominant_numbers` always null
   - For AI&Tech only: every slide should carry at least one named entity
   - No leading conjunctions, no hedging
   - Narrative thread comes from echo / setup-payoff / escalation / definite articles, never connector words

7. **Output format.** Strict JSON matching `CarouselSpec` schema, with `slot_id`/`role` writer-generated (`"hook"`, `"beat_1"`, `"beat_2"`, ..., `"cta"`, `"quote"` for a dedicated quote beat) rather than copied from a pre-supplied plan. Pydantic validates on receipt; malformed JSON, a quote-attribution mismatch, or a shape/word-budget violation each trigger one automatic retry with a targeted hint about the specific failure (Decision #69/#70), then either succeed or surface to the user.

8. **Pinned comment instruction.** After writing all slides, identify the single most screenshot-worthy sentence (typically the closing beat) and restate it as `pinned_comment`. Standalone, no hashtags, no @mentions, no questions.

**Prompt versioning.** Every `CarouselSpec` records the `prompt_version` it was generated with (currently `"writer-v2.0"`). Prompt iteration is tracked; rollback is clean — old prompt files are never overwritten, only superseded (Decision #08).

**Why one call:** Voice consistency requires the model to see the full slide arc in one pass. Splitting into per-slide calls produces drift and wastes tokens re-establishing context.

**Cache:** Keyed by `(card_id, card_version, prompt_version)` — no `slot_plan_hash` component anymore, since there's no slot plan.

**Cost:** ~$0.025–0.035 (Sonnet) + ~$0.01–0.02 (`gpt-image-1`, "high" quality). **Latency:** 4–7 seconds (Sonnet) + up to ~90s bounded (image, `IMAGE_TIMEOUT_SECONDS`).

**Regenerate paths — status as actually built:**

- **Targeted slide regenerate (Model B) — implemented.** `regenerate_slide()` in `writer.py`. Takes the full `CarouselSpec` plus the `slot_id` to regenerate, plus an optional free-text instruction; locked (`manually_edited=True`) slides can never be the target. Output is a single `Slide` replacing the targeted one. Cost: approximately $0.008. Latency: 3–5 seconds.
- **Cover image regenerate — implemented (Decision #64/Decision #71 UI).** Separate from Model B entirely: a `gpt-image-1`-only call (`image_generator.generate_cover_image()`) that swaps the hook slide's image without touching any text. UI exposes an optional keyword override (full override of the auto-derived subject, not a blend) plus a manual `is_person` toggle, at both the initial-generation and regenerate entry points. Cost: ~$0.01–0.02. Latency: up to ~90s bounded.
- **Inline text edit (Model C) — implemented.** No LLM call. User types in Streamlit; `headline`/`body` updated directly; `manually_edited=True`; affected slide re-rendered by Python. Cost: $0. Latency: <500 ms.
- **Full script regenerate with instruction (Model A) — not implemented.** The "🪄 Tweak whole carousel" button exists in the UI but is disabled (`ui/carousel_view.py`, tooltip "Full regenerate coming in v1.1"). No corresponding function exists in `writer.py` yet.
- **Caption-only regenerate — not implemented.** No dedicated function exists; the caption is only editable inline (Model C) today, not independently LLM-regenerated.

---

### 5.5 LayoutPicker

**Purpose:** Assign a layout template and styling parameters to each slide. Deterministic Python.

**Input:** `CarouselSpec`

**Output:** `EnrichedSpec` — same as `CarouselSpec` but each `Slide` is wrapped in a `LayoutChoice`:
- `template_id` — enum: `statement` | `number` | `quote` | `timeline` | `concept` | `hook` | `cover` | `cta` | `portrait` (last one still inert, no SEAM version has activated it)
- `text_size_class` — literal: `xl` | `l` | `m` | `s` (based on text length)
- `accent_colour` — hex from domain palette
- `theme_variant` — literal: `dark` | `light` (default `dark` in v1)

**Template selection rules — actual current order in `_pick_template()` (Decision #67 added the `beat`-role fallthrough; no other changes since):**

1. If `slide.role == cta` → `cta` template
2. Else if `slide.role == hook` → `cover` template (Decision #53, rebuilt image-forward per Decision #64 — supersedes the old interior-styled `hook` template, which is retained on disk but unused)
3. Else if `slide.quote` is populated → `quote` template
4. Else if `slide.dominant_numbers` (plural — renamed from `dominant_number` in Decision #57) is a non-empty list → `number` template
5. Else if `slide.role == event` → `timeline` template (dormant for new generations since Decision #67 retired the `event` role — this branch only still matters for re-rendering an old persisted carousel)
6. Else if `slide.role in {mechanism, concept}` → `concept` template (same dormant-for-new-generations note as above)
7. Else → `statement` template — this is now the effective default for every `beat`-role slide with no quote, which is most slides in a Decision #67 carousel. A `beat` with no quote falls through every role-specific branch with zero code changes needed when the role was introduced.

`portrait` never fires — no rule in `_pick_template()` currently checks `slide.image_asset`, even though the Cover template's hook slide does have one populated (Decision #64). The active image-forward cover comes entirely from the `hook`→`cover` branch above, not from a `portrait`-specific rule.

**Accent colour:** Domain-based. One accent per domain, applied identically to every slide in a carousel. See section 11.

**Python or LLM:** Python. **Cache:** Keyed by `CarouselSpec` hash. **Cost:** $0. **Latency:** <10 ms.

---

### 5.6 SlideRenderer

**Purpose:** Render each enriched Slide to a 1080×1350 PNG.

**Input:** `EnrichedSpec`

**Output:** `RenderedCarousel` — ordered list of PNG file paths.

**Stack:**
- Jinja2 HTML templates (one per `template_id`)
- CSS variables for palette/fonts/sizes — single source of truth
- Playwright headless Chromium for HTML → PNG
- Pillow only as a last-resort utility (resizing, optional watermarking)

**Rendering details:**
- Render at 2160×2700 (2× target resolution), downscale to 1080×1350 for final output. This produces sharp typography on high-DPI phones.
- Fonts self-hosted in repo (not loaded from Google Fonts CDN at render time). Deterministic, no flaky network, no surprise visual drift if Google changes a font version.

**Render cache:** Keyed by `hash(template_id + headline + body + accent + theme + brand_version)`. Cache HIT means PNG served from disk without re-rendering.

**Brand version invalidation:** Any CSS change increments `brand_version`. This invalidates render cache for affected templates. PNGs rebuild lazily on next view.

**Cost:** $0. **Latency:** ~250 ms per slide cold (render at 2×), ~5 ms per slide warm. Cold full carousel: ~1.5–2.5 seconds for a typical 5–10 slide carousel (Decision #67 — count is story-length-driven, no longer fixed at 8).

---

### 5.7 PostAssembler

**Purpose:** Assemble final caption + hashtags + pinned comment, persist the `Carousel` record, prepare for export.

**Input:** `EnrichedSpec` + `RenderedCarousel`

**Output:** `Carousel` (persisted) — see schema in section 6.

**Hashtag selection (`HashtagBuilder` sub-component):**
- `hashtags.yaml` maintained per domain — approximately 30–50 curated tags per domain plus 10–15 cross-domain general tags
- For each carousel: select 18–22 tags by sampling weighted on `hashtag_themes` from the spec, with rotation logic to avoid repeating the exact same set as the previous post (anti-shadowban heuristic)
- Tags are *selected from a curated pool*, never *generated by LLM*. The pool is the source of truth.
- Rotation log (last 10 posts' hashtag sets) maintained locally.

**Caption assembly:** LLM-written caption (already in spec) + line break + brand handle + line break + hashtag block.

**Export action:** When user clicks "Approve & Sync" in Streamlit, the engine writes the bundle into a per-carousel subfolder inside a configured directory that auto-syncs to phone via iCloud / Google Drive (Decision #52). Subfolder name: `YYYY-MM-DD_domain_slug` — the generation date, the card's domain, and a filesystem-safe slug of the card's `umbrella_title` (lowercase, hyphenated, capped ~40 chars). If that subfolder already exists (a same-day regenerate of the same card), a short suffix is appended rather than overwriting the existing bundle. The directory tree is created if missing; an unwritable or unavailable destination raises loudly rather than failing silently. Bundle contents (unchanged):
- `01_hook.png`, `02_setup.png`, ..., `08_cta.png` (or fewer if slot plan produced fewer)
- `caption.txt`
- `pinned_comment.txt`
- `hashtags.txt`
- `manifest.json` (carousel ID, generation metadata, slot map)

**[SEAM v2]** The Publisher component replaces the sync action with a Graph API call. The approval action remains the same; the post-approval action is the swap point.

**Cost:** $0. **Latency:** <100 ms.

---

## 6. Pydantic schema — the spine

These models are load-bearing. Changes here ripple through every component. Spec carefully.

### 6.1 StoryContext (input to writer)

```
StoryContext
├── umbrella_title: str
├── anchor_text: str
├── latest_delta: DeltaSummary
│   ├── headline: str
│   ├── tldr: str
│   └── event_date: date
├── previous_deltas: list[DeltaSummary]   # max 2
├── transmission_summary: TransmissionSummary
│   └── nodes: list[str]                  # 4–6 compressed bullets
├── domain: Literal["world", "finance", "ai_tech"]
├── card_age_days: int
├── available_quotes: list[SourcedQuote]
│   ├── text: str
│   ├── attribution: str
│   └── role: str                         # e.g. "Russian President"
├── key_entities: list[Entity]
│   ├── name: str
│   ├── type: Literal["person", "company", "agency", "model", "product", "place"]
│   └── importance: Literal["primary", "secondary"]
├── dominant_numbers: list[DominantNumber]
│   ├── value: str                        # rendered string e.g. "$2.3T", "1,430"
│   ├── label: str                        # e.g. "dead"
│   └── context: str                      # one-line explanation
├── visual_subject: str                   # Decision #64 — the cover image's
│                                          # gpt-image-1 subject, derived by a
│                                          # separate Haiku call (a "documentary
│                                          # filmmaker" framing, not a bare
│                                          # entity label)
└── visual_subject_is_person: bool        # Decision #64 — picks the portrait
                                           # vs. object/scene prompt template
```

### 6.2 SlotPlan (superseded, Decision #67 — no longer an input to the writer)

`SlotPlan`/`Slot` still exist in `carousel/models.py` (deprecated in place, not
deleted, matching this project's convention elsewhere), but `write_carousel()`
no longer takes one. The writer receives `StoryContext` alone and decides
count, roles, and structure itself:

```
SlotPlan
└── slots: list[Slot]
    ├── slot_id: str                      # stable role-based, e.g. "hook", "timeline_1"
    ├── role: SlotRole                    # enum
    └── is_optional: bool
```

`SlotRole` enum, current: `hook | setup | event | pivot | mechanism | concept
| proof | quote | contrast | payoff | cta | beat`. The 7 members
setup/event/pivot/mechanism/concept/proof/contrast are retired from new
generations as of Decision #67 — kept only so old persisted `CarouselSpec`
rows in Supabase still deserialize (Pydantic's strict enum validation would
otherwise fail to load them). New generations collapse all of those into the
12th member, `beat` — hook, quote, and cta remain in active use exactly as
before.

### 6.3 CarouselSpec (output from writer) — the load-bearing model

This is the single most important model in the system. Every downstream component reads it. Every future feature attaches to it. Schema versioned from day one.

```
CarouselSpec
├── schema_version: str                   # "1.0" — bump on breaking changes
├── script_id: UUID
├── card_id: str
├── card_version: str                     # hash of card content at generation time
├── prompt_version: str                   # e.g. "writer-v3.2"
├── slides: list[Slide]
├── caption: str
├── pinned_comment: str
├── hashtag_themes: list[str]             # themes, NOT hashtags
└── generation_metadata: GenerationMetadata
    ├── model: str                        # e.g. "claude-sonnet-4-6"
    ├── created_at: datetime
    ├── input_tokens: int
    ├── output_tokens: int
    └── cost_usd: float
```

### 6.4 Slide — the most carefully designed model

Every field below is either active (✅) or a forward-compatibility seam
(⏳). Seams are `Optional[X] = None` and ignored by current components.
`image_asset` moved from seam to active in Decision #64 — the first field
in this model to make that jump.

```
Slide
├── slot_id: str                          ✅ writer-generated (Decision #67),
│                                          # not copied from a slot plan —
│                                          # e.g. "hook", "beat_3", "cta"
├── role: SlotRole                        ✅
├── headline: str                         ✅ ≤8 words for hook, ≤14 for beat
├── body: str                             ✅ ≤15 words for hook sub-heading,
│                                          # ≤30 (±10% tolerance) for beat
├── emphasis_word: Optional[str]          ✅ single word for accent treatment
├── kicker: Optional[str]                 ⏳ deprecated (Decision #64) — the
│                                          # Cover template no longer renders
│                                          # one; field kept, always null
├── quote: Optional[SourcedQuote]         ✅ when slide IS a dedicated quote beat
├── dominant_numbers: Optional[list[DominantNumber]]  ✅ renamed + pluralised
│                                          # (Decision #57); always null as of
│                                          # Decision #67 — no dedicated
│                                          # numbers slide in new generations,
│                                          # hard-blocked by CarouselPlanner
├── factsheet_title: Optional[str]        ⏳ Decision #57, retired alongside
│                                          # dominant_numbers per Decision #67
├── text_hash: str                        ✅ for render cache
├── manually_edited: bool = False         ✅ true when user has edited inline
├── image_asset: Optional[ImageAsset]     ✅ ACTIVE (Decision #64) — the Cover
│   │                                      # template's AI-generated background
│   ├── source: Literal["wikimedia", "upload", "ai_generated"]  # only
│   │                                      # "ai_generated" is ever produced
│   │                                      # today; "wikimedia" remains an
│   │                                      # unimplemented alternative source
│   ├── url: str                          # local file path, never inline base64
│   ├── treatment: Literal["duotone", "high_contrast", "raw"]  # always
│   │                                      # "duotone" today
│   └── credit: Optional[str]
├── audio_clip_id: Optional[str]          ⏳ SEAM v2: Reels companion
├── animation_hint: Optional[str]         ⏳ SEAM v2: motion direction
└── notes: Optional[str]                  ✅ free-text editor notes
```

**Rules for adding fields later:** All new fields must be `Optional` with sensible defaults. Breaking changes require `schema_version` bump. Older spec versions remain readable by upgraded code (read-time migration if needed).

### 6.5 EnrichedSpec (output from LayoutPicker)

Same as `CarouselSpec`, but each `Slide` is wrapped:

```
EnrichedSlide
├── slide: Slide
└── layout: LayoutChoice
    ├── template_id: TemplateID
    ├── text_size_class: Literal["xl", "l", "m", "s"]
    ├── accent_colour: str                # hex
    └── theme_variant: Literal["dark", "light"]
```

### 6.6 Carousel (persisted record)

```
Carousel
├── id: UUID
├── card_id: str
├── card_version: str
├── spec: CarouselSpec                    # stored as JSONB in Supabase
├── slide_paths: list[str]                # paths to PNGs
├── final_caption: str                    # LLM caption + footer
├── final_hashtags: list[str]
├── pinned_comment: str
├── status: Literal["draft", "approved", "exported", "published"]
├── created_at: datetime
├── approved_at: Optional[datetime]
├── exported_at: Optional[datetime]
└── published_at: Optional[datetime]      ⏳ SEAM v2: set by Publisher
```

---

## 7. Persistence

One new Supabase table: `carousels`.

```
carousels
├── id (uuid, primary key)
├── card_id (text, foreign key to cards)
├── card_version (text)
├── spec (jsonb)                          # full CarouselSpec
├── slide_paths (text[])
├── final_caption (text)
├── final_hashtags (text[])
├── pinned_comment (text)
├── status (enum: draft | approved | exported | published)
├── created_at (timestamptz)
├── approved_at (timestamptz, nullable)
├── exported_at (timestamptz, nullable)
└── published_at (timestamptz, nullable)
```

**Why JSONB for `spec`:** The CarouselSpec schema will evolve through v1.0 → v1.5 → v2. Hard schema columns would require migrations on every field addition. JSONB plus Pydantic validation gives flexibility without sacrificing type safety at the application layer.

**No changes to existing tables.** The carousel engine only reads `cards`, `delta_events`, `transmissions`.

---

## 8. Caching strategy

Three cache layers, all keyed by content hash. Aggressive by design.

| Layer | Key | Stores | Where |
|-------|-----|--------|-------|
| **Writer output cache** | `(card_id, card_version, prompt_version)` — no `slot_plan_hash` component since Decision #67 (there's no slot plan anymore) | Full `CarouselSpec` | Supabase `carousels` table (status='draft') |
| **Render cache** | `hash(template_id + slide content + accent + theme + brand_version)` | PNG file | Local filesystem (object storage later) |
| **Hashtag rotation log** | Last 10 carousels' hashtag sets | Tag lists | Local file or `hashtag_rotations` table |

**The cache contract:**
- Regenerate from identical inputs → served from cache, no LLM call, no render
- Edit single slide → only that slide re-renders, all others served from render cache
- Change template CSS → bump `brand_version`, affected templates' renders invalidated, rebuilt lazily
- Change prompt → bump `prompt_version`, writer cache invalidates for that prompt version, old `CarouselSpec` records remain attached to their generation prompt version

---

## 9. Hook taxonomy and domain vocabularies

These are the writer prompt's load-bearing patterns. Validated across 5 real Story Cards before lock-in.

### 9.1 Hook Rules — headline + completing sub-heading (Decision #64, supersedes the original 4-pattern taxonomy)

The original plan for this section named four selectable patterns
(Contrast, Negative fact + reveal, Number shock, Insider declaration).
That taxonomy was never what got implemented — the actual writer prompt
(`writer_v2_0.md`'s Hook Rules section) uses a different, more specific
set of rules built for the current image-forward Cover template
(Decision #64), which renders headline and a completing sub-heading in
the lower band over an AI-generated background image.

**Headline:** one line, ≤8 words, one sentence — no colon (a colon
splits the line into two beats exactly like a second sentence would),
no two-sentence structure, names the specific subject directly, states
the story's most dramatic/surprising fact without holding it back for
the sub-heading. One `emphasis_word` — the word carrying the emotional
hinge.

**Sub-heading:** one sentence, ≤15 words, completes the headline rather
than repeating it — answers "what exactly happened," supplying the
name/number/date the headline didn't have room for.

Anti-patterns, explicitly banned: pure questions (weaken swipe pull),
accusatory framing on World/geopolitical content, witty setups as a
default strategy (unsustainable at daily publishing volume), abstract
lines that could apply to several different stories.

The prompt includes several GOOD/BAD worked examples the model is told
to treat as the literal calibration bar, not optional flavour text —
see `writer_v2_0.md`'s Hook Rules section for the current set.

### 9.2 Domain vocabularies

| Domain | Drama vocabulary | Default arc shape |
|--------|------------------|-------------------|
| **World** | Actions with consequences, dated events, mass-casualty numbers, regime change, deposition dynamics | Consequence-chain |
| **Finance** | Named experts in unexpected positions, dated deadlines, dramatic percent moves, counterintuitive reframes | Reframe-centred |
| **AI & Tech** | Named entities (models, executives, agencies, products), structural ironies, second-order effects | Second-order irony |

These are hints, not hard rules. The writer applies the vocabulary that fits the card.

### 9.3 Named-entity density rule

For AI & Tech only: every slide should carry at least one named entity (model, person, company, agency, product). Vague references ("a company", "an executive") signal weakness. This rule does not apply to World or Finance, where entity density varies more naturally.

### 9.4 Structural contrast (retired as a dedicated role, Decision #67)

The original `contrast` slot role — for explicit X-did-A / Y-did-B
structure — is retired from new generations along with the other 6
structural roles collapsed into `beat`. There's no dedicated contrast
slide anymore; when a card's transmission has that shape, it becomes
one beat (or two, if it earns the room per §5.3's splitting guidance)
written in prose, same as any other structural pattern the writer
notices in the transmission. The underlying instinct — don't let a
genuine before/after collapse into a flat paraphrase — still applies,
it's just no longer enforced via a named slot.

### 9.5 Metaphor reuse

The writer is permitted to surface and reuse the card's strongest metaphor as slide copy when the metaphor is slide-grade (e.g. "weapon disposal unit" → "defusing the bomb"). This is not plagiarism; it is voice continuity between card and carousel.

### 9.6 Narrative thread

Thread between slides comes from echoed language, setup-payoff pairs, escalation, and definite articles ("this", "that", "the"). It does **not** come from leading conjunctions. "But," "And," "However," "Meanwhile," "Now" as slide openers are banned. If a slide reads as disconnected, fix the slide content; do not add a connector word.

---

## 10. Template archetypes

Eight template files exist on disk; five are actively produced by new
generations, three are dormant (kept only for re-rendering old
persisted carousels, never selected for a fresh `beat`/`hook`/`quote`/
`cta` carousel).

| Template ID | Status | Used for | Word density |
|-------------|--------|----------|--------------|
| **Cover** | Active | Slide 1 only — image-forward: full-bleed AI-generated duotone background, punchy headline + completing sub-heading in the lower band (Decision #53, rebuilt Decision #64) | Very low |
| **Statement** | Active — the workhorse | Every `beat`-role slide with no quote and no populated numbers, which is most slides in a Decision #67 carousel | Medium |
| **Quote** | Active | A dedicated quote beat — only when a sourced quote is strong enough to carry the whole slide alone (Decision #67's inline-by-default rule) | Low (quote dominates), sized generously per Decision #72 |
| **CTA** | Active | Final slide, fixed copy | Fixed |
| **Number** | Dormant | Was the fact-sheet template (Decision #57); retired from new generations by Decision #67 — numbers live inline in beat prose now, hard-blocked by `CarouselPlanner`. Kept for old persisted carousels only. | Low (figure dominates) |
| **Timeline** | Dormant | Was the `event`-role template; `event` retired by Decision #67, same reasoning as Number above. | Medium |
| **Concept** | Dormant | Was the `mechanism`/`concept`-role template; both roles retired by Decision #67. Structurally near-identical to Statement (only font-size/weight differ, both covered by `TextSizeClass`). | Medium (text-dense) |
| **Hook** | Dormant | Superseded by Cover for the hook role since Decision #53. | Very low |

**Wikimedia/editorial imagery** — `Slide.image_asset.source` supports
`"wikimedia"` in the schema, but zero fetch code exists anywhere in the
repo for it (verified directly, not assumed) — it's a real but
unimplemented alternative to the current `ai_generated`/`gpt-image-1`
source, not an active feature. `TemplateID.portrait` is similarly inert
— no selection rule in `layout_picker.py` currently checks
`image_asset` at all; the active image-forward cover comes entirely
from the `hook`→`cover` branch, not a portrait-specific rule.

### Role-to-template mapping (current)

| Role | Template |
|------|----------|
| `hook` | Cover |
| `beat` (no quote, no numbers) | Statement — the effective default for nearly every slide |
| `quote` | Quote |
| `cta` | CTA |
| *(retired, dormant-only)* `event` | Timeline |
| *(retired, dormant-only)* `mechanism`, `concept` | Concept |
| *(retired, dormant-only)* `proof` | Number |

### Word budgets (current, Decision #68/#69/#70)

Enforced by `CarouselPlanner.validate_carousel_shape()`, not just stated
in the prompt — each figure below includes a 10% tolerance before the
check actually rejects (e.g. 30 → 33).

| Role | Headline | Body |
|------|----------|------|
| `hook` | ≤8 words, one line, one sentence, no colon | ≤15 words (completing sub-heading) |
| `beat` | ≤14 words | ≤30 words — a readability constraint on one slide, not a content ceiling on the story; a beat that doesn't fit is a signal to split into another beat (§5.3), never to cut real content |
| `quote` | attribution name only | quote text itself has no hard word cap, but must stand alone with zero surrounding explanation |
| `cta` | fixed: "Follow @handle for daily intelligence" | (none) |

---

## 11. Visual system — v1.0 typography only

### 11.1 Theme

**Warm dark theme. Single theme in v1.0.** Not pitch black — a cozy, dense dark that feels like a dimly lit library or aged leather, not a cold screen. Validated via rendered mockup and approved before template-design week begins.

Light theme variant is supported in the schema (`theme_variant`) but not used in v1.0.

**The single most important background decision:** background is warm near-black `#1A1612` (dark warm brown), not cold near-black `#0E0E0E`. Cold black feels harsh and digital. Warm dark brown feels editorial and considered. This hex is the foundation of the entire register.

### 11.2 Domain palettes

Three accents, one per domain, all resolved and locked in `layout_picker.DOMAIN_ACCENTS`:

| Domain | Accent | Hex | Rationale |
|--------|--------|--------------|-----------|
| World | Amber gold | `#C8813A` | Reads like candlelight on warm dark; red on warm brown muddy |
| Finance | Cool silver | `#A8B8C8` | Resolved from the original "TBD" — needs contrast against World's warmth |
| AI & Tech | Electric cyan | `#00D9FF` | Strong contrast against warm dark; signals precision |

**Constraints:**
- Each accent visually distinguishable at a glance in a feed grid
- All three work against `#1A1612` warm dark background
- Each is the sole colour element per slide — 3–5 appearances maximum per slide
- Domain tags, emphasis words, thin rule lines, dominant numbers all use the accent

### 11.3 Typography — locked

**This decision is final. Not subject to template-week revision.**

Two fonts, both free on Google Fonts, both self-hosted in the repo. Do not substitute.

- **Headline font: Playfair Display, weights 700 and 900 only.** High-contrast serif with ink-trap detail. Renders dramatically at 100px+. Transforms slide register from corporate to serious publication. This is the single decision that makes the slides look editorial rather than generic.
- **Body font: Inter, weights 400 and 500 only.** Clean geometric sans for body text, date labels, footer, attribution, muted context lines.

Self-host both as `.woff2` files in `carousel/fonts/`. Do not load from Google Fonts CDN at render time (Decision #10).

Do not use: Space Grotesk, Archivo Black, or any single-font system. The Playfair Display / Inter pairing is load-bearing — it is what makes the slides look distinctive.

### 11.4 Layout chassis (shared across all templates, `base.css`)

Every slide shares this skeleton — what makes the feed grid read as one
body of work. All sizes below are 2x-canvas CSS values (halve for the
downscaled 1x final output) — the convention used everywhere in the
actual codebase, unlike this section's original 1x-first framing.

- Domain tag — top-left, accent colour, Inter 500, 48px (2x), letter-spacing 6px, uppercase
- Main content — content-wrapper band, top-aligned so leftover space pools at the bottom (reads intentional, not floaty)
- Thin rule line — accent colour at 40% opacity, structural divider between headline and body. One per slide maximum.
- Page indicator — bottom-left, Inter 400, 40px (2x), `var(--text-muted)` = `#B0A898` (Decision #73 — was `var(--text-footer)` `#4A4540`, low contrast against the background, nearly invisible)
- Brand wordmark — bottom-right, "@anchordelta" (Decision #73 — was "ANCHOR & DELTA"), Inter 500, 48px (2x), letter-spacing 3px, `var(--text-muted)`, no uppercase transform (preserves the lowercase handle, matching the Cover slide's own handle exactly)

### 11.5 Slide-level typography scale

Sizes vary meaningfully by template — there is no longer one uniform
scale applied everywhere, unlike the original planning assumption.
Representative current values (2x-canvas CSS px; halve for 1x final):

| Element | Template | Font | Weight | 2x size | Colour |
|---------|----------|------|--------|---------|--------|
| Headline | Statement (workhorse) | Playfair Display | 900 | 152px | `var(--text-primary)` `#E8E0D0` |
| Headline | Cover (hook) | Playfair Display | 900 | 180px | `var(--text-primary)` |
| Headline | CTA (line 1) | Playfair Display | 900 | 120px | `var(--text-primary)` |
| Body text | Statement | Inter | 400 | 72px | `var(--text-muted)` `#B0A898` — left-aligned with a modest inset (Decision #68), not centred |
| Quote text | Quote | Playfair Display italic | 700 | 108px | `var(--text-primary)` (Decision #72 — was 100px, cramped letter-spacing/line-height fixed) |
| Quote attribution (name) | Quote | Inter | 500 | 48px | `var(--text-primary)` (Decision #72 — was 32px) |
| Quote role/designation | Quote | Inter | 400 | 38px | `var(--text-muted)` (Decision #72 — was 28px) |
| Sub-heading | Cover | Inter | 400 | 60px | `var(--text-muted)` |
| Footer (page indicator + wordmark) | shared, `base.css` | Inter | 400/500 | 40px / 48px | `var(--text-muted)` (Decision #73) |

All hardcoded muted-grey colours across templates were consolidated to
the single `var(--text-muted)` CSS variable earlier this session — no
template hand-codes `#8A8078` or `#6B6560` anymore.

### 11.6 Rendering technical specifications

- Canvas: 1080×1350 (Instagram portrait 4:5)
- Render at 2160×2700 (2×), downscale to 1080×1350 for final output
- Self-hosted fonts loaded via `@font-face` — Playfair Display (700, 900) and Inter (400, 500)
- Background: warm dark brown `#1A1612`
- Primary text: warm cream `#E8E0D0` (`--text-primary`)
- Muted text: `#B0A898` (`--text-muted`) — used for body context, footer, page indicator, and the wordmark (all consolidated to this one variable; `--text-footer` `#4A4540` still exists in `base.css` but is no longer used by the footer elements its name suggests, after Decision #73)
- Subtle warm radial gradient overlay on background (amber at ~7% opacity) for depth — not imagery, just warmth
- Thin rule lines: accent colour at 40% opacity — structural, never decorative
- No drop shadows, no glow effects, no hard gradients on content elements
- Cover slide only: full-bleed AI-generated duotone background image (Decision #64) plus a separate CSS gradient overlay fading from transparent at the top to fully opaque `#1A1612` by 85% down, guaranteeing the text zone stays legible regardless of image content

**Critical validation step:** After every template iteration during design week, render the PNG at full resolution and open on your actual phone. Not in the browser, not in Streamlit — on the phone, at full screen. Production at 1080×1350 on a modern iPhone is dramatically sharper and more impactful than any desktop preview. This is the only true quality gate.

---

## 12. Streamlit UI integration

A "Generate Carousel" button is added to every card in the existing dashboard.

### 12.1 Preview view (`ui/carousel_view.py`)

- One column per slide (`st.columns(len(slides))`) — bordered container
  per slide with thumbnail (270px wide), role-abbreviated caption, and
  per-slide controls
- Full-width panels below the entire slide row (not inside the narrow
  per-slide column) for the edit and image-regenerate controls when
  toggled open — a real bug fixed this session: the image controls were
  originally built inside the cramped column and were unusable
- Below: editable caption text box
- Below: editable pinned comment text box
- Below: hashtag list (displayed; resampled via button, not directly edited)

### 12.2 Per-slide controls

- ✏️ **Edit** — toggles a full-width inline text editor below the row (Model C, no LLM call, instant re-render via cache)
- 🔄 **Regenerate this** + optional instruction text field — targeted Sonnet call (Model B); ↩️ **Undo** appears after a regenerate to restore the previous slide
- 🖼️ **Regenerate cover image** — hook slide only. Toggles a full-width panel with an optional keyword field (full override of the auto-derived subject, not a blend) and a manual "portrait / person composition" checkbox, then a single `gpt-image-1` call that swaps only the image — text is never touched. Live and active, not a disabled seam — Decision #64 shipped image generation in v1.0, not v1.5 as originally planned.
- No lock/freeze button exists as a separate control — `manually_edited` is set automatically by the inline editor (Model C) and read by the regenerate/undo logic to prevent stray overwrites, but there's no dedicated ⛔ UI toggle for it today.

### 12.3 Script-level controls

- 🔄 **Resample hashtags** — implemented, Python only, no LLM
- 🪄 **Tweak whole carousel** — UI exists but disabled (tooltip: "Full regenerate coming in v1.1"); no backing function exists in `writer.py` yet
- ✅ **Approve & Sync** — implemented, writes bundle to the configured directory and marks the carousel `approved`
- 📤 **Publish to Instagram** — disabled (tooltip: "Direct publishing arrives in v2") — **[SEAM v2]**, unchanged from original plan
- No separate caption-regenerate control exists — caption is only editable inline today, not independently LLM-regenerated

Cover image generation also has its own entry point at first
generation, before any carousel exists yet: an optional "🖼️ Cover image
keywords" expander sits above the 🎠 generate button on every eligible
card in `ui/app.py`, same override/toggle mechanism as the regenerate
panel above.

### 12.4 Sync destination

Configured via the `CAROUSEL_SYNC_DIR` environment variable (`config.py`), not a Streamlit setting (Decision #52). Default: `G:\My Drive\Anchor & Delta\Outbox`. Each approved carousel gets its own subfolder under this directory, named `YYYY-MM-DD_domain_slug` (generation date, card domain, slug of the card's `umbrella_title`) — this replaces the earlier flat-folder design and eliminates the manual copy-to-Drive step. A same-day regenerate of the same card gets a short suffix appended rather than colliding. If `CAROUSEL_SYNC_DIR` is unset or empty, the engine falls back to the local `outputs/bundles/` folder so nothing breaks when the env var is missing. Engine has no knowledge of the sync layer; it just writes files to a configured directory.

---

## 13. Cost and latency profile

| Operation | Cost | Latency |
|-----------|------|---------|
| First generation (cold) — Haiku context + Sonnet writer + cover image | ~$0.006 (Haiku) + ~$0.025–0.035 (Sonnet) + ~$0.01–0.02 (`gpt-image-1`) ≈ $0.04–0.06 | ~4–7s (Sonnet) + up to ~90s bounded (image) |
| Targeted slide regenerate (Model B) | ~$0.008 | 3–5 s |
| Cover image regenerate (image only, no text call) | ~$0.01–0.02 | up to ~90s bounded |
| Inline edit + re-render (Model C) | $0 | <500 ms |
| Resample hashtags | $0 | <50 ms |
| Cached generation (no change) | $0 | <200 ms |
| Full regenerate with instruction (Model A) | not implemented — UI button disabled | — |
| Caption regenerate | not implemented — caption only editable inline | — |

These are the same documented estimates carried in `write_carousel()`'s
own docstring, not a separate figure — the two should always agree; if
they ever drift apart, the code comment is the one to trust and this
table needs updating, not the reverse. The image call is the main new
cost/latency driver versus the original v1.0 estimate, which predates
Decision #64 shipping image generation at all.

At 3 carousels/day, that's roughly $0.12–0.18/day depending on how many
generations need an image regenerate — still negligible, but no longer
the flat ~$0.037/carousel figure from before image generation existed.

---

## 14. Roadmap — v1.0, v1.5, v2

### v1.0 — shipped, ahead of the original plan on one front

Everything in this document, plus one thing pulled forward from v1.5:
**AI-generated cover images shipped in v1.0** (Decision #64), not
typography-only as originally planned — `gpt-image-1` generates a
full-bleed background image, duotone-treated to the domain accent, for
every hook slide. This was a deliberate pull-forward, not a v1.5
portrait-template activation as described below; the current image
pipeline is unrelated to Wikimedia and doesn't use the `portrait`
template at all (see §10's note that `portrait` remains completely
inert — no selection rule fires for it).

### v1.5 — partially reframed given the v1.0 pull-forward above

- **Portrait template / Wikimedia source** — still not built. Verified
  directly: zero fetch code exists anywhere in the repo for Wikimedia,
  and `layout_picker.py`'s `portrait` case never fires. This remains a
  real future option — a non-AI-generated, non-duotone alternative
  image source, useful for named real people where `gpt-image-1`'s
  likeness accuracy is unreliable (see the AskUserQuestion/discussion
  logged around cover-image keyword overrides) — but it is additive to
  the current `ai_generated` pipeline, not a replacement for it.
- **Domain prompt tuning** based on real performance data — not yet
  started; no post-volume data exists yet to tune against.

### v2.0 — planned, decided after meaningful post volume (50+ posts)

Three additions, still all pending — none started:
- **Reels companion generation.** For each approved carousel, generate a 30-second Reel using: condensed script from CarouselSpec, ElevenLabs voiceover with pronunciation overrides, synced captions, hook-slide ken-burns background. Same approval, dual output.
- **Editorial imagery slot.** When the card has a specific evocative location/event/object that isn't a person, use a treated editorial photography source (Wikimedia or licensed) — distinct from the current AI-generated cover, which already covers this case today via `gpt-image-1`'s non-person prompt template.
- **Instagram Graph API publishing.** Publisher component replaces sync-to-folder. The `status='approved'` action becomes `Publisher.publish()`. UI stub already exists (disabled "📤 Publish to Instagram" button) — no backing implementation yet.

### v3.0 — speculative, defer until v2 data exists

- Performance-driven prompt evolution (saves/shares feedback loop)
- Multi-variant generation for high-stakes cards
- Domain-specific prompt tuning based on engagement signal
- Scheduled publishing at optimal times

### Indefinite hold (do not plan in detail)

- Multi-platform output (LinkedIn, TikTok, X)
- Multi-language output
- Brand sub-properties / sub-accounts
- Multi-user collaboration

---

## 15. Build order — when implementation begins

Templates and prompt come before pipeline code. Code is the last thing built, not the first.

1. **Template design week.** Hand-coded HTML/CSS for 4 templates (Statement, Number, Quote, Hook). Iterate in browser. Pick fonts and palette. No project code yet. This is the hardest and most undervalued part.
2. **Remaining 3 templates.** Timeline, Concept, CTA. Verify all 7 render coherently together.
3. **Pydantic models.** Freeze every schema in section 6.
4. **CardLoader + ContextBuilder.** Real card → real StoryContext. Print and inspect output by hand.
5. **CarouselPlanner.** Test deterministic slot logic on 5 real cards manually.
6. **CarouselWriter prompt.** Iterate on a single card until output is consistent. Then run on the other 4 test cards.
7. **LayoutPicker + SlideRenderer.** First end-to-end PNG carousel.
8. **PostAssembler + hashtag pool.** Bundle export working.
9. **Streamlit preview.** Full UX: edit / regenerate / lock / approve.
10. **Cache layers.** Last, because correctness comes before performance.

---

## 16. Definition of done for v1.0

v1.0 is shippable when, in order:

1. Six real Story Cards (two per domain) generate carousels end-to-end without manual intervention.
2. Visual quality bar met: a designer friend asked "is this AI-generated or designed?" cannot tell.
3. Targeted regenerate works for any slide.
4. Render cache verified: editing one slide does not re-render others.
5. Decisions log (`CAROUSEL_DECISIONS.md`) is current.
6. Anonymous Instagram account is set up.
7. First three carousels manually QA'd before any are published.

After v1.0 ships: 4-week learning phase, then v1.5 scoping review.

---

## 17. Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| LLM voice drifts from card-to-card despite prompt | Prompt versioning + held-out test-card set for regression review |
| AI&Tech named entities incorrect at source | Flagged for separate Intelligence Engine review — not a carousel-layer fix |
| Render quality on phone disappoints | 2x render with downscale; review on actual phone before approving template-design week complete |
| Template-design week stretches indefinitely | Hard limit: 2 weeks. If not done by then, ship with current templates and revise post-v1.0 |
| Cache invalidation gets buggy | Three layers separated by responsibility; brand_version is global kill switch if needed |
| Sync-to-folder unreliable | iCloud and Google Drive are user's choice; engine just writes files to a path |

---

## 18. Repository layout and boundary discipline

### 18.1 Same repository, new top-level module

The carousel engine lives in the same repository as the existing Intelligence Engine. Not a separate repo, not a git submodule.

Three reasons:

1. **Shared Story Card contract.** The carousel engine reads `cards`, `delta_events`, `transmissions` from the same Supabase. One Pydantic definition of the Story Card, referenced by both engines. Splitting repos means keeping two schema definitions in sync manually — a source of drift.
2. **Shared infrastructure that already works.** Supabase client setup, environment variable handling, Streamlit app scaffolding, Anthropic client configuration, logging, cost tracking. The carousel engine reuses all of it. Splitting would duplicate scaffolding or force a third shared-library repo — over-engineering for a solo project.
3. **One Streamlit UI.** The "Generate Carousel" button lives inside the existing card view. Same app, extended.

### 18.2 Directory structure

Existing structure preserved. Carousel engine added as a new `carousel/` top-level module.

```
Anchor-Delta/
├── config.py                      # existing — extend with CAROUSEL_* settings
├── pipeline/                      # existing Intelligence Engine — DO NOT TOUCH
│   ├── fetcher.py
│   ├── filter.py
│   ├── engine.py
│   ├── models.py
│   ├── orchestrator.py
│   └── runner.py
│
├── carousel/                      # NEW — carousel engine module
│   ├── __init__.py
│   ├── models.py                  # all Pydantic schemas (see section 6)
│   ├── loader.py                  # stage 1: CardLoader
│   ├── context_builder.py         # stage 2: ContextBuilder + Haiku extraction
│   ├── planner.py                 # stage 3: CarouselPlanner
│   ├── writer.py                  # stage 4: CarouselWriter (Sonnet call)
│   ├── layout_picker.py           # stage 5: LayoutPicker
│   ├── renderer.py                # stage 6: SlideRenderer (Playwright)
│   ├── assembler.py               # stage 7: PostAssembler + HashtagBuilder
│   ├── cache.py                   # three cache layers (writer, render, hashtag rotation)
│   ├── prompts/                   # versioned prompt files
│   │   ├── writer_v1_0.md
│   │   ├── extraction_v1_0.md
│   │   └── caption_v1_0.md
│   ├── templates/                 # HTML/CSS templates (design week output)
│   │   ├── base.css               # shared chassis (layout grid, footer, brand mark position)
│   │   ├── palettes.css           # domain accent variables
│   │   ├── statement.html
│   │   ├── number.html
│   │   ├── quote.html
│   │   ├── timeline.html
│   │   ├── concept.html
│   │   ├── hook.html
│   │   └── cta.html
│   ├── fonts/                     # self-hosted font files (see decision #10)
│   ├── assets/                    # brand mark, wordmark files
│   └── hashtags.yaml              # curated hashtag pools per domain
│
├── db/                            # existing Supabase layer — extend
│   ├── ... existing files
│   └── carousel_queries.py        # NEW — queries for the `carousels` table
│
├── ui/                            # existing Streamlit — extend
│   ├── app.py                     # existing dashboard (add "Generate Carousel" button)
│   ├── carousel_view.py           # NEW — preview + edit + regenerate + approve UX
│   └── components/                # NEW — reusable UI pieces if needed
│
├── outputs/                       # NEW — render output and export bundles
│   ├── renders/                   # render cache PNGs (gitignored)
│   └── bundles/                   # export bundles per carousel (gitignored)
│
├── tests/
│   └── carousel/                  # NEW — tests for the carousel engine
│
├── DESIGN_LESSONS.md              # existing — Intelligence Engine lessons
├── CAROUSEL_BLUEPRINT_v1.md       # this document
├── CAROUSEL_DECISIONS.md          # running decisions log
└── README.md                      # update to mention both engines
```

### 18.3 Boundary discipline — non-negotiable

The carousel module reads from the Intelligence Engine's outputs. It never writes back. This boundary keeps the Intelligence Engine's stability intact.

Rules:

- `carousel/` may import from `pipeline/models.py` to reference the Story Card contract
- `carousel/` may import from `db/` to read cards, delta events, transmissions
- `carousel/` writes only to its own new Supabase table (`carousels`) and to `outputs/`
- `pipeline/` never imports from `carousel/`
- If a change to `pipeline/` seems necessary to support the carousel, stop. First try to adapt `carousel/context_builder.py` to what `pipeline/` already produces. If a real pipeline change is genuinely needed, that is a separate deliberate decision recorded in `DESIGN_LESSONS.md`, not a casual patch.

### 18.4 Pre-implementation scaffolding

Two small commits before template-design week begins, to make the structure real:

**Commit 1 — Directory scaffolding:**
- Create empty `carousel/` with `__init__.py`
- Create `carousel/templates/`, `carousel/prompts/`, `carousel/fonts/`, `carousel/assets/`
- Create `outputs/renders/` and `outputs/bundles/` with `.gitkeep`
- Add `outputs/renders/` and `outputs/bundles/` to `.gitignore`

**Commit 2 — Documentation:**
- Place `CAROUSEL_BLUEPRINT_v1.md` at repo root
- Place `CAROUSEL_DECISIONS.md` at repo root
- Update `README.md` to reference both engines and link to blueprint

After these two commits, the structure exists as skeleton. Template-design week fills `carousel/templates/`. Only after templates are done does Python implementation begin, filling `carousel/*.py` in the order specified in section 15 (Build Order).

### 18.5 Branch strategy

Work on the default branch. The carousel module is inert until actively invoked from the UI. There is no risk of breaking the existing Intelligence Engine because the carousel module does not touch anything the engine uses. Feature branches are for uncertain changes; this is a certain addition made in visible, committed steps.

### 18.6 What Claude Code needs when implementation starts

When opening a fresh Claude Code session for implementation, provide the following context:

1. This blueprint document (`CAROUSEL_BLUEPRINT_v1.md`)
2. The decisions log (`CAROUSEL_DECISIONS.md`)
3. Existing `DESIGN_LESSONS.md` (Intelligence Engine context)
4. Existing `pipeline/models.py` (Story Card contract)
5. Existing `db/` layer (how Supabase is accessed)
6. Existing `ui/app.py` (Streamlit patterns used)

The blueprint and decisions log together should carry sufficient architectural context that a fresh session can proceed without re-litigating design decisions. If a Claude Code session starts questioning locked decisions, refer it back to the log entry that locked them.

---

## 19. What this document is and is not

This is the **architectural spine**. Adding features means adding to it; restructuring it means a v2 bump.

This is **not** a code specification. It defines components, contracts, and behaviours. Implementation details (which Python library to use for hashing, how Streamlit state is managed, etc.) are left to implementation.

This is **not** the decisions log. The decisions log (`CAROUSEL_DECISIONS.md`) records the *reasoning* behind every decision in this document, plus any subsequent changes. The blueprint is "what we are building"; the decisions log is "why we chose this and what we considered."

End of blueprint v1.0.
