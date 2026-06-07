# Adult Studio — Phase 1 Technical Design & Implementation Plan

**Status:** Design only. No code in this document. No GPU jobs, no RunPod, no image
generation are part of this deliverable.
**Date:** 2026-06-07
**Rollback anchor:** `adult-studio-phase1-start-2026-06-07` (HEAD `0994185`)
**Predecessor:** `docs/ADULT_STUDIO_PHASE0_SUMMARY.md` (architecture proven), and the
validated pipeline architecture in §4 there.

> **Boundary (non-negotiable):** Canon Studio remains **untouched and beta-complete**.
> Adult Studio is a **separate consumer** of canon. It READS `CharacterIdentityCanon`,
> `PermanentBodyMark`, and `CharacterImage` as source-of-truth and never writes them.
> Scene Router, Canon Router, Identity OS, providers, and the normal image-generation
> path are out of scope. See §12.

---

## 1. Objective

Move Adult Studio from the Phase 0 proof to a **production architecture**: durable
per-character identity models (LoRA), a managed training lifecycle, and a deterministic
**mark-type routing** layer that places each permanent mark on the correct limb using
the proven LoRA-identity + regional-inpaint pipeline (IP-Adapter for texture marks,
ControlNet-Canny for figural marks).

**Explicit non-goals for this sprint:** improving image quality, running GPU jobs,
launching RunPod, generating more Summer images, or touching Canon Studio.

---

## 2. Current state (MVP) and gaps

**Exists today** (`backend/app/`):
- `models/adult_studio.py::AdultStudioIdentity` — one row/character: `status`
  (`not_trained|preparing|ready|failed`), `provider`, `model_ref`, `training_notes_json`.
- `api/routes/adult_studio.py` — `GET status`, `POST prepare`, `POST generate`,
  `GET training-pack`.
- `services/adult_studio.py` — `build_manifest`, `load_manifest_refs`,
  `build_adult_prompt`, `check_prompt_safety`, `trigger_token`, `build_training_pack`.
- Canon marks: `schemas/canon.py::PermanentBodyMark` {`id, label, type, body_region,
  side, description, reference_image_url, detail_crop_url, locked`}; marking enums in
  `schemas/body_canon.py` (`MarkingType`, `MarkingPlacement`, `MarkingSize`,
  `MarkingCoverage`).
- Storage: Cloudflare R2 wired (`core/storage.py`, `R2_*` env).

**Gaps for production:**
1. **No durable model artifact.** `model_ref` is a single string; no LoRA weights URI,
   no training config, no version history, no retrain trail.
2. **No training lifecycle.** No job tracking, no provider abstraction, no
   success/failure/cost capture, no resumability.
3. **`generate` does not use the proven pipeline.** It calls a multi-image provider
   (OpenAI) with manifest refs — not LoRA + regional inpaint. Marks are not placed
   per-limb.
4. **No mark routing.** Nothing maps a mark's `type`/`size`/`coverage` to a render
   mechanism, mask, or control asset.
5. **No staleness tracking.** Canon can change (e.g., the Summer truth-metadata fix);
   nothing detects that a trained model is stale vs current canon.

---

## 3. Target architecture (overview)

```
 Canon (read-only)                Adult Studio (Phase 1)
 ─────────────────                ───────────────────────────────────────────────────
 CharacterIdentityCanon  ──┐
 PermanentBodyMark        ─┼─► [PREPARE] manifest + canon_fingerprint + mark plan
 CharacterImage (refs)   ──┘        │
                                    ▼
                         [TRAIN] LoRA training job (provider-abstracted)
                                    │  → AdultIdentityModelVersion (weights_uri)
                                    ▼
                         [GENERATE] worker pipeline:
                            base SDXL + LoRA ─► SegFormer masks ─► per-mark passes
                              • texture marks  → IP-Adapter
                              • figural marks  → ControlNet-Canny(detail crop)
                            (exposure-gated; region-zoom for small marks)
                                    │
                                    ▼  outputs + metrics → R2, CharacterImage(kind=scene_only)
```

Three planes: **Persistence** (§4), **Lifecycle/orchestration** (§5), **Routing/render**
(§6). Provider/infra abstraction in §8.

---

## 4. Persistence design — `AdultIdentityModel`

Evolves the MVP `AdultStudioIdentity` into a production model with **version history**,
**training-job tracking**, and a **per-mark render plan**. Four tables. Canon tables are
**not** modified.

