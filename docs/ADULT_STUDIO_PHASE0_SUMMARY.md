# Adult Studio — Phase 0 Summary & Findings

**Status:** Phase 0 (research/proof) COMPLETE. No production code shipped.
**Date:** 2026-06-07
**Scope:** Validate, outside Ficshon, an architecture that holds **Summer Fielding's**
(character id=60) identity **and** her two permanent tattoos in a generated scene —
better than the current third-party provider does — and decide the production path.

> **Hard boundary (held throughout):** Canon Studio, Scene Router, Canon Router,
> Identity OS, providers, and normal image generation were **not modified**. All
> work read canon as source-of-truth only. See §9.

---

## 1. What was proven

1. **Headless GPU pipeline works end-to-end and is safe.** A self-contained RunPod
   pod pulls the LoRA + canon tattoo crops, generates, segments, inpaints, streams
   every stage to R2, and **self-terminates** under a hard `$5` cap. Real per-run
   cost ≈ `$0.01`. Triple kill-switch (in-pod 45-min watchdog + main self-kill +
   external poller cap) held on every run; **zero orphaned pods**.
2. **Per-character LoRA gives reliable identity.** Summer's v2 SDXL LoRA (700 steps,
   rank 32, trained from her locked Canon Pack) reproduces a recognizable, consistent
   face/build across scenes.
3. **Per-arm region masking is reliable without fragile pose libs.** SegFormer
   human-parsing (`mattmdjaga/segformer_b2_clothes`, Left-arm/Right-arm classes,
   split upper/lower) produced usable masks every time.
4. **Reference-guided regional inpaint places tattoos on the CORRECT limb.**
   - Right upper arm butterfly/floral sleeve → **strong** (clear butterflies + florals).
   - Left forearm ballerina → **correct location**, structured black linework via
     ControlNet-Canny (faint at full-body scale; see §2).
5. **Mechanism selection matters.** IP-Adapter is right for *texture/style* marks
   (the sleeve); ControlNet-Canny (edges of the actual crop) is right for *specific
   figural* marks (the ballerina), where IP-Adapter alone produced nothing.
6. **Pose control changes mask quality.** Akimbo pose hid the forearm (mask ≈ 0
   usable); "arms straight at sides" exposed it (left-arm mask ≈ 32k px) — the single
   biggest lever for the ballerina.

---

## 2. What failed / limitations

- **Tattoo-via-LoRA alone does NOT work (Option A premise refuted).** The LoRA learned
  the floral sleeve as a *generic* "big arm sleeve" feature — spread across both arms,
  bleeding onto clothing — and **never learned the ballerina or limb-specificity**.
  Root causes (from inspection): the Replicate SDXL trainer ignores per-image `.txt`
  captions (it uses BLIP auto-caption + a fixed `caption_prefix`), and
  `use_face_detection` cropping strips arm-tattoo pixels during training. **A naive
  "retrain with corrected captions" is therefore not the path.** (Measured in Option B.)
- **Ballerina fidelity is partial.** Present and correctly located, but faint — the
  forearm is a thin, foreshortened surface; at 832×1216 / ~34 steps the masked strip
  can't resolve fine dancer detail. Needs region-zoom inpaint (crop→upscale→inpaint→
  paste-back), higher ControlNet scale, and a sharpening pass.
- **Early pipeline failures (all caught cheaply; each pod self-terminated):**
  1. `403 Forbidden` fetching crops from the public `r2.dev` URL — Cloudflare blocks the
     default `Python-urllib` user-agent → fixed by fetching via **boto3** (bucket creds).
  2. `RuntimeError: Numpy is not available` — pip pulled numpy 2.x, incompatible with the
     image's torch 2.2 ABI → fixed by pinning **numpy<2**.
  3. `mediapipe has no attribute 'solutions'` — broken native install on the pod →
     replaced with **SegFormer** human-parsing.
- **RunPod placement:** on-demand RTX 4090 *community* capacity was unavailable
  ("machine does not have the resources"); switched to **A40 (48 GB, secure, ~$0.44/hr,
  High stock)**, which placed reliably.

---

## 3. Actual costs

All work used throwaway models/pods. Every sprint ran under a `$5` cap.

| Workstream | Item | Cost (USD) |
|---|---|---|
| LoRA train | summer-sdxl-lora (v1) train + gen | ~0.43 |
| LoRA train | summer-sdxl-lora-v2 train + gen | ~0.36 |
| LoRA tune | scale sweep (0.78/0.82/0.88) | ~0.05 |
| Option B | tattoo-specific inference (6 imgs, est.) | ~0.035 |
| Option C | headless inpaint proofs — **5 pod runs total** (RunPod A40) | ~0.043 |
| | **Grand total** | **≈ $0.91** |

RunPod balance moved `$9.447 → $9.404` across all five Option C launches. No single
run exceeded ~`$0.012`; the `$5` absolute cap was never approached.

---

## 4. Actual architecture (as proven)

```
                 ┌─────────────────────────── locked Canon (read-only) ───────────────────────────┐
                 │  Summer v2 SDXL LoRA (identity)   +   per-mark reference crops (butterfly,       │
                 │                                       ballerina)  +  body_region / side          │
                 └───────────────────────────────────────────────────────────────────────────────┘
                                                  │
   [1] BASE GEN        base SDXL + LoRA  ──────────►  Summer, blue bikini, arms-at-sides
                       (prompt + negatives control pose/exposure)
                                                  │
   [2] MASKING         SegFormer human-parsing  ──►  Right-arm / Left-arm masks (split upper|lower)
                                                  │
   [3] MARK PASSES     per-mark regional inpaint (one StableDiffusionXLControlNetInpaintPipeline):
                         • texture/sleeve mark   → IP-Adapter (h94/IP-Adapter sdxl), mask=region
                         • specific figural mark → ControlNet-Canny (edges of the real crop,
                                                    composited into the mask bbox), mask=region
                       toggling controlnet_conditioning_scale / ip_adapter_scale per pass
                                                  │
   [OUTPUT]            final image  →  R2 (Cloudflare)   +   status.json stream
```

