# Ficshon Closed Beta Runbook (MVP)

## 0) Required Secrets (Replit)
- SECRET_KEY
- PG* (host/user/password/db/port)
- STORYLAB_PROVIDER=openrouter
- OPENROUTER_API_KEY
- STORYLAB_MODEL (or tiered STORYLAB_MODEL_SFW/FADE/SENSUAL)
- IMAGE_PROVIDER=openai
- OPENAI_API_KEY
- IMAGE_MODEL=gpt-image-1.5
- ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_USERNAME
- SMTP_* (optional for beta; required if you expect password reset email delivery)

## 1) Diagnostics Truth Check (admin)
GET /api/admin/diagnostics
Confirm:
- storylab.provider=openrouter
- storylab.openrouter_key_present=true
- images.provider=openai
- images.openai_key_present=true
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
