# Adult Studio — Phase 3 Sprint 6 Inspection Report

**Date:** 2026-06-08
**Goal of sprint:** Validate end-to-end tattoo enforcement using Adult Studio mark-route plans.
**Rollback tag:** `rollback-pre-adult-studio-phase3-sprint6-2026-06-08`
**Spend so far:** $0.00 (inspection only — no provider constructed, no generation, no RunPod).

> **VERDICT: STOP. Critical execution infrastructure is MISSING.**
> The required state is all present and correct, but there is **no committed
> tattoo-enforcement executor** that consumes the mark-route plans. The only code
> that actually enforces tattoos is the untracked Phase 0 RunPod/ComfyUI proof,
> which is out of scope. Implementing Sprint 6's goal would require building new
> infrastructure, not validating existing infrastructure. **No money spent, no
> images generated.** Details below.

---

## 1. Required-state verification — ALL PASS ✅

Verified live against the DB and routing services:

| Check | Expected | Actual | Result |
|---|---|---|---|
| Summer character | id=60 | id=60, "Summer Fielding" | ✅ |
| AdultIdentityModel | id=1 | id=1 (character_id=60) | ✅ |
| active_version_id | 1 | 1 | ✅ |
| status | ready | ready (model_status=ready) | ✅ |
| Active version | runnable | Version id=1, state=active, LoRA weights present | ✅ |
| Training job | completed | Job id=1, state=completed, version_id=1, cost $0.4266 | ✅ |
| Mark routes exist | yes | 2 persisted `mark_render` records | ✅ |
| Butterfly sleeve route | ip_adapter | `pbm_8cff990d` Right upper arm → **ip_adapter** ("matched sleeve/coverage keyword 'sleeve'") | ✅ |
| Ballerina route | controlnet_canny | `pbm_de30011b` Left forearm → **controlnet_canny** ("matched figural keyword 'ballerina'") | ✅ |

The active LoRA artifact:
`https://replicate.delivery/.../trained_model.tar` (Summer v2 SDXL LoRA).

Persisted `mark_render` records carry: `route`, `reference_uri` (R2 detail crop),
`mark_fingerprint`, `body_region`, `side`, and `params_json.reason`.
`control_asset_uri` is **null** for both (no pre-computed Canny/control asset).

---

## 2. Current inference path

**Committed code:**
- `scripts/validate_summer_adult_studio_inference.py` (Phase 3 S4) — resolves the
  runnable Replicate version from the training job and runs **4 fixed text-to-image
  prompts** (portrait headshot, casual sleeveless, blue bikini full body, black dress)
  on **Replicate SDXL + Summer LoRA**, trigger token `TOK`. Hard $0.10 cap.
- `scripts/adult_studio_validation_harness.py` (Phase 3 S5) — wraps the above, applies
  **non-vision** technical checks (prompts completed, URLs returned, cost under cap,
  no errors, active version used) → `technical_verdict`. Always
  `manual_review_required=true`; no CV scoring.

**Scope of this path (by its own design):** *"No tattoo inpaint (LoRA artifact
inference only). No RunPod, no ComfyUI."* It does **not** reference marks,
mark-route plans, tattoo, inpaint, IP-Adapter, ControlNet, masking, or reference
crops anywhere. It is a **text-to-image identity** check, not a tattoo-enforcement
check.

---

## 3. Does tattoo-enforcement EXECUTION infrastructure exist? — NO ❌

The mark-route plans (`MarkRoutePlan`; route values `ip_adapter` /
`controlnet_canny` / `inpaint_direct`) are **produced** by
`adult_identity_routing.py` and **consumed** in committed code only by:

- `adult_identity_readiness.py` — readiness check (read-only)
- `adult_identity_preparation.py` — persists them as `mark_render` rows

**Nothing dispatches on `route` to actually execute enforcement.** The route
strings are declared as constants and stored as data; no production code branches
on them to run IP-Adapter, ControlNet, segmentation masking, or inpaint. There is
no inference provider (the only provider abstraction,
`replicate_training_provider.py`, is **training**-only).