### 4.1 `adult_identity_models` (one row per character — the authoritative record)

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `character_id` | int FK→characters, **unique** | one identity per character |
| `status` | enum (§5.1) | lifecycle state |
| `trigger_token` | str | LoRA trigger (e.g. `ficsummerfielding`) |
| `base_model` | str | e.g. `stabilityai/stable-diffusion-xl-base-1.0` |
| `active_version_id` | int FK→versions, nullable | currently servable LoRA |
| `canon_fingerprint` | str(64) | sha256 of canon inputs at last prepare (§5.4) |
| `prepared_manifest_json` | json | refs + per-mark plan snapshot (replaces `training_notes_json`) |
| `provider` | str | training provider used (`replicate`/`runpod`/`modal`) |
| `last_error` | str nullable | most recent failure summary |
| `created_at`/`updated_at` | datetime | |

*Migration:* extend `adult_studio_identities` in place (Alembic add-columns) and rename
the ORM class to `AdultIdentityModel`, keeping the table or renaming to
`adult_identity_models`; backfill `trigger_token` from `services.trigger_token`,
`prepared_manifest_json` from `training_notes_json`. Status values are a superset of the
existing four, so existing rows map cleanly.

### 4.2 `adult_identity_model_versions` (LoRA artifacts — append-only history)

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `identity_id` | int FK→models | |
| `version_index` | int | monotonic per identity |
| `lora_weights_uri` | str | R2 key / storage URI of `lora.safetensors` |
| `base_model` | str | |
| `training_config_json` | json | steps, rank, resolution, caption source, seed |
| `source_manifest_json` | json | exact canon refs used |
| `canon_fingerprint` | str(64) | canon hash this version was trained against |
| `metrics_json` | json nullable | eval scorecard (§11) |
| `state` | enum: `active|superseded|failed` | |
| `created_at` | datetime | |

### 4.3 `adult_identity_training_jobs` (training run tracking)

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `identity_id` | int FK→models | |
| `version_id` | int FK→versions, nullable | set on success |
| `provider` | str | `replicate`/`runpod`/`modal` |
| `external_job_id` | str | provider job/training id |
| `state` | enum: `queued|running|succeeded|failed|canceled` | |
| `cost_usd` | float nullable | actuals |
| `logs_uri` | str nullable | R2 log blob |
| `error` | str nullable | |
| `started_at`/`finished_at` | datetime nullable | |

### 4.4 `adult_identity_mark_renders` (per-mark routing plan + cached control assets)

One row per canon mark that Adult Studio will render. Lets routing be computed once,
inspected, and cached; keyed for staleness by mark content.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `identity_id` | int FK→models | |
| `canon_mark_id` | str | `PermanentBodyMark.id` (e.g. `pbm_8cff990d`) |
| `mark_fingerprint` | str(64) | sha256 of the mark's canon fields + ref bytes |
| `mark_type` | str | tattoo/scar/burn/birthmark/… |
| `body_region` | str | from canon (`right_upper_arm`, `left_forearm`, …) |
| `side` | str | left/right/centre/bilateral |
| `route` | enum (§6.1): `ip_adapter|controlnet_canny|hybrid|skip` | resolved mechanism |
| `reference_uri` | str | preferred `detail_crop_url`, else `reference_image_url` |
| `control_asset_uri` | str nullable | cached canny/edge map (R2) |
| `params_json` | json | scales, strength, steps, seed for this mark |
| `created_at`/`updated_at` | datetime | |

**Relationships:** `AdultIdentityModel 1─*  Versions`, `1─* TrainingJobs`,
`1─* MarkRenders`; `active_version_id` points into Versions.

---

## 5. Training lifecycle

### 5.1 State machine (`adult_identity_models.status`)

```
not_trained ──prepare──► prepared ──train──► training ──success──► ready
     ▲                       │                   │                   │
     │                       │                   └──fail──► failed ◄──┘ (on serve error)
     │                       │                                       │
     └───────────────────────┴──────── canon change (fingerprint) ──► stale ──prepare──► …
```

- **not_trained** — no model yet.
- **prepared** — manifest + `canon_fingerprint` + mark-render plan computed; ready to train.
- **training** — a training job is `queued|running`.
- **ready** — an `active` version exists AND its `canon_fingerprint` matches current canon.
- **stale** — current canon fingerprint ≠ active version's fingerprint (canon changed);
  servable but flagged for re-prepare/retrain.
