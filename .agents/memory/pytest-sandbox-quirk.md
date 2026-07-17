---
name: Run pytest with output redirected to a file
description: Long pytest runs in this workspace die silently when streaming output directly.
---

Long-running pytest invocations (the auth suite takes ~100s due to argon2 hashing) repeatedly exited with code -1 and zero output when run directly in the shell, even under `timeout` with plenty of budget.

**Why:** Unknown sandbox/output-buffering interaction; the same commands succeed when stdout/stderr are redirected to a file.

**How to apply:** For backend test runs, use `pytest ... > /tmp/out.txt 2>&1` then read/tail the file. Split long suites into smaller node-id subsets if needed.
