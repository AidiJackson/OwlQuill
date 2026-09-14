# Ficshon Closed Beta Runbook (MVP)

## 0) Required Secrets (Replit)
- SECRET_KEY
- PG* (host/user/password/db/port)
- STORYLAB_PROVIDER=openrouter
- OPENROUTER_API_KEY
- STORYLAB_MODEL (or tiered STORYLAB_MODEL_SFW/FADE/SENSUAL)
- IMAGE_PROVIDER=google (Canon default; GOOGLE_AI_API_KEY required)
- OPENAI_API_KEY (founder OpenAI option, identity-pack fallback, vision checks)
- IMAGE_MODEL — leave UNSET to take the code default (`gpt-image-2`). Setting
  it pins the model for every "openai" caller (identity pack, scene images,
  accessories, public /images). Older `gpt-image-1.5` pins should be removed.
- ADMIN_CREATOR_OPENAI_MODEL / ADMIN_CREATOR_OPENAI_QUALITY /
  ADMIN_CREATOR_OPENAI_OUTPUT_FORMAT — optional; Admin Creator's OWN OpenAI
  configuration (defaults `gpt-image-2` / `medium` / `png`). Independent of
  IMAGE_MODEL. Effective values: `images.admin_creator_openai` in diagnostics.
- ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_USERNAME
- SMTP_* (optional for beta; required if you expect password reset email delivery)

## 1) Diagnostics Truth Check (admin)
GET /api/admin/diagnostics
Confirm:
- storylab.provider=openrouter
- storylab.openrouter_key_present=true
- images.provider=google
- images.openai_key_present=true
- images.model = gpt-image-2 (the model every "openai" caller sends)
- images.admin_creator_openai.model = gpt-image-2, .quality = medium,
  .quality_supported = true (Admin Creator's own OpenAI configuration)
- OpenAI credit balance > 0 on the platform billing page — an exhausted
  balance fails every OpenAI call in seconds; Admin Creator now reports it as
  "OpenAI has no remaining credits" rather than "try again".
- storylab.daily_limit matches desired beta cap
- images.weekly_limit matches desired beta cap

## 2) Beta Caps (suggested defaults)
- STORYLAB_DAILY_LIMIT=30
- IMAGE_WEEKLY_LIMIT=15
(Admin remains unlimited.)

## 3) Smoke Flow — Admin
1) Login admin
2) Create 3 characters (proves admin multi-character)
3) Generate identity packs for each
4) Generate 3 library images
5) StoryLab: generate 3 chapters on story A, 2 chapters on story B

## 4) Smoke Flow — Normal user
1) Register + login
2) Create character
3) Attempt second character -> expect 403 character_limit_reached
4) StoryLab: generate until quota -> expect 429 quota_exceeded
5) Images: generate until quota -> expect 429 quota_exceeded

## 5) Safety Flow
1) User A posts + comments
2) User B blocks A
   - feed excludes A
   - messaging returns 403 blocked
3) User B reports content
4) Admin bans A
5) A now receives banned 403 payload on protected endpoints

## 6) If something fails
- Re-check /api/admin/diagnostics first.
- Verify alembic head matches expected.
- Confirm STORYLAB_PROVIDER and IMAGE_PROVIDER are set in runtime env.

## 7) Identity Pack A/B Testing — Google vs OpenAI

To switch identity pack generation to Google Imagen (Google AI Studio):
    export IDENTITY_IMAGE_PROVIDER=google
    export GOOGLE_AI_API_KEY=<your-key>

To revert to OpenAI (default):
    unset IDENTITY_IMAGE_PROVIDER   # or set to "openai"

Notes:
- IDENTITY_IMAGE_PROVIDER only affects identity pack generation.
- Scene/library images always use IMAGE_PROVIDER (default: openai).
- Google Imagen is text-to-image only; reference-image edits are not supported.
  The identity pack tier A will generate all 4 shots as independent text-to-image calls.
- Diagnostics endpoint confirms effective providers per context (identity_pack / scene).
