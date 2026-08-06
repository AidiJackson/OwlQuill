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

**Fixed in commit `4e956f9`, pending production verification:**

- `boto3==1.42.96` explicitly declared in `backend/requirements.txt` (botocore,
  jmespath and s3transfer arrive transitively and are not imported directly, so
  they are deliberately unpinned).
- `_load_from_r2`'s error handler extracts the S3 code defensively and logs
  `exc_type`, so a non-`ClientError` can never mask the real fault again.
- Reference loading emits `IMAGE_GEN_REF_LOAD_START` / `_OK` / `_FAILED` /
  `_SUMMARY` with requested and loaded counts, with query strings stripped so a
  signed URL cannot leak its credential.
- A canon generation whose references *all* fail now returns a safe **503**
  ("Character reference images could not be loaded. Please try again.") before
  any provider call, instead of silently generating an identity-ungrounded image.
  Partial loads still proceed.

Verified from a clean deployment-style install (`pip install --target`, with dev
`.pythonlibs` excluded from `sys.path`): boto3 resolves, `app.core.storage`,
`app.api.routes.image_generator` and `app.main` all import, and `_r2_client()`
reaches boto3 and fails only on the absent env var. 150 focused backend tests,
148 frontend tests, `tsc --noEmit` and the production build were all green at
commit time.

Closing this item requires one production generation on the republished build.

**Superseded hypotheses**, recorded so they are not re-investigated: Google model
ID/availability, credentials, response parsing, SPA fallback masking, route
registration, provider gating, request timeout, container OOM, and the earlier
claim that production used local filesystem storage. That last one was wrong —
it came from reading the *workspace* shell environment and `start-prod.sh`, which
do not carry Replit deployment secrets.

### 1.9 GB of generated images ship in every deployment image

`backend/static/generated/` holds **34,387 files totalling 1.9 GB**. `.gitignore`
excludes it (line 236) so **0 of those files are git-tracked**, but
**`.replitignore` has no matching rule**, so Replit packages the whole directory
into every deployment. It inflates build and deploy time and bloats the runtime
image. Runtime writes land in the same directory, which on the Cloud Run target
is ephemeral — anything written there is also lost on restart.

**Cannot be excluded yet — a dependency check is outstanding.** Production runs
with `USE_OBJECT_STORAGE=true`, so newly generated images go to R2, but any
*legacy* row whose `file_path` is a relative `static/generated/...` path is still
read from local disk by `load_image_bytes` and served from the deployed folder.
Excluding the directory would break exactly those rows.

A read-only audit of the **dev** database (`helium/heliumdb`) found:

    character_images total     1323
      https / R2 paths         1303
      local static/generated     20

so even in dev, 20 rows still resolve locally. **The production Neon database has
not been audited** — its credentials are not available in the workspace, and the
workspace `DATABASE_URL` points at the dev Postgres, not Neon.

Required before any `.replitignore` change:
1. Run the same read-only count against production Neon.
2. If any local-path rows exist, copy those objects to R2 and update the rows
   (idempotent, verify-before-update, retain originals).
3. Only then add the exclusion, and re-measure the bundle.

### Historical images: JPEG bytes stored under .png

Distinct from the MIME fix below, which only corrects *new* writes. A read-only
magic-byte scan of all 34,387 local objects found:

    png bytes, .png name     34034   (99.0%)  correct
    jpeg bytes, .png name      353   ( 1.0%)  MISMATCH
    unreadable                   0

All 1,323 dev `character_images` rows carry a `.png` extension, consistent with
the pre-fix behaviour of always naming files `.png`.

**R2 objects have not been audited** — that needs controlled downloads against
production and has deliberately not been run. Browsers content-sniff, so these
render; the risk is to anything that trusts the extension or the stored
`Content-Type`. No repair tool has been written yet; when it is, it must be
dry-run by default, copy-and-verify before updating any row, and never delete
originals in the first pass.

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

**Built — pending review and deployment.** Every finding recorded here was
confirmed and is now addressed on `feature/provenance-sprint`.

