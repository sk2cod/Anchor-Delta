# Anchor & Delta — Instagram Carousel Engine

## Blueprint v1.0

Date frozen: 2026-06-30
Status: Active. Supersedes none.

---

## 1. Purpose

Convert finalised Story Cards from the existing Intelligence Engine into publish-ready Instagram carousels. Eight slide PNGs + caption + pinned comment + hashtag list per carousel. Solo-use, human-approved, manual-publish in v1.

The Story Card produced by the existing pipeline is treated as a frozen contract. This engine reads cards. It does not modify, augment, or write back to them.

---

## 2. Goals and non-goals

**v1.0 goals:**

- One-click carousel generation from any Story Card
- Production-grade typographic visual system across three domains (World / Finance / AI & Tech)
- Editor-quality content compression: hook taxonomy, domain vocabularies, slot-driven planning
- Solo daily use sustainable: targeted regenerate, inline edit, fast caching
- Architecture forward-compatible with portraits (v1.5), editorial imagery (v2), Reels companion (v2), Graph API publish (v2)

**v1.0 non-goals:**

- AI image generation
- Photographic backgrounds, portraits, illustrations of any kind
- Reels, video, or audio output
- Instagram Graph API publishing
- Multi-account, multi-user, or team workflows
- Performance analytics ingestion
- Scheduling or queueing
- LangGraph, agent frameworks, multi-model abstraction

Each non-goal has a defined re-evaluation point in section 13.

---

## 3. Design philosophy

Five principles. Every component honours all five.

1. **Python owns determinism. LLM owns creativity.** Planning, layout, hashtags, rendering, caption assembly, persistence: Python. Slide text, caption draft, hashtag themes: LLM. No third category.

2. **One LLM creative call per generation.** A single Sonnet call produces all slide text, caption draft, and hashtag themes in one pass for voice consistency. Targeted regenerates are additional calls only when needed. Plus one cheap Haiku call upstream for entity/number/quote extraction.

3. **Slot-driven generation.** Python decides which slots exist for a given card. The LLM fills the slots given to it. The model never decides how many slides to write or what structure to use.

4. **Cache by content hash. Aggressively.** Three cache layers. Re-render after a text edit is free. Re-render after a template tweak is free for unchanged slides. This is the property that makes daily solo use sustainable.

5. **Architecture stays legible at 50,000 lines.** Seven pipeline stages, one responsibility each, Pydantic contracts at every boundary, no shared mutable state. Adding features means adding to stages, not restructuring them.

---

## 4. System overview

Seven sequential stages. Each stage takes a typed Pydantic input and returns a typed Pydantic output. There are no dicts passed between stages.

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
[3] CarouselPlanner         Python      <10 ms
       │
       ▼
[4] CarouselWriter          1 Sonnet call      ~5 s
       │
       ▼
[5] LayoutPicker            Python      <10 ms
       │
       ▼
[6] SlideRenderer           Python (Playwright)      ~2 s for 8 slides cold
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

Total cold-path latency: ~9 seconds for a fresh generation. Warm-path (cache hits): under 1 second.

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

### 5.3 CarouselPlanner

**Purpose:** Decide slot structure and order for this card. Deterministic Python rules.

**Input:** `StoryContext`

**Output:** `SlotPlan` — ordered list of `Slot` definitions, each with `slot_id`, `role`, `is_optional`.

**Slot rules:**

Fixed slots (always present): `hook`, `setup`, `payoff`, `cta`.

Conditional slots, added in this priority order if their conditions are met:

| Slot | Condition |
|------|-----------|
| `event` | `latest_delta` exists (effectively always) |
| `pivot` | always (it is the reframe slide) |
| `proof` | `dominant_numbers` is non-empty |
| `contrast` | transmission contains explicit X-did-A / Y-did-B structure |
| `mechanism` | domain in {`world`, `ai_tech`} and transmission contains explanatory mechanism content |
| `concept` | domain in {`finance`, `ai_tech`} and transmission contains framework / structural insight |

**Hard cap:** 8 total slots (7 content + 1 CTA). If conditional slots would exceed the cap, drop in reverse priority order: `proof` → `concept` → `mechanism` → `contrast`. (`contrast` last because it is load-bearing when present.)

**Python or LLM:** Python. No LLM judgment involved.

**Why this matters:** Eliminates approximately 80% of "carousel is wrong shape" failures. Structure is deterministic; only content is creative.

**Cache:** Keyed by `StoryContext` hash. **Cost:** $0. **Latency:** <10 ms.

---

### 5.4 CarouselWriter — the single LLM creative call

