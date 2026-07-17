---
name: Autoscale needs pool_pre_ping
description: Why the deployed app intermittently 500s on the first request after idle, and the fix.
---

On the autoscale deployment, the first request after an idle period failed with `psycopg2.OperationalError: SSL connection has been closed unexpectedly` — the DB server closes idle pooled connections while the SQLAlchemy pool still hands them out.

**Why:** Autoscale instances sleep/scale; the Postgres side (helium/Neon-style) drops idle connections aggressively. Without `pool_pre_ping`, the stale socket is only discovered mid-query.

**How to apply:** Keep `pool_pre_ping=True` (and `pool_recycle=300`) on `create_engine` in `backend/app/core/database.py`. If a user reports one-off 500s in production that succeed on retry, suspect stale pooled connections before suspecting auth/data bugs — check deployment logs for the SSL OperationalError signature.
