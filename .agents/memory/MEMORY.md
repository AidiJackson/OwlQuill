# Memory Index

- [Prod DB is a publish-time fork](prod-db-fork.md) — dev DB writes never reach production; use env config or app endpoints for prod-effective changes, then republish.
- [Autoscale needs pool_pre_ping](autoscale-db-connections.md) — first request after idle 500s with "SSL connection has been closed unexpectedly" unless the engine pre-pings.
- [Run pytest with output redirected to a file](pytest-sandbox-quirk.md) — long direct-streamed pytest runs get killed silently with no output in this workspace.
