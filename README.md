# Experiment archive — S24 pre-launch (2026-07-15)

**This branch is an archive. It is NOT part of the deployable application.**

The files here are experimental driver scripts and harnesses (RunPod/LoRA/editor/
tattoo/canon validation, sprints S22–S24, E3–E8 editor bake-offs). They were
deliberately separated out of the production snapshot so the deployable tree
contains only reviewed application source, frontend, tests, docs, config, and the
database migration. Nothing in this branch is imported or executed by the running
application.

## Provenance

- **Source snapshot these files were separated from:** commit
  `332c006a0ccaeeed6fc6f7a3410d668c8bc7ee6c`
  (`chore(release): consolidate secure pre-launch beta snapshot`,
  branch `experiment/s23c-tattoo-safe-hires`).
- **Production release tag:** `pre-launch-2026-07-15`.
- This branch is intentionally an **orphan** (no shared history with the
  production branch) and **must not be merged** into the production branch.

## Structure

```
archive/
├── drivers/                    31 untracked experiment driver scripts, removed
│                               from the production tree (runpod_*, s23*, e3–e8,
│                               editor_*, comfyui_*, summer_lora / tattoo drivers).
└── modified-tracked-scripts/   The MODIFIED working-tree versions of two tracked
                                scripts that were reverted to HEAD in production:
                                  - founder_v2_build.py
                                  - runpod_s24t_poll.py
                                (Their committed/HEAD versions remain in the
                                production tree; only the in-progress edits live here.)
```

## Restoring a file

```bash
git checkout experiments/s24-prelaunch-2026-07-15 -- archive/drivers/<name>.py
```

Do not deploy from this branch.