What was wrong: the badge defaulted to "✍️ User Written" for every post, was
client-settable (`PostModel(**post_data.model_dump())`, `source_type=body.source_type`),
was applied retroactively to historical NULL rows by the client's `?? 'user'`
fallback, and was dropped entirely by Story Space publication. Meanwhile real AI
evidence existed (`RPStoryTurn.generated`, `GenerationLog`, `StoryChapter`) and
reached nothing public.

What replaced it:

- Inline provenance columns via `ProvenanceMixin` on all seven content tables,
  written by the same `INSERT` as the content. Migration `prov01_provenance`.
- One decision service, `app/services/provenance.py`, called by every create
  route; no route decides for itself and no create schema carries a verdict.
- AI output fingerprinting (`ai_output_fingerprints`) — generators register
  shingle hashes of their own output, so pasting StoryLab text into the Commons
  composer is labelled server-side regardless of client behaviour. Author-scoped.
- Composition sessions (`composition_sessions`) as shared editor infrastructure,
  with `state_json` reserved for autosave / revisions / collaboration.
- Paste detection by field-length diffing. `clipboardData.getData()` is never
  called anywhere in the client — see `frontend/src/lib/composition.ts`.
- Historical rows are `unknown` with `provenance_rule_version = 0` and render no
  badge. Deliberately **not** backfilled to `user_written`.

Known follow-ups, none blocking:

- The retired `source_type` columns on `posts` and `story_space_posts` are left
  in place for rollback safety and should be dropped in a later revision.
- `EXTERNAL_VERDICT` in the provenance service resolves to `UNKNOWN`. Externally
  pasted text and RP partner imports already carry a distinguishing evidence
  `basis`, so enabling a dedicated state is a constant, a badge entry and a
  re-decide pass — no migration.
- No sweep exists yet for abandoned composition sessions or for fingerprints past
  the 90-day retention window. Both tables are indexed on `created_at` for it.
- Editor Studio is image-only and remains out of scope for text provenance.

## P2 – Future improvements

### Founder-quality Gemini Pro image option

**An optional enhancement, not a defect.** `gemini-3-pro-image` is confirmed
available on the configured key (stable, not preview) and supports
`generateContent`. Worth exposing as a founder/admin quality tier alongside
Canon · Recommended, with `gemini-2.5-flash-image` as an economical fallback.
Purely additive — the current pinned `gemini-3.1-flash-image` default is correct
and carries no deprecation debt.

## Withdrawn findings

Claims previously recorded here that turned out to be false. Kept so they are not
rediscovered and re-investigated, and for the engineering lesson they share.

### "Alembic has nine heads" — false

There is exactly **one** head, `tw02_writer_waitlist`. `alembic heads` reports
one, `alembic branches` shows every branchpoint reconverging at a mergepoint, and
the dev database is already at it. `alembic upgrade head` works as documented in
`DEV_SETUP.md`, `replit.md` and `README.md`. **There is no multiple-head defect
and no merge revision is required.**

The figure came from a hand-rolled regex that read `down_revision` as a single
quoted string, silently missing the three merge revisions that use a **tuple**
(`4643bfb95d96`, `08567e37d16e`, `bc03_body_identity_v2`). Every revision named
inside those tuples looked unreferenced — 8 phantoms plus the 1 real head gave
the reported 9.

### "Production uses local filesystem storage" — false

Production runs with `USE_OBJECT_STORAGE=true`, proven by the production
traceback. The claim came from reading the workspace shell and `start-prod.sh`;
Replit **deployment** secrets are separate and invisible to a workspace shell.

### The shared lesson

Both were inferences stated with more confidence than their evidence carried, and
each cost multiple investigation rounds.

- **Never hand-parse a tool's own data model.** `alembic heads` was always
  available and authoritative.
- **Never infer a deployment's configuration from the workspace.** Read it from
  the deployment, have the running app report it, or prove it from a production
  traceback.
- Treat "dev works, production doesn't" as a signal to compare **installed
  dependencies and deployment configuration**, not application logic.