**Infra:** headless RunPod pod (A40 48 GB secure). Self-contained startup wrapper:
streams images + `status.json` to R2; **triple self-terminate** (45-min in-pod
watchdog + main self-kill + external poller cap); `$5` absolute cap. Inputs: Summer
LoRA weights (`Replicate trained_model.tar → lora.safetensors`), canon crops (R2).

**Models:** `stabilityai/stable-diffusion-xl-base-1.0`,
`diffusers/controlnet-canny-sdxl-1.0`, `h94/IP-Adapter` (sdxl),
`mattmdjaga/segformer_b2_clothes`, Summer v2 LoRA.

**Reproduction scripts (untracked tooling, `scripts/`):**
`runpod_launch_proof.py`, `runpod_watch_proof.sh`, `runpod_poll_proof.py`,
`runpod_proof_lib.py`, `comfyui_proof_pod_inpaint.py`; state in
`runpod_phase0_state.json`; result URLs in `proof_result_urls.txt` / `proof_v2_status.json`.

---

## 5. Why LoRA + ControlNet/inpaint is the Adult Studio path

- **LoRA owns IDENTITY** (face, build, hair) — what must stay constant. Cheap
  (~$0.34/char, ~5 min) and reusable across every scene.
- **LoRA does NOT own permanent marks.** Option B proved it cannot bind a specific
  design to a specific limb; it generalizes marks into generic features and drops
  figural ones entirely.
- **Regional inpaint owns the MARKS** — exact design on the correct limb — using the
  **actual canon crops** and masks, decoupled from identity. Two complementary
  mechanisms cover the two mark types (texture → IP-Adapter; figural → ControlNet-Canny).
- **It matches the canon data model.** `PermanentBodyMark` already carries
  `body_region`, `side`, `reference_image_url`, `detail_crop_url` — exactly the inputs
  this pipeline consumes. The recently corrected truth metadata (Summer's mark labels/
  descriptions + training-pack captions) feeds it directly.
- **It is self-hostable** (RunPod/Modal) with our own moderation — consistent with the
  production-serving conclusion in `docs/ADULT_STUDIO_V1_PIPELINE_DESIGN.md`, and keeps
  adult content off third-party moderated APIs.

---

## 6. Next implementation sprint (Phase 1)

1. **Productionize the headless pipeline** as an internal Adult Studio worker/service
   (separate from Canon Studio): input = locked `character_id`; pull LoRA weights +
   per-mark crops + `body_region`/`side`; base-gen → segment → per-mark inpaint.
2. **Mark-type routing:** `sleeve`/`full_sleeve`/large textured → IP-Adapter; specific
   figural (ballerina, lettering, logo) → ControlNet-Canny (prefer `detail_crop_url`).
3. **Detail crops:** capture tight `detail_crop_url` per mark (schema already supports
   it) to lift canny/IP fidelity.
4. **Small-mark fidelity:** region-zoom inpaint (crop → upscale → inpaint → paste-back)
   so thin limbs (forearm) get full model resolution — directly fixes the faint ballerina.
5. **Exposure gating:** reuse the existing clothing/surface-discipline logic
   (`image_generator`) so a mark is inpainted only when its region is exposed.
6. **LoRA harness fix (only if any mark stays in LoRA):** feed per-image `.txt`
   captions and disable face-detection cropping — but primary marks go through inpaint.
7. **Serving + moderation:** self-hosted SDXL; integrate existing R2 storage and the
   already-built Adult Studio manifest / training-pack endpoints.
8. **Eval harness:** scorecard (identity, each mark present + correct limb, no clothing
   bleed) — reuse `ADULT_STUDIO_VALIDATION_SPRINT.md`, now with corrected canon placements.

---

## 7. Proof artifacts (R2, `proof/` prefix in `ficshon-images`)

- **v1** (IP-Adapter, akimbo): `proof/summer_tattoo_20260607_135546/99_final.png`
  — butterfly sleeve ✓ on right upper arm; ballerina absent.
- **v2** (ControlNet-Canny, arms-at-sides): `proof/summer_tattoo_20260607_140525/99_final.png`
  — butterfly sleeve **strong**; ballerina **present (faint) in correct location**;
  `03b_ballerina_canny_control.png` shows the canny edge-map placement.

*(These objects sit under a `proof/` prefix and can be deleted on request.)*

---

## 8. Decision

**Green-light Phase 1** on the **LoRA-identity + regional-inpaint (IP-Adapter for
texture marks, ControlNet-Canny for figural marks)** architecture, self-hosted with
our own moderation. Do **not** pursue tattoo-via-LoRA retraining as the mark mechanism.

---

## 9. Canon Studio status — explicit

**Canon Studio remains UNTOUCHED and beta-complete.** No Canon Studio logic, Scene
Router, Canon Router, Identity OS, provider code, or normal image-generation path was
modified in Phase 0 (Options A/B/C). Every step consumed canon **read-only**. The only
canon-*data* change in this entire effort was the earlier truth-metadata correction for
Summer (id=60) mark labels/descriptions — that is data, not Canon Studio logic, and it
left Canon Studio behavior unchanged.