The **only** code that genuinely enforces tattoos is the **untracked Phase 0 proof**:
- `scripts/comfyui_proof_pod_inpaint.py` (+ `runpod_*.py`, `tattoo_inference_test_v2.py`)
- Runs **on a RunPod GPU pod** via ComfyUI/diffusers: base SDXL+LoRA → SegFormer
  human-parsing masks → IP-Adapter butterfly pass (right upper arm) → ControlNet-Canny
  ballerina pass (left forearm).
- It is **untracked** (not committed), **standalone**, and **hardcodes** the two
  passes — it does **not** read the DB `mark_render` plans. It requires **RunPod +
  ComfyUI + GPU spend**.

**Prompt-only enforcement is already refuted.** `tattoo_inference_test_v2.py`
tested whether the LoRA + verbose tattoo descriptors alone place the marks on the
correct limbs via plain Replicate text-to-image. Phase 0 §2 concluded
*"Tattoo-via-LoRA alone does NOT work"* — the LoRA learned the sleeve as a generic
arm feature and never learned the ballerina or limb-specificity. So the in-scope
(no-RunPod) path **cannot** enforce tattoos.

---

## 4. Gap analysis — what is missing for "end-to-end tattoo enforcement"

To validate end-to-end enforcement **driven by the mark-route plans**, the system
needs an **enforcement executor** that, given a base image + each `mark_render`
plan (route + reference crop + region/side), runs:

1. Region segmentation/masking per limb (Phase 0 used SegFormer human-parsing).
2. `ip_adapter` pass for the butterfly sleeve (reference crop on right upper arm).
3. `controlnet_canny` pass for the ballerina (Canny of crop on left forearm).
4. Paste-back / compositing.

**This executor does not exist in committed code.** The only implementation lives in
the untracked RunPod/ComfyUI proof, which:
- is **out of scope** (the production inference path is explicitly "No RunPod, no
  ComfyUI"), and
- is **not wired** to the mark-route plans (hardcoded passes).

Replicate's SDXL-LoRA endpoint (the committed inference path) is **text-to-image
only** and cannot perform regional IP-Adapter/ControlNet inpaint — so the gap
**cannot** be closed within the existing in-scope path.

Closing it would require **building new infrastructure** (either a production
regional-inpaint executor that consumes `mark_render` plans, or standing up the
RunPod/ComfyUI pipeline and wiring it to the plans) — that is a build sprint, not a
validation sprint, and it necessarily involves GPU spend and image generation.

---

## 5. Decision

Per the sprint rules — *"If critical pieces are missing, stop and report exactly
what is missing before spending money or generating images"* — I am **stopping
here**. The missing critical piece is the **tattoo-enforcement executor that
consumes mark-route plans**; the only enforcement-capable code is the out-of-scope
untracked RunPod/ComfyUI proof.

**No code changes made. No money spent. No images generated. No tag committed**
(the `fic-checkpoint-…` tag is reserved for "if code changes are required").

### Options for the user (each needs an explicit go-ahead)

- **A — Dry-run plan validation (in scope, $0):** Build a read-only validator that
  assembles the full enforcement plan from `mark_render` rows + active LoRA +
  reference crops and asserts it is complete/consistent (routes resolved, crops
  fetchable, region/side present) — **without executing or generating**. Validates
  the *plan*, not the *pixels*.
- **B — Stand up the enforcement executor (out of current scope):** Wire the Phase 0
  RunPod/ComfyUI pipeline to consume the DB mark-route plans and run one capped
  Summer validation. Requires lifting the "No RunPod/ComfyUI" boundary and GPU
  spend (Phase 0 measured ≈ $0.01–0.02/run, within the $0.15 cap — but it is new
  infrastructure, not validation of existing infrastructure).
- **C — Hold:** Keep Sprint 6 blocked until the enforcement executor is planned as
  its own build sprint.
