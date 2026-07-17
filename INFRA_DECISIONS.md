# Anchor & Delta — Hosting & Infrastructure Decisions Log

Living record of architectural decisions for hosting, deployment, and
infrastructure. Sibling log to `CAROUSEL_DECISIONS.md` — kept separate on
purpose.

**Scope:** hosting, deployment, infra, and environment decisions only.
Carousel content, rendering, and prompt decisions keep going in
`CAROUSEL_DECISIONS.md` — the two logs are never merged.

**Format:** Decision / Date / Why / Alternatives considered / Status

**Status values:** `Active` · `Active / In Progress` · `Completed` ·
`Superseded by #N` · `Open` · `Deferred`

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
**Status:** Completed

**Follow-up (2026-07-17):** The Docker/Railway approach itself needed no
changes — both real problems hit on the first deploy attempt were
branch/process issues, not a flaw in this decision. Railway was building
from `main`, which had no `Dockerfile` on it yet, and separately
`railway-migration-stage1` existed only in the local working copy and had
never been pushed to GitHub, so Railway could not have built from it even
if pointed there. Once the branch was pushed to GitHub and Railway was
pointed at it, the build and an in-container Playwright render succeeded
on the first real attempt — the Dockerfile / `playwright install
--with-deps chromium` approach worked exactly as designed once Railway
was actually building the right branch. (Railway's connected branch was
later repointed again, to `main` — see Decision #05.)

---

## #02 — Google Drive upload via user-delegated OAuth2, not a service account

**Date:** 2026-07-17
**Decision:** "Approve & Sync" uploads the export bundle directly to Google
Drive via the Drive API (`carousel/drive_sync.py`), authenticated as the
user's own Google account through a one-time OAuth2 consent flow
(`scripts/get_drive_refresh_token.py`) that yields a long-lived refresh
token. Scope is `drive.file` — the narrowest scope that can create and
manage files, restricted to files/folders the app itself created. Uploads
go into a new folder named exactly `"Anchor & Delta - Railway"`, created
via the API on first run and cached thereafter via `GOOGLE_DRIVE_FOLDER_ID`
— not the pre-existing local `"Outbox"` folder `CAROUSEL_SYNC_DIR` points
at today. This upload path is independent of `CAROUSEL_SYNC_DIR`: when the
three `GOOGLE_OAUTH_*` env vars are all present, `CAROUSEL_SYNC_DIR` is not
consulted at all; when any is missing, the existing local
`outputs/bundles/`/`CAROUSEL_SYNC_DIR` write behaves exactly as before,
unchanged.
**Why:** A Railway container has no local filesystem that syncs to Google
Drive the way a desktop Drive-sync client does on the current local-only
setup — `CAROUSEL_SYNC_DIR` is a path on a machine with Google Drive for
Desktop installed, which a container will never have. The Drive API is the
only way to actually reach Drive from inside the container. A **service
account** was the first design considered and rejected immediately on a
hard constraint, not a preference: personal Gmail accounts (this project's
account) give service accounts a **0GB Drive storage quota** — every
upload would fail outright regardless of code correctness, because service
accounts only get real storage on Google Workspace domains, not personal
accounts. User-delegated OAuth2 (the account's own quota, via a refresh
token obtained once through a real consent screen) is therefore not just
preferred but the only working option for a personal account. `drive.file`
scope (rather than broader `drive` scope) was chosen so the app can never
see or touch the user's other Drive content, including the existing
`CAROUSEL_SYNC_DIR`-linked `"Outbox"` folder — which is precisely *why* a
new app-created folder is required rather than reusing that one: a
`drive.file`-scoped token has no visibility into any folder it didn't
create itself, "Outbox" included.
**Alternatives considered:**
- **Service account with domain-wide delegation or a shared Workspace
  drive.** Rejected: this is a personal Gmail account, not a Google
  Workspace domain — there is no admin console to grant domain-wide
  delegation and no shared drive to delegate into. Not applicable, not
  just undesirable.
- **Broader `drive` scope, reusing the existing `"Outbox"` folder.**
  Rejected: would require the much broader `drive` (or `drive.readonly`
  variants) scope just to locate a pre-existing, human-created folder by
  name — `drive.file` cannot see it — trading a meaningfully larger
  attack surface (visibility into the user's entire Drive) for the sole
  convenience of reusing one folder name instead of creating a new one.
- **Mounting a synced local folder inside the container (e.g. `rclone
  mount`, a Drive FUSE layer).** Rejected: adds a background daemon and a
  new failure mode (mount drops, sync lag) to what the Drive API handles
  as a single, stateless authenticated HTTP call per file — no meaningful
  benefit for ~3 uploads/day.
**Status:** Active / In Progress

**Follow-up (2026-07-17):** Two issues surfaced during real-world testing,
both fixed without revisiting the OAuth2-vs-service-account reasoning
above: (a) the first working version of `upload_bundle()` uploaded files
flat into the top-level `"Anchor & Delta - Railway"` folder instead of a
per-carousel subfolder — a regression against the old `CAROUSEL_SYNC_DIR`
behaviour, which always wrote one subfolder per bundle. Fixed by having
`upload_bundle()` create a subfolder named after the bundle directory
(the same `YYYY-MM-DD_domain_slug` name already used locally) before
uploading into it. (b) Leaving `GOOGLE_DRIVE_FOLDER_ID` unset across
multiple test runs caused `get_or_create_folder()` to create a new
top-level folder on every run instead of reusing one, since there was
nothing yet to read back. The folder ID must be captured from the logs
after the first successful run and set as `GOOGLE_DRIVE_FOLDER_ID` to
avoid accumulating duplicate top-level folders.

---

## #03 — Persistent volume for outputs/ (Stage 2)

**Date:** 2026-07-17
**Decision:** A Railway volume was created and mounted at `/app/outputs`,
covering all four runtime write paths identified in the earlier audit:
the render cache (`outputs/renders/`), cover images
(`outputs/cover_images/`), the hashtag rotation log
(`outputs/hashtag_rotation.json`), and the local Approve & Sync bundle
fallback (`outputs/bundles/`).
**Why:** All four paths already had defensive
`mkdir(parents=True, exist_ok=True)` guards in place (confirmed in an
earlier audit of `carousel/renderer.py`, `carousel/image_generator.py`,
`carousel/cache.py`, and `carousel/assembler.py`), so no code changes were
needed to make the volume work — the container writes to `/app/outputs`
exactly as it always has; the only change is that path now persisting
across restarts and redeploys instead of resetting to an empty directory
each time.
**Alternatives considered:**
- Leave `/app/outputs` as ephemeral container storage and rely solely on
  the Google Drive upload (Decision #02) as the only durable output.
  Rejected: Drive upload only covers finished export bundles, and only
  when the `GOOGLE_OAUTH_*` vars are set — it does nothing for the render
  cache or cover-image intermediates the app depends on between
  generation and Approve & Sync, and the local bundle fallback still
  needs a durable directory when Drive isn't configured.
**Verification:** Wrote a test file via Railway's Console, triggered a
real redeploy (confirmed by a changed container ID, not just a
config-only "changes to apply" deploy with no new container), and
confirmed the file survived the redeploy.
**Status:** Completed

---

## #04 — Password gate via shared APP_PASSWORD, not a multi-user auth system

**Date:** 2026-07-17
**Decision:** A shared-password gate in `ui/app.py`, checked against an
`APP_PASSWORD` env var via `secrets.compare_digest()` (not `==`). Fails
open when `APP_PASSWORD` is unset (local dev — no gate at all, unchanged
from before Stage 4) and fails closed when it is set (any public
deployment).
**Why:** This app has no separable backend surface to defend — Streamlit's
UI *is* the entire application, unlike a split frontend/backend
architecture where the backend independently verifies every request
regardless of what the frontend shows. A shared password in front of the
one process that exists is sufficient; a real multi-user auth system would
be defending a boundary this app doesn't have.
**Alternatives considered:**
- A real multi-user auth system (e.g. Supabase Auth). Rejected: this is a
  solo-use app with one intended user, and there is no independent backend
  API surface for per-user sessions to actually gate — the complexity of
  user accounts, sessions, and token verification would add real
  engineering cost for a boundary that doesn't exist here.
**Verification:** `APP_PASSWORD` set independently in two separate secrets
stores — Railway's Variables tab and Streamlit Cloud's Secrets (TOML,
root-level key so it also mirrors into `os.environ`) — and the gate
verified end-to-end on both deployments.
**Status:** Completed

---

## #05 — Branch unification: main feeds both deployments

**Date:** 2026-07-17
**Decision:** `railway-migration-stage1` was merged into `main` via a real
merge commit (`--no-ff`, full commit history preserved — not squashed or
rebased), and Railway's connected branch was repointed from
`railway-migration-stage1` to `main`. From this point, a single branch
(`main`) feeds both the Streamlit Cloud deployment and the Railway
deployment.
**Why:** Two long-lived branches tracked by two different deployment
targets would require every future change to be manually forward-ported to
both, with the two deployments silently drifting apart the moment either
one was updated and the other forgotten.
**Alternatives considered:**
- Keep `railway-migration-stage1` as a permanent branch, with Railway
  tracking it indefinitely while Streamlit Cloud continues tracking
  `main`. Rejected: makes divergence the default outcome rather than an
  exception — every change would need deliberate duplication across both
  branches instead of a single push updating both deployments.
**Status:** Completed