**Purpose:** Given `StoryContext` and `SlotPlan`, produce all slide text, caption, pinned comment, and hashtag themes in one Sonnet call with structured JSON output.

**Input:** `StoryContext` + `SlotPlan`

**Output:** `CarouselSpec` (full schema in section 6).

**Prompt architecture (system prompt sections, in order):**

1. **Role definition.** "Carousel writer for Anchor & Delta, an editorial intelligence brand. Compress finalised Story Cards into punchy, declarative carousels."

2. **Brand voice rules.** Direct, no specialist jargon without explanation, active voice, present tense for stakes, **no leading conjunctions** (no "But," "And," "However," "Meanwhile," "Now"), one point per slide, no hedging.

3. **Hook taxonomy.** Four patterns with examples and selection rules. Anti-patterns explicitly listed. See section 9.

4. **Domain vocabularies.** World runs on consequences/events/casualties; Finance runs on reframes/experts/deadlines/percent-moves; AI&Tech runs on named entities and second-order ironies. See section 9.

5. **Slot-role writing guides.** Each slot has a named job, word budget, and one or two example slides drawn from real Story Cards. See section 10.

6. **Hard constraints.**
   - Word limits per slot (see section 10)
   - For AI&Tech only: every slide should carry at least one named entity
   - Preserve structural contrasts when the card transmission has X-did-A / Y-did-B structure
   - Permitted to surface and reuse the card's strongest metaphor when slide-grade
   - No leading conjunctions
   - Single point per slide
   - Narrative thread comes from echo / setup-payoff / escalation / definite articles, never from connector words

7. **Output format.** Strict JSON matching `CarouselSpec` schema. Pydantic validates on receipt. Malformed JSON triggers one automatic retry, then surfaces to user.

8. **Pinned comment instruction.** After writing all slides, identify the single most screenshot-worthy sentence (typically from `payoff` slide) and restate it as `pinned_comment`. Standalone, no hashtags, no @mentions, no questions.

**Prompt versioning.** Every `CarouselSpec` records the `prompt_version` it was generated with. Prompt iteration is tracked; rollback is clean; A/B comparison on a fixed card set is possible.

**Why one call:** Voice consistency requires the model to see the full slide arc in one pass. Splitting into per-slide calls produces drift and wastes tokens re-establishing context.

**Cache:** Keyed by `(card_id, card_version, prompt_version, slot_plan_hash)`.

**Cost:** $0.025–0.035 per call. **Latency:** 4–7 seconds.

**Regenerate paths:**

- **Targeted slide regenerate (Model B).** Separate prompt mode. Takes the full `CarouselSpec` plus the `slot_id` to regenerate, plus the freeze-list of `manually_edited` slides. Output is a single `Slide` replacing the targeted one. Cost: approximately $0.008. Latency: 3–5 seconds.
- **Full script regenerate with instruction (Model A).** Takes original input plus free-text user instruction (e.g. "make the hook sharper", "less corporate"). Outputs a new full `CarouselSpec`. Cost: $0.025–0.035.
- **Inline text edit (Model C).** No LLM call. User types in Streamlit; `headline`/`body`/`caption` updated directly; `manually_edited=True`; affected slide re-rendered by Python. Cost: $0. Latency: <500 ms.
- **Caption-only regenerate.** Separate cheap Haiku call. Cost: approximately $0.002. Latency: ~2 seconds.

---

### 5.5 LayoutPicker

**Purpose:** Assign a layout template and styling parameters to each slide. Deterministic Python.

**Input:** `CarouselSpec`

**Output:** `EnrichedSpec` — same as `CarouselSpec` but each `Slide` is wrapped in a `LayoutChoice`:
- `template_id` — enum: `statement` | `number` | `quote` | `timeline` | `concept` | `hook` | `cta` (+ inert `portrait` slot for v1.5)
- `text_size_class` — literal: `xl` | `l` | `m` | `s` (based on text length)
- `accent_colour` — hex from domain palette
- `theme_variant` — literal: `dark` | `light` (default `dark` in v1)

**Template selection rules (evaluated in order):**

1. **[SEAM v1.5]** If `slide.image_asset` is not None and `slide.role` in {hook, anchor-equivalent} → `portrait` template. In v1.0, `image_asset` is always None, so this rule never fires.
2. If `slide.quote` is populated → `quote` template
3. Else if `slide.dominant_number` is populated → `number` template
4. Else if `slide.role == hook` → `hook` template
5. Else if `slide.role == event` → `timeline` template
6. Else if `slide.role in {mechanism, concept}` → `concept` template
7. Else if `slide.role == cta` → `cta` template
8. Else → `statement` template (the workhorse, expected to cover 50–60% of slides)

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

