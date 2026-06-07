# Adult Studio — Phase 2 Technical Design

**Status:** Design only. No code in this document. No RunPod, no Replicate, no GPU, no
image generation, no real provider execution.
**Date:** 2026-06-07
**Predecessors:** Phase 1 (S1–S6) shipped the `AdultIdentityModel` system —
persistence, canon fingerprinting, mark routing, preparation, lifecycle state machine,
provider seam (fake only), and an end-to-end orchestration test.

> **Boundary (non-negotiable):** Canon Studio stays **untouched and beta-complete**.
> Phase 2 reads canon read-only (via `canon_service`) and writes only `adult_*` tables
> + `CharacterImage(SCENE_ONLY)`. Scene Router, Canon Router, Identity OS, providers,
> and the normal image-generation path are out of scope. See §11.

---

## 1. Objective

Connect the **existing Adult Studio UI/routes** to the **new `AdultIdentityModel`
system**, while keeping real GPU providers **disabled behind flags**. Concretely:
1. Bridge/replace the legacy `adult_studio_identities` table.
2. Serve `prepare`/`status` from the new tables (via Phase 1 services).
3. Surface `prepared / stale / ready / failed` in the UI.
4. Keep provider execution (training) and image generation **disabled by default**.

**Non-goals (Phase 2):** running training, calling any provider, generating images,
adding a real `TrainingProvider`, or any Canon Studio change.

---

## 2. Current state and the gap

**Legacy backend** (`backend/app/api/routes/adult_studio.py`, table
`adult_studio_identities`):
- `GET /adult-studio/characters/{id}` → `AdultStudioStatusResponse`
  `{character_id, status, provider, model_ref, refs_count, marks_count}`.
- `POST …/prepare` → builds a manifest and **sets status `ready` immediately** (MVP
  semantics: "ready" = manifest exists, *not* trained).
- `POST …/generate` → calls a multi-image provider (OpenAI) — **must be gated off**.
- `GET …/training-pack` → ZIP export (kept).
- Legacy status vocabulary: `not_trained | preparing | ready | failed`.

**Legacy frontend** (`frontend/src/pages/Studio18Plus.tsx`, `apiClient.ts`,
`types.ts`): status badges for `preparing / ready / failed` (+ implicit `not_trained`);
calls `apiClient.prepareAdultStudio(id)`.

**Phase 1 system** (`AdultIdentityModel` + versions/jobs/mark_renders; services
`adult_identity_preparation`, `adult_identity_training`, `adult_identity_provider`):
status vocabulary `not_trained | prepared | training | ready | stale | failed`.

**The gap:** routes/UI talk to the legacy table and a 4-value status; the new system
has richer state (versions, fingerprints, mark routing, stale detection) and a 6-value
status whose **`ready` now means "trained"** rather than "manifest exists."

---

## 3. Status-model reconciliation (the crux)

The semantics of `ready` changed, so this mapping is explicit and load-bearing.

**Backfill mapping — legacy `adult_studio_identities` → new `AdultIdentityModel`:**

| Legacy status | New status | Why |
|---|---|---|
| `not_trained` | `not_trained` | unchanged |
| `preparing` (transient) | `not_trained` | re-prepare to reach `prepared` |
| `ready` (MVP: manifest only) | **`prepared`** | it was never trained; "manifest+plan ready" = `prepared` |
| `failed` | `failed` | unchanged |

**Phase 2 runtime semantics of the new vocabulary:**

| New status | Meaning in Phase 2 | UI badge |
|---|---|---|
| `not_trained` | no prepare run yet | "Not prepared" (neutral) |
| `prepared` | manifest + fingerprint + mark routes persisted; **awaiting training (disabled)** | "Prepared" (blue) + "training disabled" note |
| `training` | a training job is active | "Training" (amber) — *unreachable while provider disabled* |
| `ready` | an active trained version exists | "Ready" (green) — *unreachable in Phase 2* |
| `stale` | canon changed since last prepare/train | "Update available" (amber) → re-prepare |
| `failed` | last prepare/training failed | "Failed" (red) |

In Phase 2 (training disabled) the reachable states are **`not_trained → prepared →
(stale on canon change) → prepared`** and `failed`. `training`/`ready` are designed and
shown but only become reachable when the training flag is enabled in a later phase.

