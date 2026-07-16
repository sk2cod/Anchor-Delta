# Anchor & Delta — Hosting & Infrastructure Decisions Log

Living record of architectural decisions for hosting, deployment, and
infrastructure. Sibling log to `CAROUSEL_DECISIONS.md` — kept separate on
purpose.

**Scope:** hosting, deployment, infra, and environment decisions only.
Carousel content, rendering, and prompt decisions keep going in
`CAROUSEL_DECISIONS.md` — the two logs are never merged.

**Format:** Decision / Date / Why / Alternatives considered / Status

**Status values:** `Active` · `Active / In Progress` · `Superseded by #N` ·
`Open` · `Deferred`

**Rules of the log:**
- Every infra/deployment decision is recorded here before it's carried out
- When a decision is superseded, it is not deleted — it is marked
  superseded and linked to the new decision
- The log is updated as we go, not retroactively

---

## #01 — Dockerize the existing Streamlit app and redeploy to Railway

**Date:** 2026-07-16
**Decision:** Move hosting from local-only Streamlit (see
`ARCHITECTURE_SNAPSHOT.md` §4 for the frozen pre-migration baseline) to the
same Streamlit application, packaged in a Docker container with a custom
Dockerfile, deployed on Railway. This is **not** a rewrite: same
`ui/app.py` entry point, same `streamlit run` execution model, same
Pydantic contracts, same Playwright/Chromium slide renderer. The only
thing changing is where the container running that app lives.
**Why:** The constraint blocking any hosted deployment today is narrowly
Streamlit Cloud's managed container — it doesn't allow installing
system-level packages, and Playwright's headless Chromium renderer needs
real system-level Chromium dependencies (`DESIGN_LESSONS.md` §14,
`CAROUSEL_DECISIONS.md` Decision #50). The constraint is that specific
managed container, not Streamlit-the-framework and not Playwright itself.
Railway allows a custom Dockerfile, which means real system Chromium deps
can be installed exactly as they are on the local dev machine today.
Solving the actual constraint this way avoids touching working application
code, working UX, or the render pipeline's typography (locked per Blueprint
§11.3) — all of which a framework rewrite would put at risk for zero
corresponding benefit.
**Alternatives considered:**
- **(B) Full Next.js/Vercel frontend + FastAPI/Railway backend rebuild.**
  Rejected. This would be an unnecessary rewrite of a UI and interaction
  model that already works — every carousel-preview, inline-edit, and
  regenerate flow in `ui/carousel_view.py` would need to be rebuilt from
  scratch in a new framework for no functional gain, and introduces new
  rewrite risk (new bugs, new UX regressions) purely to solve a hosting
  problem that doesn't require touching the frontend at all.
- **(C) Serverless slide renderer via Satori or `@sparticuz/chromium`.**
  Rejected. Two independent problems with this path: it risks the locked
  slide typography (Playfair Display + Inter, self-hosted fonts, exact
  kerning/line-height — Blueprint §11.3, Decisions #42/#43/#45) which was
  validated against real Playwright/Chromium rendering and is not
  guaranteed to reproduce identically under Satori's or a serverless
  Chromium shim's rendering engine. It also doesn't fit the actual usage
  pattern — real volume is ~3 carousels/day (solo daily use, Decision
  #38/#40), nowhere near the scale where serverless's per-invocation cold
  starts and packaging complexity would pay for themselves over a single
  always-on Railway container.
**Status:** Active / In Progress
