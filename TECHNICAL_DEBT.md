# Technical Debt

Confirmed issues found during development, recorded so they survive between
sessions. Only items with direct evidence belong here — no speculation. When an
item is fixed, delete it and note the fix in `CHANGELOG.md`.

Each entry records what is wrong, how it was confirmed, and what closing it
requires.

## P0 – Must fix before beta

### Production-only image generation failure — ROOT CAUSE PROVEN, fix pending verification

**Proven in production** on `POST /api/characters/58/image-generator/generate`
(`request_id=234f0c783520`): `ModuleNotFoundError: No module named 'boto3'`,
HTTP 500.

Production runs with **`USE_OBJECT_STORAGE=true`** — proven by the traceback
itself, since boto3 is imported only inside the object-storage branches of
`app/core/storage.py` (`save_image` line 63, `_r2_client` line 123). boto3 was
never declared in `backend/requirements.txt`, so the deployment installed into
`.deploy-python` without it, while dev kept a copy in `.pythonlibs` — which
`.replitignore` excludes from the deployment. That is the entire dev/prod
divergence.

A second defect made it unreadable. `_load_from_r2`'s error handler extracted the
S3 error code with
`getattr(getattr(exc, "response", None), "get", lambda *_: None)("Error", {}).get("Code", "?")`,
which yields `None` for any exception without a botocore-style `.response` and
then calls `.get` on it. The handler itself raised
`AttributeError: 'NoneType' object has no attribute 'get'`, replacing the real
`ModuleNotFoundError` at all six reference loads. Diagnostics outranked the error
they described.

Both are fixed on branch and pending production verification: boto3 is pinned in
requirements, the error handler extracts defensively and logs `exc_type`, and a
canon generation whose references *all* fail now returns a safe 503 instead of
silently producing an identity-weak image.

**Superseded hypotheses**, recorded so they are not re-investigated: Google model
ID/availability, credentials, response parsing, SPA fallback masking, route
registration, provider gating, request timeout, container OOM, and the earlier
claim that production used local filesystem storage. That last one was wrong —
it came from reading the *workspace* shell environment and `start-prod.sh`, which
do not carry Replit deployment secrets.

### Lesson for the next environment-specific incident

The original symptom was the bare string `Something went wrong`, produced only by
`frontend/src/features/characterCreation/shared/api.ts:36` when a non-2xx
response body fails to parse as JSON. That correctly narrowed the fault to "an
unhandled exception or a gateway error", but the investigation then stalled for
several rounds on a wrong premise.

**The wrong premise:** production storage mode was read from the *workspace*
shell environment and `start-prod.sh`, both of which showed `USE_OBJECT_STORAGE`
unset, and the conclusion drawn was that production used local filesystem
storage. It does not — it runs with object storage enabled. Replit **deployment**
secrets are configured separately from the workspace and are not visible to a
shell in the workspace, so no amount of local inspection could have shown the
real value.

**What to do instead:** never infer a deployment's configuration from the
workspace. Read it from the deployment itself, or make the running app report it
(a redacted diagnostics endpoint), or prove it from a production traceback as
happened here. Treat "dev works, production doesn't" as a signal to compare
*installed dependencies and deployment config*, not application logic.

### 1.9 GB of generated images ship in every deployment image

`backend/static/generated/` holds 34,387 PNGs totalling 1.9 GB. `.gitignore`
excludes it, but **`.replitignore` does not**, so the whole directory is packaged
into every deployment. It inflates build and deploy time and bloats the runtime
image. Runtime writes land in the same directory, which on the Cloud Run target
is ephemeral — anything written there is also lost on restart.

## P1 – Closed beta

### Unhandled exceptions returned unparseable plain-text 500s

**Fixed and PRODUCTION-VERIFIED.** Confirmed working on the live deployment:
`request_id=234f0c783520` was returned to the client and matched the logged
traceback exactly, which is what identified `ModuleNotFoundError: No module named
'boto3'` and closed the P0 above. The handler did its job on first use.

`backend/app/main.py` registered
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