**Cost:** $0. **Latency:** ~250 ms per slide cold (render at 2×), ~5 ms per slide warm. Cold full carousel: ~2 seconds for 8 slides.

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

**Export action:** When user clicks "Approve & Sync" in Streamlit, the engine writes the bundle to a configured local directory that auto-syncs to phone via iCloud / Google Drive. Bundle contents:
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
└── dominant_numbers: list[DominantNumber]
    ├── value: str                        # rendered string e.g. "$2.3T", "1,430"
    ├── label: str                        # e.g. "dead"
    └── context: str                      # one-line explanation
```

### 6.2 SlotPlan (input to writer)

```
SlotPlan
└── slots: list[Slot]
    ├── slot_id: str                      # stable role-based, e.g. "hook", "timeline_1"
    ├── role: SlotRole                    # enum
    └── is_optional: bool
```

`SlotRole` enum: `hook | setup | event | pivot | mechanism | concept | proof | contrast | payoff | cta`

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

Every field below is either active in v1.0 (✅) or a forward-compatibility seam (⏳). Seams are `Optional[X] = None` and ignored by v1 components.

```
Slide
├── slot_id: str                          ✅ matches SlotPlan, e.g. "pivot"
├── role: SlotRole                        ✅
├── headline: str                         ✅ ≤8 words for hook, ≤14 words otherwise
├── body: str                             ✅ ≤25 words
├── emphasis_word: Optional[str]          ✅ single word for accent treatment
├── quote: Optional[SourcedQuote]         ✅ when slide IS a quote
├── dominant_number: Optional[Number]     ✅ when slide IS a number
├── text_hash: str                        ✅ for render cache
├── manually_edited: bool = False         ✅ true when user has edited inline
├── image_asset: Optional[ImageAsset]     ⏳ SEAM v1.5: portraits
│   ├── source: Literal["wikimedia", "upload", "ai_generated"]
│   ├── url: str
│   ├── treatment: Literal["duotone", "high_contrast", "raw"]
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
| **Writer output cache** | `(card_id, card_version, prompt_version, slot_plan_hash)` | Full `CarouselSpec` | Supabase `carousels` table (status='draft') |
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

### 9.1 Hook taxonomy — 4 patterns

The writer selects from these four. Pure questions, accusatory framing on World content, and witty setups as default are explicit anti-patterns.

| Pattern | Shape | Use when |
|---------|-------|----------|
| **Contrast** | "Action A. Then B." | Card has clear before/after or political-vs-physical dynamic |
| **Negative fact + reveal** | "X doesn't exist anymore. Y just found out." | Card hinges on something absent or broken |
| **Number shock** | "[Big number]. [Context that makes it land]." | Card has hook-grade number (1000+, $1B+, dramatic ratio) |
| **Insider declaration** | "[Counterintuitive fact stated flatly]. [Concrete subject]." | Card's core insight is non-obvious |

Hard constraints on every hook: ≤2 lines, ≤14 words total, must match one of the 4 patterns.

### 9.2 Domain vocabularies

| Domain | Drama vocabulary | Default arc shape |
|--------|------------------|-------------------|
| **World** | Actions with consequences, dated events, mass-casualty numbers, regime change, deposition dynamics | Consequence-chain |
| **Finance** | Named experts in unexpected positions, dated deadlines, dramatic percent moves, counterintuitive reframes | Reframe-centred |
| **AI & Tech** | Named entities (models, executives, agencies, products), structural ironies, second-order effects | Second-order irony |

These are hints, not hard rules. The writer applies the vocabulary that fits the card.

### 9.3 Named-entity density rule

For AI & Tech only: every slide should carry at least one named entity (model, person, company, agency, product). Vague references ("a company", "an executive") signal weakness. This rule does not apply to World or Finance, where entity density varies more naturally.

### 9.4 Structural contrast preservation

When a card's transmission contains explicit X-did-A / Y-did-B structure, the writer must preserve at least one contrast slide. Contrast is structural, not decorative — collapsing it weakens the carousel.

### 9.5 Metaphor reuse

The writer is permitted to surface and reuse the card's strongest metaphor as slide copy when the metaphor is slide-grade (e.g. "weapon disposal unit" → "defusing the bomb"). This is not plagiarism; it is voice continuity between card and carousel.

### 9.6 Narrative thread

Thread between slides comes from echoed language, setup-payoff pairs, escalation, and definite articles ("this", "that", "the"). It does **not** come from leading conjunctions. "But," "And," "However," "Meanwhile," "Now" as slide openers are banned. If a slide reads as disconnected, fix the slide content; do not add a connector word.

