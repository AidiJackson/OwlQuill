---
name: Prod DB is a publish-time fork
description: How the production database relates to dev, and how to make prod-effective data/config changes.
---

The production database is a fork of the dev database taken at publish time (verified: identical user rows and byte-identical password hashes, while later dev writes did not propagate to prod).

**Why:** Replit's publish flow snapshots the dev heliumdb; afterwards the two diverge. Production SQL access from the workspace is read-only, and there is no admin API for flags like `is_seeder`.

**How to apply:**
- Never assume a dev DB write (e.g. setting a user flag) will affect production.
- For prod-effective changes without touching prod data, prefer env-var driven config the app already honors (e.g. `SEEDER_EMAILS`, `ADMIN_EMAILS` in `backend/app/core/config.py` / `app/services/seeding.py`), set as shared env vars, then republish.
- Any code or env change requires the user to republish before it reaches production.
- Note: `checkDatabase()` reports "not provisioned" but the DB works via the `DATABASE_URL` secret (host `helium`, db `heliumdb`); old `PG*` secrets point to a stale Neon host — trust `DATABASE_URL`.
