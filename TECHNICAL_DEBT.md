# Technical Debt

Confirmed issues found during development, recorded so they survive between
sessions. Only items with direct evidence belong here — no speculation. When an
item is fixed, delete it and note the fix in `CHANGELOG.md`.

Each entry records what is wrong, how it was confirmed, and what closing it
requires.

## P0 – Must fix before beta

### Production-only image generation failure

Canon · Recommended image generation fails on the published app
(`storyseed-2026.replit.app`) while the identical path succeeds in development.

- **Symptom:** the UI shows the bare string `Something went wrong`.
- **What that proves:** that string is only produced by
  `frontend/src/features/characterCreation/shared/api.ts:36`, in the branch
  where the response is non-2xx **and its body fails to parse as JSON**. Every
  FastAPI `HTTPException` serialises to JSON, and `backend/app/main.py:129`
  registers no 500 handler, so the response was either an unhandled exception
  (Starlette's plain-text `Internal Server Error`) or a gateway 502/504.
- **Ruled out with evidence:** model ID and availability (`gemini-3.1-flash-image`
  returned HTTP 200 with image bytes in 6.3 s), credentials, response parsing,
  SPA fallback masking (`main.py:291` is GET-only and returns JSON 404 for
  `/api`), route registration (unauthenticated POST returns JSON 403), and
  provider gating.
- **Also ruled out since:** storage mode is *not* an environment difference.
  `USE_OBJECT_STORAGE` is unset in both dev and production (`config.py` default
  `False`; `start-prod.sh` exports only `PYTHONUNBUFFERED`, `PYTHONPATH`,
  `SERVE_FRONTEND_DIST`), so both write to local disk and the R2 branch of
  `save_image()` is unreachable. R2 credentials exist but R2 is dormant.
- **Still open:** which stage throws. Needs a live production reproduction with
  deployment logs attached — not reproducible from the workspace, as production
  logs and the production database are unreachable from here.
- **Remaining candidates:** the Cloud Run target's ephemeral memory-backed
  filesystem, its request timeout, or its memory ceiling. A Canon generation
  loads up to six reference images (largest on disk is 3.2 MB), base64-encodes
  them (×1.33) and builds a JSON payload — several multiplied copies live at
  once — and may repeat that twice more under face-verify retries
  (`GOOGLE_IMAGE_TIMEOUT_S=180`, `IDENTITY_FACE_VERIFY_MAX_RETRIES=2`).
- **Diagnosis is now instrumented.** The next production failure will identify
  its own stage: the route emits `IMAGE_GEN_START` → `IMAGE_GEN_BYTES_RECEIVED`
  → `IMAGE_GEN_STORAGE_START` → `IMAGE_GEN_STORAGE_OK` →
  `IMAGE_GEN_DB_WRITE_START` → `IMAGE_GEN_DB_WRITE_OK`, and any unhandled
  exception now returns JSON carrying a `request_id` that matches a full
  server-side traceback. A `START` with no matching `OK` localises the fault
  without needing a traceback at all.

### 1.9 GB of generated images ship in every deployment image

`backend/static/generated/` holds 34,387 PNGs totalling 1.9 GB. `.gitignore`
excludes it, but **`.replitignore` does not**, so the whole directory is packaged
into every deployment. It inflates build and deploy time and bloats the runtime
image. Runtime writes land in the same directory, which on the Cloud Run target
is ephemeral — anything written there is also lost on restart.

## P1 – Closed beta

### Unhandled exceptions returned unparseable plain-text 500s

**Fixed — pending verification in production.** `backend/app/main.py` registered
a handler only for `RateLimitExceeded`, so every other unhandled exception got
Starlette's default plain-text `Internal Server Error`. Frontend clients parse
error bodies as JSON, so that body failed to parse and any real backend fault
was flattened into a generic "Something went wrong" — on every route, not just
image generation. It is the single biggest reason the P0 above took so long to
localise.

`unhandled_exception_handler` now returns JSON `{detail, request_id}` plus an
`X-Request-ID` header. The public payload is deliberately generic — no exception
type, message, or traceback, since those carry file paths and connection
strings — while the full traceback is logged server-side under the same
`request_id`, so a user-reported id maps to an exact stack.

Note: Starlette prefers its HTML debug page when `app.debug` is True, so this
handler governs production (`DEBUG=False`) while local dev keeps the interactive
traceback.

### Preserve Google image MIME type instead of forcing PNG

**Fixed — pending verification in production.** Gemini image models return
`inlineData.mimeType = image/jpeg`, but `backend/app/core/storage.py` hardcoded
`<uuid>.png` and `ContentType="image/png"`, so every Gemini image was JPEG bytes
stored and served as PNG. `save_image()` now sniffs the format from magic bytes
and stores the correct extension and Content-Type, without transcoding.

Historical rows written before this fix still carry `.png` paths containing JPEG
bytes. They render (browsers sniff content) and no backfill is planned, but
anything that trusts the extension rather than the bytes must account for them.

### Evidence-based provenance system (User Written / AI Assisted)

The current authorship badge is decorative, not evidential, and the sprint to
replace it is paused at the investigation stage. Confirmed findings:

- No frontend composer sends `source_type`, so every post silently takes the
  Pydantic default `user` (`backend/app/schemas/post.py:26`) and renders
  "✍️ User Written". The label has never encoded anything.
- `source_type` is forgeable — `backend/app/api/routes/posts.py:129` does
  `PostModel(**post_data.model_dump())` and
  `backend/app/api/routes/story_spaces.py:328` does `source_type=body.source_type`,
  both unvalidated.
- Real AI evidence exists but is disconnected from the public badge:
  `RPStoryTurn.generated`, `StoryChapter.generated_text`, `GenerationLog`,
  `GenerationTelemetry`.
- Story Space publication loses provenance entirely —
  `PublishedStorySegment` (`backend/app/models/story_space.py:140`) has no
  source field.
- No paste detection exists anywhere (zero `onPaste` handlers), while WriteSpace
  actively routes users through a paste into the Home composer.
- Editor Studio is image-only and out of scope for text provenance.

The data-model decision (inline columns via mixin vs. a central polymorphic
table) is open and deliberately unanswered.

### Alembic has nine heads

`alembic upgrade head` — the command documented in `DEV_SETUP.md:30`,
`replit.md:87` and `README.md:106` — fails with "Multiple head revisions are
present". Migrations are run manually; nothing runs them at startup. This must
be resolved deliberately before any new migration is added, including the
provenance migration above.

## P2 – Future improvements

### Founder-quality Gemini Pro image option

`gemini-3-pro-image` is confirmed available on the configured key (stable, not
preview) and supports `generateContent`. Worth exposing as a founder/admin
quality tier alongside Canon · Recommended, with `gemini-2.5-flash-image` as an
economical fallback. Purely additive — the current pinned
`gemini-3.1-flash-image` default is correct and carries no deprecation debt.