- **failed** — last job failed; `last_error` populated.

*Generation is a runtime operation, not a state* — it requires `status ∈ {ready, stale}`.

### 5.2 `prepare` (extends existing)
1. Load **locked** canon (existing `_load_locked_canon`).
2. Build manifest (existing `build_manifest`): face/body/mark refs + descriptions.
3. **Compute `canon_fingerprint`** (§5.4) and per-mark `mark_fingerprint`s.
4. **Resolve mark routing** (§6) → upsert `adult_identity_mark_renders`.
5. Persist `prepared_manifest_json`; set `status=prepared`.

### 5.3 `train`
1. Build training pack (existing `build_training_pack`) — **now also writing per-image
   `.txt` captions into the trainer input** (Phase 0 found the Replicate trainer ignores
   them unless present; future RunPod/Modal trainer will consume them).
2. Create `adult_identity_training_jobs` row; submit via the training provider adapter
   (§8); store `external_job_id`; `status=training`.
3. Poll (worker/cron) → on success: download `lora.safetensors` to R2, create
   `adult_identity_model_versions` (`state=active`, mark previous active `superseded`),
   set `active_version_id`, capture `cost_usd`; `status=ready`.
4. On failure/cancel/timeout: job `failed`; model `status=failed`; `last_error` set.
   **Hard spend cap + auto-terminate carried over from Phase 0 harness.**

### 5.4 Staleness (`canon_fingerprint`)
`sha256` over a canonical serialization of: face canon (image URIs + description),
body canon (build/description + image URIs), and the full ordered mark list
(`id, type, body_region, side, label, description, ref/detail URIs`). On any
canon-data change (e.g. the Summer truth-metadata correction), the fingerprint diverges →
model flagged **stale** → UI prompts re-prepare/retrain. This makes the corrected truth
metadata *actionable* rather than silently ignored.

### 5.5 Provider abstraction (training)
`TrainingProvider` interface: `submit(pack, config) → job_id`, `poll(job_id) → state`,
`fetch_weights(job_id) → bytes/uri`, `cost(job_id)`. Implementations:
`ReplicateSDXLTrainer` (works today), `RunPodTrainer`/`ModalTrainer` (self-hosted,
captions honored, no face-crop loss). Selection via config; lifecycle code is
provider-agnostic.

---

## 6. Mark-type routing architecture

The core new subsystem. Deterministic resolver: **mark → (route, mask plan, control
asset, params)**. Pure function of canon mark fields; cached in `mark_renders`.

### 6.1 Route decision table

| Mark signal | Route | Rationale (Phase 0 evidence) |
|---|---|---|
| `coverage ∈ {sleeve, full_sleeve}` OR `size ∈ {full_sleeve, full_back}` OR large ornamental tattoo | **`ip_adapter`** | Texture/pattern over a region; IP-Adapter reproduced the butterfly/floral sleeve **strongly**. |
| Figural/structural tattoo (dancer, portrait, lettering, logo, line-art) — small/medium with defined shape | **`controlnet_canny`** | Specific figure needs structure; Canny etched the ballerina where IP-Adapter alone produced **nothing**. |
| Complex mark needing both structure + style | **`hybrid`** | Canny (structure, scale ~0.8) + IP-Adapter (style, low scale ~0.3). |
| `scar`, `burn`, `birthmark`, `mole` | **`ip_adapter`** (texture) | Texture-like; no rigid figure. |
| Region not exposed by the requested scene/clothing | **`skip`** | Exposure gate (§6.4); do not paint a covered mark. |
| No usable `reference_image_url`/`detail_crop_url` | **`skip`** + warn | Never fabricate a mark; surface it (mirrors `build_training_pack` "never silently dropped"). |

