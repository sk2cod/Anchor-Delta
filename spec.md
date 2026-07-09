# Cover Slide Overhaul — Phase A Spec
**Project:** Anchor & Delta Instagram Carousel Engine
**Date:** 2026-07-09

---

## What We're Building

A test script that previews a new cover slide format on real story cards from Supabase. Nothing in the production pipeline changes. Clicking Streamlit still runs the old system.

The test script already exists at `tests/carousel/test_new_cover.py`. This spec describes what needs to change and why.

---

## The Problem

The current cover output has three issues found through real viewer testing:

**1. Headlines are not punchy or specific enough.**
"The ocean is the new battlefield. No one can see it." — a viewer has no idea what story this is about. It's evocative but useless as a hook.

**2. Sub-heading was removed but shouldn't have been.**
The sub-heading isn't the problem — incoherence between headline and sub-heading was. When they work as a unit they're stronger than headline alone.

**3. AI-generated images are unrelated to the actual story.**
The image generation uses a generic entity label ("Ukraine", "Canada") which produces stereotyped imagery unrelated to the specific story being told.

---

## The Target Format

Study @daily.ai.co on Instagram. Their cover format:

- **Headline:** One punchy line. Specific. Dramatic. Stops the scroll.
- **Sub-heading:** One sentence that completes the headline with the specific detail.
- **Image:** Visually relevant to the actual story — not a country flag or generic scene.

Examples of what good looks like:

| Headline | Sub-heading |
|---|---|
| "THREE NEW MODELS DROP TOMORROW" | "GPT-5.6 Sol, Terra, and Luna go public Thursday." |
| "OPENAI JUST BUILT A SCIENCE EXAM FOR AI" | "GeneBench-Pro tests whether AI can handle real-world genomics." |
| "AI TOLD THE WORLD JIM CARREY WAS DEAD" | "He's alive. The AI was wrong. And millions almost believed it." |

The headline and sub-heading together are one continuous thought. Neither repeats the other. The headline creates the hook; the sub-heading delivers the specifics.

---

## What Needs to Change

### 1. Headline rule in `carousel/prompts/writer_v1_6.md`

**Current problem:** Writer produces two-sentence headlines or abstract evocative lines with no specificity.

**New rule:** One line only. Maximum 8 words. Must name the specific subject (country, person, technology, event). Must be the most dramatic or surprising fact about the story stated directly — not implied. No two-sentence structure. No colons introducing a twist.

Good: "Putin's 'victory' is 97 square kilometres of mud."
Good: "Macron just walked into Syria uninvited."
Good: "China's best AI model is now legal in Europe."
Bad: "The ocean is the new battlefield. No one can see it." — abstract, two sentences, no specific subject.
Bad: "Ukraine found a weapon Russia can't shoot down: economics." — colon = two beats.

Include these examples verbatim in the prompt so the model calibrates correctly.

### 2. Sub-heading re-introduced in `writer_v1_6.md` and the test template

**Rule:** One sentence, maximum 15 words, that answers "what exactly happened?" — the specific detail the punchy headline deliberately left out. Must not repeat the headline. Must complete it.

The writer prompt should return all three fields: `headline`, `emphasis_word`, `sub_heading`.

The template needs a sub-heading element below the thin rule, visually subordinate to the headline (smaller, muted).

### 3. Image generation uses story-specific visual subject

**Current problem:** Script passes a generic entity label to DALL-E. "Ukraine" → generic war scene. "Canada" → random submarine.

**New approach:** Before generating the image, make a quick Anthropic API call asking the model to identify the most visually distinctive and story-specific element — not the country or entity name, but what a documentary filmmaker would actually put on screen for this story. Use that as the DALL-E subject.

For stories with a named individual as the central figure → pencil sketch / editorial illustration portrait style (as validated in previous test).
For stories about events, objects, places, or concepts → cinematic editorial dark image style.

Domain colour palette stays the same (world=amber, finance=silver, ai_tech=cyan) applied as duotone.

---

## Files to Change

| File | What changes |
|---|---|
| `carousel/prompts/writer_v1_6.md` | Rewrite headline rule (1 line, max 8 words, specific) + add sub_heading to output schema |
| `tests/carousel/templates/test_new_cover.html` | Add sub_heading element below the thin rule |
| `tests/carousel/test_new_cover.py` | Add visual subject derivation step before DALL-E; parse sub_heading from writer response |

## Files That Must Not Change

Everything in `carousel/` except `carousel/prompts/writer_v1_6.md`. Production writer, planner, templates, assembler — all untouched.

---

## Acceptance Criteria

Run `python tests/carousel/test_new_cover.py`. Script fetches most recent card per domain from Supabase (world, finance, ai_tech) and outputs three PNGs to `outputs/renders/`.

Script must also print to terminal: the generated headline, sub_heading, and derived visual subject for each card — so quality can be checked before even opening the PNG.

A good result:
- Headline names the story subject and lands a surprise in one punchy line
- Sub-heading completes the headline with the specific fact
- Image is visually relevant to the actual story content
- Layout unchanged from previous run (confirmed good)