---

## 10. Template archetypes

Seven templates total. Designed by hand in HTML/CSS during template-design week.

| Template ID | Role | Used for | Word density |
|-------------|------|----------|--------------|
| **Statement** | Workhorse | Hook (when not number/quote), anchor, pivot, payoff | Medium |
| **Number** | Drama | Slides where a single figure carries the point | Low (figure dominates) |
| **Quote** | Authority | Slides where a sourced quote IS the point | Low (quote dominates) |
| **Timeline** | Event | Date-stamped delta event chapters | Medium |
| **Concept** | Framework | Mechanism slides (how something works), Concept slides (a framework) | Medium (text-dense) |
| **Hook** | Cover | Slide 1 only — visually distinct, signals "start here" | Very low |
| **CTA** | Closer | Final slide, fixed copy | Fixed |

**[SEAM v1.5]** An 8th template, `Portrait`, will be added in v1.5 for full-bleed treated portraits of named people. The `Slide.image_asset` field is already in the schema; the LayoutPicker selection rule already exists but never fires in v1.0.

### Slot-to-template default mapping

| Slot role | Default template |
|-----------|------------------|
| `hook` | Hook |
| `setup` | Statement |
| `event` | Timeline |
| `pivot` | Statement |
| `mechanism` | Concept |
| `concept` | Concept |
| `contrast` | Statement |
| `proof` | Number (or Statement if no dominant number) |
| `payoff` | Statement |
| `cta` | CTA |

Quote and Number templates override the default when the slide has a populated `quote` or `dominant_number` field.

### Word budgets per slot

| Slot | Headline | Body |
|------|----------|------|
| `hook` | ≤8 words | (none — hook is 2 lines headline only) |
| `setup`, `pivot`, `payoff` | ≤14 words | ≤25 words |
| `event` (timeline) | ≤10 words + date | ≤30 words |
| `proof` | the number + label | ≤25 words context |
| `quote slides` | (attribution above quote) | quote ≤30 words |
| `mechanism`, `concept` | ≤12 words | ≤45 words (denser than others) |
| `cta` | fixed: "Follow @handle for daily intelligence" | (none) |

---

## 11. Visual system — v1.0 typography only

### 11.1 Theme

**Warm dark theme. Single theme in v1.0.** Not pitch black — a cozy, dense dark that feels like a dimly lit library or aged leather, not a cold screen. Validated via rendered mockup and approved before template-design week begins.

Light theme variant is supported in the schema (`theme_variant`) but not used in v1.0.

**The single most important background decision:** background is warm near-black `#1A1612` (dark warm brown), not cold near-black `#0E0E0E`. Cold black feels harsh and digital. Warm dark brown feels editorial and considered. This hex is the foundation of the entire register.

### 11.2 Domain palettes

Three accents, one per domain. Locked starting values from mockup validation — fine-tune during template-design week:

| Domain | Accent | Starting hex | Rationale |
|--------|--------|--------------|-----------|
| World | Amber gold | `#C8813A` | Reads like candlelight on warm dark; red on warm brown muddy |
| Finance | Cool silver-white or muted teal | TBD | Needs contrast against World's warmth; something cooler |
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

### 11.4 Layout chassis (shared across all templates)

Every slide shares this skeleton — what makes the feed grid read as one body of work:

- Domain tag — top-left, accent colour, Inter 500, 9px at 1× (18px at 2×), letter-spacing 2px, uppercase
- Main content — vertically centred in remaining space, left-aligned
- Thin rule line — accent colour at 15–25% opacity, structural divider between headline and body. One per slide maximum.
- Page indicator — bottom-left, Inter 400, 9px at 1×, muted `#4A4540`
- Brand wordmark — bottom-right, "ANCHOR & DELTA", Inter 500, 9px at 1×, letter-spacing 1px, muted `#4A4540`

### 11.5 Slide-level typography scale

Sizes below are CSS pixel values at 1× canvas (1080px wide). Playwright renders at 2× so actual pixel size is double.

| Element | Font | Weight | CSS size | Colour |
|---------|------|--------|----------|--------|
| Headline | Playfair Display | 900 | 45–55px | Cream `#E8E0D0` |
| Accent / emphasis line | Playfair Display | 700 italic | 30–40px | Domain accent |
| Body text | Inter | 400 | 21–24px | Muted cream `#8A8078` |
| Date label | Inter | 500 | 18px uppercase | Muted `#4A4540` |
| Dominant number | Playfair Display | 900 | 60–80px | Domain accent |
| Number context label | Inter | 400 | 18px | Muted `#5A5248` |
| Footer (indicator + wordmark) | Inter | 400/500 | 16px | Muted `#4A4540` |

