---
name: Prod DB is a publish-time fork
description: How the production database relates to dev, how to make prod-effective changes, and the DEV-only database command path.
---

The production database is a fork of the dev database taken at publish time (verified: identical user rows and byte-identical password hashes, while later dev writes did not propagate to prod).

**Why:** Replit's publish flow snapshots the dev heliumdb; afterwards the two diverge. Production SQL access from the workspace is read-only, and there is no admin API for flags like `is_seeder`.

**How to apply:**
- Never assume a dev DB write (e.g. setting a user flag) will affect production.
- For prod-effective changes without touching prod data, prefer env-var driven config the app already honors (e.g. `SEEDER_EMAILS`, `ADMIN_EMAILS` in `backend/app/core/config.py` / `app/services/seeding.py`), set as shared env vars, then republish.
- Any code or env change requires the user to republish before it reaches production.

## Database connection safety (corrected 4 September 2026)

An earlier version of this note said the workspace's `PG*` variables were merely "a stale Neon host" and that they could be ignored. **That was wrong and the correction matters.**

What was actually true: the workspace carried a complete set of ambient libpq variables (`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`) targeting Neon-hosted, production-era infrastructure with an owner-level role — while `DATABASE_URL` pointed at the Replit-managed DEV database. Any bare `psql`, `pg_dump`, or libpq call that omitted connection details resolved to the wrong database, with write and DDL rights, silently.

Those five variables were **removed from Replit Secrets on 4 September 2026**.

Standing rules:

- **`DATABASE_URL` is the canonical DEV application connection.** The app (`backend/app/core/database.py`), Alembic (`backend/alembic/env.py`) and every script that goes through `app.core.database.SessionLocal` already derive from it, and correctly.
- **Do not recreate ambient production `PG*` variables in the development workspace.** If an integration re-provisions them, remove them again — they are not needed by anything in this repository.
- **Use `scripts/devdb` for intentional DEV shell access** (`scripts/devdb`, `scripts/devdb -c '…'`, `scripts/devdb pg_dump …`, `scripts/devdb --check`). It validates the destination before launching anything and strips ambient `PG*` from the client's environment.
- **Future maintenance/data scripts must call `assert_dev_database()`** from `scripts/assert_dev_db.py` before creating an engine or session.
- **Production database access must be deliberate and separate** — an explicit, per-session action, never something ambient workspace variables make possible by default.

No host, user, password or connection string belongs in this file.