Classification of "figural vs texture" uses: explicit `type`, `coverage`/`size`,
and a keyword pass over `label`/`description` (e.g. "ballerina/dancer/portrait/script/
lettering/logo" → figural; "sleeve/floral/pattern/tribal/mandala" → texture). The
resolver is table-driven and unit-testable with fixtures.

### 6.2 Reference selection
Prefer `detail_crop_url` (tight, high-fidelity) over `reference_image_url`. For
`controlnet_canny`, precompute the Canny edge map of the chosen reference and cache it
as `control_asset_uri`.

### 6.3 Region → mask
`body_region` → SegFormer human-parsing class (Right-arm/Left-arm/torso/leg/…) →
sub-region split where needed (`*_upper_arm` = upper half of arm class; `*_forearm` =
lower half), dilate + feather. Proven reliable in Phase 0 (replaced fragile mediapipe).
`MarkingPlacement` already enumerates all needed regions.

### 6.4 Exposure gating
Reuse the existing clothing/surface-discipline logic in `api/routes/image_generator.py`
(region exposure classifier) to decide, per scene prompt + garment, whether a mark's
region is visible. Covered → `route=skip` for that render. This concept is already
solved in the codebase; Adult Studio calls it read-only.

### 6.5 Resolution policy (small-mark fidelity)
For small/figural marks on thin/foreshortened surfaces (forearm, wrist, neck):
**region-zoom inpaint** — crop the mask bbox, upscale to full model resolution, inpaint,
paste back. Directly addresses the Phase 0 "faint ballerina" limitation **without**
raising base resolution globally.

---

## 7. Generation pipeline (runtime, worker)

Composes the proven passes, driven by `mark_renders`:
1. **Base gen** — base SDXL + active LoRA → character in requested scene; pose/exposure
   shaped by prompt + negatives.
2. **Masking** — SegFormer → per-region masks for all `route≠skip` marks.
3. **Mark passes** — for each mark in deterministic order (large/texture first, figural
   last): apply its route (`ip_adapter` | `controlnet_canny` | `hybrid`) with cached
   control asset + params; region-zoom when flagged.
4. **Persist** — final + intermediates to R2; register output as
   `CharacterImage(kind=SCENE_ONLY)` (already the canon-safe "not canon" kind); record
   metrics.

Single `StableDiffusionXLControlNetInpaintPipeline` (base SDXL + canny ControlNet +
IP-Adapter) toggling `controlnet_conditioning_scale`/`ip_adapter_scale` per pass —
exactly the Phase 0 v2 pipeline.

---

## 8. Provider / infra abstraction

- **Training:** `TrainingProvider` (§5.5). Default Replicate; target self-hosted
  RunPod/Modal so captions are honored and face-crop loss avoided.
- **Serving/inference:** `InferenceWorker` running the §7 pipeline on a GPU
  (RunPod/Modal). Carries the **Phase 0 safety harness**: hard `$` cap, triple
  self-terminate, R2 status streaming, no orphaned pods.
- **Storage:** Cloudflare R2 (already wired). LoRA weights, control assets, outputs,
  logs all keyed under namespaced prefixes (`adult/<character_id>/…`).
- **Orchestration:** a job/worker abstraction (queue or cron-driven poller) so training
  and generation are async, resumable, and observable; no long-lived in-request GPU calls.
- **Safety:** existing `check_prompt_safety` gate retained and extended; adult-adjacent
  allowed, minors/illegal blocked; self-hosted moderation per `ADULT_STUDIO_V1_PIPELINE_DESIGN.md`.

---

## 9. API surface (incremental, additive)

- `GET  /adult-studio/characters/{id}` — status incl. `version`, `canon_fingerprint`,
  `stale` flag, mark-render plan summary.
- `POST /adult-studio/characters/{id}/prepare` — extends existing: now also resolves
  routing + fingerprints.
- `POST /adult-studio/characters/{id}/train` — **new**: submit training job (async).
- `GET  /adult-studio/characters/{id}/training-jobs/{job_id}` — **new**: job status/cost.
- `POST /adult-studio/characters/{id}/generate` — **rewired** to the worker pipeline
  (LoRA + routed inpaint) instead of the multi-image provider.
- `GET  /adult-studio/characters/{id}/training-pack` — retained (now emits `.txt` captions).

All require login + ownership + locked canon, as today.

---

## 10. Implementation plan (sprints)

**S1 — Persistence & migration** (no behavior change)
- Alembic: extend/rename to `AdultIdentityModel` + add `versions`, `training_jobs`,
  `mark_renders` tables; backfill from `adult_studio_identities`.
- ORM models + repository layer. Dependency: none.

**S2 — Fingerprint & routing resolver** (pure, offline-testable)
- `canon_fingerprint` + `mark_fingerprint` hashing.
- Mark-type routing resolver (§6.1–6.2) + region→mask mapping (§6.3).
- Unit tests with Summer fixtures (butterfly→ip_adapter, ballerina→controlnet_canny).
  Dependency: S1.

**S3 — Training lifecycle & provider abstraction**
- `TrainingProvider` interface + `ReplicateSDXLTrainer`; `train` endpoint + job poller;
  version creation on success; staleness flagging. Training pack emits `.txt` captions.
  Dependency: S1.

**S4 — Inference worker (pipeline as a service)**
- Port the Phase 0 v2 pipeline into a worker (base+LoRA → masks → routed passes →
  region-zoom). Exposure gating via existing classifier. Safety harness carried over.
  Dependency: S2, S3.

**S5 — Wire `generate` + outputs**
- Rewire `generate` to the worker; persist outputs as `CharacterImage(SCENE_ONLY)`;
  metrics. Dependency: S4.

**S6 — Eval harness & hardening**
- Automated scorecard (§11), retry/cancel/timeout paths, cost reporting, docs.
  Dependency: S5.

GPU execution (S3 training runs, S4/S5 inference) is **out of scope for this design
sprint** and gated behind explicit approval + the $-cap harness.

---

## 11. Acceptance criteria

**Persistence (S1)**
- [ ] Migration applies and reverses cleanly; existing `adult_studio_identities` rows
      map to `AdultIdentityModel` with no data loss.
- [ ] One identity per character enforced (unique `character_id`); versions append-only;
      `active_version_id` always points to a `state=active` version or null.
- [ ] No canon table altered (schema diff touches only `adult_*` tables).

**Routing resolver (S2)**
- [ ] Deterministic: identical canon mark → identical `(route, reference_uri, params)`.
- [ ] Summer fixtures: right-upper-arm butterfly/floral sleeve → `ip_adapter`;
      left-forearm ballerina → `controlnet_canny` (prefers `detail_crop_url` if present).
- [ ] Mark with no usable reference → `skip` + surfaced warning (never fabricated).
- [ ] `canon_fingerprint` changes iff any canon identity/mark field changes; the Summer
      truth-metadata edit would flip an existing model to `stale`.

**Training lifecycle (S3)**
- [ ] `prepare` populates manifest + fingerprints + mark-render plan; sets `prepared`.
- [ ] `train` creates a job, transitions `training`→`ready` on success with a persisted
      `lora_weights_uri`, `cost_usd`, and an `active` version.
- [ ] Failure/timeout → `failed` + `last_error`; no orphaned GPU resources; spend within cap.
- [ ] Training pack includes per-image `.txt` captions carrying corrected mark descriptions.

**Generation pipeline (S4–S5)** *(validated only under explicit approval)*
- [ ] Output holds recognizable identity (LoRA) and renders each `route≠skip` mark on its
      **correct limb** (`body_region`/`side`), no clothing bleed.
- [ ] Covered regions (exposure gate) are not painted.
- [ ] Output stored as `CharacterImage(SCENE_ONLY)`; never written to any canon table.

**End-to-end / safety (S6)**
- [ ] Scorecard per generation: identity, per-mark present + correct limb, no bleed.
- [ ] Every GPU job self-terminates; hard `$` cap enforced; no orphaned pods.
- [ ] Canon Studio behavior unchanged (regression check, §12).

---

## 12. Canon Studio — explicit statement

**Canon Studio remains UNTOUCHED and beta-complete.** Phase 1 adds only `adult_*`
tables, an Adult Studio service/worker, and additive Adult Studio API endpoints. It:
- READS `CharacterIdentityCanon`, `PermanentBodyMark`, `CharacterImage` as source-of-truth;
- WRITES only `adult_*` tables and `CharacterImage(kind=SCENE_ONLY)` outputs (the
  existing canon-safe "not canon" kind);
- does **not** modify Canon Studio logic, Scene Router, Canon Router, Identity OS,
  providers, or the normal image-generation path.
A Canon Studio regression check is part of S6 acceptance.

---

## 13. Risks & open questions

1. **Self-hosted training** (RunPod/Modal) to honor captions + avoid face-crop loss —
   build now, or ship S3 on Replicate first and migrate? (Recommend Replicate-first,
   abstracted, migrate in a later sprint.)
2. **Figural-vs-texture classification** from `label`/`description` keywords — start
   rule-based + table; revisit if misclassification appears.
3. **Bilateral / non-arm regions** (back, ribs, thigh, face) — SegFormer classes exist;
   sub-region splitting rules need per-region definition beyond arms.
4. **Cost ceiling per generation** (multi-pass inpaint + region-zoom) — define a
   per-image cap and pass budget.
5. **Multiple marks on one limb** — pass ordering + mask disjointness rules.