---

## 4. Backend bridge design

### 4.1 Rewire `prepare` and `status` onto the new system
- `POST …/prepare` calls `prepare_adult_identity(character_id, db)` (Phase 1 S3):
  loads locked canon read-only, computes `canon_fingerprint`, resolves mark routes,
  upserts `AdultIdentityModel` (creates as `prepared`; flips `stale` on canon change),
  upserts `adult_identity_mark_renders`. Idempotent.
- `GET …/status` reads `AdultIdentityModel` (+ active version + mark renders).
- Map `CanonNotReadyError` → HTTP 409 (same UX as today's "lock canon first").

### 4.2 Status response schema (superset — additive, back-compatible)
`AdultStudioStatusResponse` gains fields (existing fields retained so the old UI keeps
working during rollout):
```
character_id, status,                       # status now from the 6-value vocabulary
provider, model_ref,                        # retained (nullable)
refs_count, marks_count,                    # retained (derived from prepared_manifest)
# NEW:
canon_fingerprint, stale (bool),            # stale == (status == "stale")
active_version_id, version_index,           # null until trained (Phase 2: null)
marks: [ {canon_mark_id, region, side, route, reason} ],   # from mark_renders
training_enabled, generation_enabled        # echo the flags so the UI can gate itself
```

### 4.3 Training/generation endpoints — gated OFF
- `POST …/train` (new, optional): when `ADULT_STUDIO_TRAINING_ENABLED` is false →
  **HTTP 409** `{detail: "Adult Studio training is disabled in this environment."}`.
  When enabled later, it drives `AdultIdentityTrainingService` with the configured
  provider. **Default: disabled.**
- `POST …/generate` (legacy): gated behind `ADULT_STUDIO_GENERATION_ENABLED` (default
  false) → **HTTP 409** "generation disabled". Prevents the legacy OpenAI path from
  running. No provider is called.
- `GET …/training-pack`: unchanged (no provider, pure packaging).

### 4.4 Data cutover (bridge-then-deprecate; no fork)
1. **One-time backfill** (Alembic data migration or idempotent startup task): copy each
   `adult_studio_identities` row → `AdultIdentityModel` using §3 mapping (only the 1
   live row exists — Summer/id=60). Backfilled models land in `prepared`/`not_trained`;
   a subsequent `prepare` call refreshes fingerprint + mark routes.
2. **Rewire reads/writes** to `AdultIdentityModel` (4.1).
3. **Legacy table → read-only** for one release as a safety net; no new writes.
4. **Drop `adult_studio_identities`** in a later migration once parity is confirmed.

> This honors the S1 design note: cutover happens now (route rewire), not as a premature
> fork while the legacy table was still the live source.

---

## 5. Feature flags (provider execution disabled)

Add to `core/config.py` (same simple `bool`/`str` pattern as `USE_OBJECT_STORAGE`):

| Flag | Default | Effect |
|---|---|---|
| `ADULT_STUDIO_TRAINING_ENABLED` | `False` | `POST …/train` returns 409 when false; no `TrainingProvider` is constructed |
| `ADULT_STUDIO_PROVIDER` | `"disabled"` | provider selector. `disabled` → none; `fake` → `FakeTrainingProvider` (tests/dev only). **No real provider value resolves to a network call in Phase 2.** |
| `ADULT_STUDIO_GENERATION_ENABLED` | `False` | `POST …/generate` returns 409 when false |

Resolution rule: even if `ADULT_STUDIO_PROVIDER` is misconfigured to a real name, Phase 2
ships **no real provider implementation**, so the seam can only resolve to `none`/`fake`.
The flags are the guardrail; the absence of a real provider is the hard stop.

---

## 6. Frontend bridge design

- **Types** (`types.ts`): extend `AdultStudioStatus['status']` to the 6-value union;
  add `stale`, `active_version_id`, `version_index`, `marks[]`, `training_enabled`,
  `generation_enabled` to the status type.
- **Badges** (`Studio18Plus.tsx`): add `prepared` (blue), `training` (amber, spinner),
  `stale` (amber, "Update available"); keep `ready/failed/not_trained`. Map the new
  `prepared` to the primary "identity is set up" affordance (replacing the old meaning
  of `ready`).
- **Status panel:** show status badge + (when present) version, and a compact list of
  the per-mark routes (`butterfly → ip_adapter`, `ballerina → controlnet_canny`) sourced
  from `marks[]` — gives the user/admin visibility into how each mark will render.
- **Gating:** when `training_enabled` is false, show "Training disabled" and hide/disable
  any "Train" affordance; when `generation_enabled` is false, hide/disable the Generate
  panel with a clear notice. The `Prepare` button stays active.
- **Stale UX:** `stale` → prompt "Canon changed — re-prepare" wired to the existing
  `prepare` call.

No Canon Studio UI is touched; this is confined to the Adult Studio page.

---

## 7. API contract summary

- `GET /adult-studio/characters/{id}` → extended `AdultStudioStatusResponse` (§4.2).
- `POST /adult-studio/characters/{id}/prepare` → same response; now persists to the new
  tables; idempotent; `stale` on canon change.
- `POST /adult-studio/characters/{id}/train` → **new**, 409 while disabled.
- `POST /adult-studio/characters/{id}/generate` → **gated**, 409 while disabled.
- `GET /adult-studio/characters/{id}/training-pack` → unchanged.

All endpoints keep: login + ownership + locked-canon preconditions.

---

## 8. Implementation plan (Phase 2 sprints)

**P2-S1 — Flags + status schema** (no behavior change): add the three flags; extend
`AdultStudioStatusResponse`; echo flags in status. 
**P2-S2 — Rewire status + prepare** onto `AdultIdentityModel`/`prepare_adult_identity`;
map `CanonNotReadyError`→409; backfill migration for the legacy row.
**P2-S3 — Gate generate + add disabled train endpoint** (both 409 by default).
**P2-S4 — Frontend** status vocabulary, badges, mark-route display, flag-driven gating.
**P2-S5 — Legacy deprecation**: legacy table read-only; parity check; (drop deferred).

Each sprint: rollback tag first, tests, no GPU/provider/generation, no Canon Studio
change, commit + checkpoint tag — same cadence as Phase 1.

---

## 9. Acceptance criteria

- [ ] `status`/`prepare` served from `AdultIdentityModel`; legacy row backfilled with no
      data loss (Summer/id=60 maps per §3).
- [ ] Status response exposes `prepared/stale/ready/failed` + per-mark routes + flags.
- [ ] UI renders all four required states (`prepared/stale/ready/failed`) and gates
      train/generate by flag.
- [ ] `POST …/train` and `POST …/generate` return 409 with flags at defaults; **no
      provider constructed, no network call, no GPU, no spend** (assert via no real
      provider import path being reachable).
- [ ] `prepare` is idempotent and flips `stale` on a canon metadata change (reuses the
      Phase 1 e2e guarantees).
- [ ] Schema diff touches only `adult_*` (+ the additive backfill); **no canon table
      altered**; Canon Studio regression check passes.
- [ ] Tests pass (route tests with `TestClient`; flag-gated 409s; backfill mapping).

---

## 10. Risks & open questions

1. **`ready` semantic shift** — previously-"Ready" characters become "Prepared". This is
   accurate (they were never trained) but visible; the UI copy should explain it.
2. **Backfill location** — Alembic data migration vs idempotent startup/CLI task. With a
   single live row, a small data migration is simplest; confirm before coding.
3. **Legacy `generate` removal vs gate** — Phase 2 gates it off (409). Full removal of
   the OpenAI multi-image path is deferred to when the new inference worker lands.
4. **Flag surface** — keep to three booleans/string now; a per-environment override
   matrix can come later.
5. **Dual-table window** — keep `adult_studio_identities` read-only for one release;
   define the parity check before dropping it.

---

## 11. Canon Studio — explicit statement

**Canon Studio remains UNTOUCHED and beta-complete.** Phase 2 only: rewires Adult Studio
routes onto `adult_*` tables, adds Adult Studio flags + status fields, gates training and
generation OFF, and updates the Adult Studio page. It READS canon via `canon_service`
(face/body/marks) and WRITES only `adult_*` tables (+ future `CharacterImage(SCENE_ONLY)`
outputs, not in Phase 2). No Canon Studio logic, Scene Router, Canon Router, Identity OS,
provider code, or normal image-generation path is modified. A Canon Studio regression
check is part of P2-S2 acceptance.