### 11.6 Rendering technical specifications

- Canvas: 1080×1350 (Instagram portrait 4:5)
- Render at 2160×2700 (2×), downscale to 1080×1350 for final output
- Self-hosted fonts loaded via `@font-face` — Playfair Display (700, 900) and Inter (400, 500)
- Background: warm dark brown `#1A1612`
- Body text: warm cream `#E8E0D0`
- Muted text: `#8A8078` for body context, `#4A4540` for footer and labels
- Subtle warm radial gradient overlay on background (amber at ~7% opacity) for depth — not imagery, just warmth
- Thin rule lines: accent colour at 15–25% opacity — structural, never decorative
- No drop shadows, no glow effects, no hard gradients on content elements

**Critical validation step:** After every template iteration during design week, render the PNG at full resolution and open on your actual phone. Not in the browser, not in Streamlit — on the phone, at full screen. Production at 1080×1350 on a modern iPhone is dramatically sharper and more impactful than any desktop preview. This is the only true quality gate.

---

## 12. Streamlit UI integration

A "Generate Carousel" button is added to every card in the existing dashboard.

### 12.1 Preview view

- Horizontal scroll of slide thumbnails (~270×340 each)
- Below: editable caption text box
- Below: hashtag list (displayed; resampled via button, not directly edited)
- Below: pinned comment text box

### 12.2 Per-slide controls

- ✏️ **Edit** — inline text edit, instant re-render via cache
- 🔄 **Regenerate this** — targeted Sonnet call (Model B)
- ⛔ **Lock** — toggles `manually_edited` flag, prevents overwriting in cascade regenerates
- 🖼️ **Add image** — disabled in v1.0 (tooltip: "Portrait support arrives in v1.5") — **[SEAM v1.5]**

### 12.3 Script-level controls

- 🔄 Resample hashtags (Python only, no LLM)
- 🔄 Regenerate caption (Haiku call only)
- 🪄 Tweak whole carousel (free-text instruction → full Model A regenerate)
- ✅ **Approve & Sync** — writes bundle to configured local directory
- 📤 **Publish to Instagram** — disabled in v1.0 (tooltip: "Direct publishing arrives in v2") — **[SEAM v2]**

### 12.4 Sync destination

User-configurable path in settings. Default: `~/iCloud Drive/AnchorDelta/Outbox/` on Apple; `~/Google Drive/AnchorDelta/Outbox/` otherwise. Engine has no knowledge of the sync layer; it just writes files to a configured directory.

---

## 13. Cost and latency profile

| Operation | Cost | Latency |
|-----------|------|---------|
| First generation (cold) | $0.030–0.040 | 7–10 s |
| Targeted slide regenerate | $0.008 | 3–5 s |
| Caption regenerate (Haiku) | $0.002 | 2 s |
| Inline edit + re-render | $0 | <500 ms |
| Full regenerate with instruction | $0.030–0.040 | 7–10 s |
| Resample hashtags | $0 | <50 ms |
| Cached generation (no change) | $0 | <200 ms |

**Steady-state target:** 1.0–1.3 LLM call sequences per approved carousel.

At 3 carousels/day, that is approximately $0.12–0.15/day, ~$4–5/month. Negligible.

---

## 14. Roadmap — v1.0, v1.5, v2

### v1.0 — ships in approximately 3 weeks

Everything in this document. Typography-only carousels with all upgrade seams wired in but inert.

### v1.5 — planned, decided after week 7 review

Two specific additions:
- **Portrait template** activated. `image_asset` field becomes usable. New asset pipeline (~200 lines of Python) — Wikimedia API fetch + duotone treatment in Pillow. LayoutPicker rule already exists; just turn it on.
- **Domain prompt tuning** based on real performance data from weeks 3–7.

### v2.0 — planned, decided after meaningful post volume (50+ posts)

Three additions:
- **Reels companion generation.** For each approved carousel, generate a 30-second Reel using: condensed script from CarouselSpec, ElevenLabs voiceover with pronunciation overrides, synced captions, hook-slide ken-burns background. Same approval, dual output.
- **Editorial imagery slot.** When the card has a specific evocative location/event/object that isn't a person, use the Image-anchor template with treated editorial photography (Wikimedia or licensed source).
- **Instagram Graph API publishing.** Publisher component replaces sync-to-folder. The `status='approved'` action becomes `Publisher.publish()`.

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
