# Adult Studio — Validation Sprint Runbook

**Status:** Research & proof only. No production implementation, no integration, no production code changes.
**Date:** 2026-06-06
**Goal:** Produce a proof-of-concept image **outside Ficshon** that holds Summer's face + tattoos + body shape in a bikini/beach scene **better than Google currently does** — and capture the evidence.

> **Honesty note (read first):** This runbook is the turnkey route to the evidence. I cannot generate the image or produce real screenshots from inside this environment — the PoC must run on an external GPU service (fal.ai / Replicate / RunPod ComfyUI), and fabricated examples would be worthless as evidence. Every step below is copy-paste runnable by a human (or by me if you wire up one of these services and approve it). The "Evidence" section is a fill-in scorecard so the result is directly comparable to the current Google output.

---

## 0. Summer canon (source of truth)

Pulled from the existing benchmark harness (`backend/tests/test_together_flux_provider.py`), which is the current record of Summer's permanent markings:

- **Face/build:** athletic blonde woman, blue eyes, athletic body shape.
- **Butterfly tattoo:** **left forearm.** *(Task says "butterfly sleeve" — canon currently records a forearm butterfly, not a full sleeve. **Confirm which is canon before scoring.**)*
- **Ballet-slipper tattoo:** **right ankle.** *(Task says "ballet tattoo" — canon places it on the ankle.)*

**Action item before running:** export Summer's **Canon Pack** from Ficshon as the reference set —
multi-view face refs, a body/full-length ref, a **left-forearm butterfly close-up**, and a **right-ankle ballet-slipper close-up**. Target **15–30 images**, varied angle/lighting, clean crops. This set is the training/conditioning input for every track below. *(Read-only export — Canon Studio is not modified.)*

---

## 1. Fastest route to first successful image

Two clocks matter: **time to *any* first image** and **time to a *passing* image** (face + both tattoos + body). The winners are different.

| Track | Method | Time to first image | Holds tattoos+body? | Use as |
|---|---|---|---|---|
| **A** | SDXL + **IP-Adapter** (zero-shot, no training) | **~10 min** | Weak (face-ish, loses tattoos) | Instant baseline / control |
| **B** | **SDXL Character LoRA** (hosted trainer) | ~30–45 min (incl. ~10–15 min train) | **Yes** — learns face+body+tattoos | **The real evidence** |
| **C** | **PhotoMaker** (fal) | ~10 min | **No** (face-only) | Face-identity sanity check only |

**Recommended fastest route to a *passing* image → Track B: hosted SDXL LoRA on Replicate or fal.ai.**
Run Track A first (10 min) as the "instant but weak" control, then Track B for the result that should beat Google.

### Why hosted is acceptable *for this sprint* (but not for production)
- This is a **PoC outside Ficshon**, non-commercial evaluation → the InsightFace non-commercial license issue (which blocks InstantID/FaceID/PuLID *in production*) does **not** apply to research/eval. So you may use the convenient hosted tools to get evidence fast.
- **Bikini/beach is adult-*adjacent*, not explicit** → it generally passes fal/Replicate moderation (unlike lingerie/nude). The success criterion (bikini/beach) is the one most likely to clear hosted moderation, which is why it's the right first target.
- The production-serving conclusion from the pipeline-design doc (self-hosted SDXL on RunPod/Modal, our own moderation) is **unchanged** — see `docs/ADULT_STUDIO_V1_PIPELINE_DESIGN.md`. This sprint just borrows hosted speed to gather proof.

---

## 2. Step-by-step

### Track A — SDXL + IP-Adapter (instant control)
1. Open **fal.ai** SDXL + IP-Adapter (or local ComfyUI with the IP-Adapter node).
2. Reference image: Summer's best front-facing canon face ref (+ optional body ref).
3. Prompt: use **Prompt 1** below. Negative prompt: `deformed, extra limbs, wrong tattoo, blurry face, text, watermark`.
4. Generate 4–8 samples. **Expect:** rough face match, **tattoos usually wrong/missing** — that's the point (shows why zero-shot isn't enough).

### Track B — SDXL Character LoRA (the evidence)
1. **Trainer:** Replicate `stability-ai/sdxl` train, or fal.ai SDXL/Flux LoRA trainer. *(Prefer SDXL to keep it commercial-clean for later; Flux-dev is non-commercial.)*
2. **Upload** the 15–30-image Canon Pack export. Caption with a unique token, e.g. `summ3r woman`, and explicitly caption the tattoo close-ups (`butterfly tattoo on left forearm`, `ballet slipper tattoo on right ankle`).
3. **Train:** ~1000–1500 steps / ~10–15 min. Download the LoRA weights.
4. **Generate** the 4 benchmark prompts (below) at SDXL 1024×1024, ~30 steps, with the LoRA loaded at weight ~0.8–1.0.
5. **Expect:** strong face lock + both tattoos in roughly the right place + athletic build — the comparison target vs Google.

### Track C — PhotoMaker (face-only sanity check)
1. fal.ai PhotoMaker, stack 3–4 Summer face refs.
2. Prompt 1. **Expect:** good face, **no tattoos, no body canon** → confirms face-only methods can't satisfy the criteria. One image is enough to document the limitation.

### Benchmark prompts (canon-grounded — reuse across tracks for apples-to-apples)
- **Prompt 1 (yellow bikini / golden hour):** "Summer, an athletic blonde woman with blue eyes, wearing a yellow string bikini standing on a white sand beach. Butterfly tattoo on left forearm visible. Ballet-slipper tattoo on right ankle. Warm golden-hour lighting. Photorealistic."
- **Prompt 2 (blue bikini / tropical):** "Summer, athletic blonde, blue eyes, bright blue bikini on a sunny tropical beach. Butterfly tattoo on left forearm. Ballet-slipper tattoo on right ankle. Clear ocean background. Photorealistic."
- **Prompt 3 (full-body framing):** same as Prompt 1 but "full-body shot, standing, both forearms and ankles visible" — forces the tattoos into frame for scoring.
- **Prompt 4 (control, covered):** floral sundress courtyard scene — confirms identity holds when skin/tattoos are mostly covered.

---

## 3. Cost estimates

| Item | Estimate | Basis |
|---|---|---|
| **LoRA training (once per character)** | **~$1–3** on Replicate; **~$5–10** on fal | Replicate L40S ≈ $0.000975/s × ~600–900s ≈ $0.6–0.9; fal LoRA ≈ $0.008/step × ~1000 steps ≈ $8 |
| **Generation (per image)** | **~$0.01–0.05** hosted; lower self-hosted | fal/Replicate SDXL per-image range; self-host = GPU-seconds only |
| **Full validation sprint (all tracks, ~30–50 images)** | **~$5–20 total** | 1 train + a few dozen gens + IP-Adapter/PhotoMaker samples |

Verdict: the entire evidence sprint is a **single-digit-to-low-double-digit dollar** spend. Training cost is one-time per character; per-image cost is negligible at validation scale.

---

## 4. Implementation complexity

- **Track A (IP-Adapter):** Low. Upload ref + prompt. No training.
- **Track B (LoRA):** **Low–Medium.** Caption + upload dataset, run a hosted trainer, load weights, prompt. The only "work" is curating the 15–30-image dataset and captioning the tattoo close-ups. No infra to manage on hosted trainers.
- **Track C (PhotoMaker):** Low, but **inadequate** (face-only) — included only to document the gap.

Nothing in this sprint requires Ficshon code. The hard part is **dataset quality**, not engineering — which is exactly why the Canon Pack (already multi-view, already includes marking refs) is the unlock.

---

## 5. Evidence to capture (fill-in scorecard)

For each track, save the generated PNGs and the exact prompt/seed, then score against the **current Google output** for the same prompt. Score each axis **0–3** (0 = absent/wrong, 1 = hinted, 2 = mostly right, 3 = canon-accurate). This mirrors the manual-review criteria already used in the Summer benchmark harness.

| Axis | Google (current) | Track A IP-Adapter | Track B LoRA | Track C PhotoMaker |
|---|---|---|---|---|
| Face identity | _ /3 | _ /3 | _ /3 | _ /3 |
| Butterfly (L forearm) | _ /3 | _ /3 | _ /3 | _ /3 |
| Ballet slipper (R ankle) | _ /3 | _ /3 | _ /3 | _ /3 |
| Body shape (athletic) | _ /3 | _ /3 | _ /3 | _ /3 |
| Bikini/beach renders cleanly (no refusal) | _ /3 | _ /3 | _ /3 | _ /3 |
| **Total** | **_ /15** | **_ /15** | **_ /15** | **_ /15** |

**Success criterion met when:** Track B total **> Google total**, with Butterfly **and** Ballet each ≥ 2 (Google's known weak spot is tattoo retention).

**Evidence package to hand back:**
1. The 4 LoRA images (Prompts 1–4) + their seeds/prompts.
2. Side-by-side: Google vs Track B for Prompt 1 and Prompt 3 (full-body).
3. One IP-Adapter and one PhotoMaker sample showing the tattoo-loss failure mode.
4. The filled scorecard above + the LoRA training time/cost actuals.

---

## 6. Decision gate (what this sprint proves)

- **If Track B beats Google** (expected, on tattoo/body retention) → green-light the v1 pipeline (`docs/ADULT_STUDIO_V1_PIPELINE_DESIGN.md`): per-character SDXL LoRA, self-hosted serving.
- **If Track B only ties Google on tattoos** → the LoRA dataset needs more/closer tattoo refs (a captioning/data problem, not a method problem) — iterate on the Canon Pack export, not the approach.
- **If even hosted moderation refuses bikini/beach** → confirms the self-hosted-serving requirement is non-negotiable and moves it up the priority list.

---

## Out of scope (unchanged)
No production code, no provider integration, no content-policy change, and no changes to Canon Studio / Identity OS / Face Canon / Body Canon / permanent markings / Scene Router / Canon Router / tattoo routing / normal image-generator logic.

## Sources
- [Replicate SDXL LoRA training (L40S ~$0.000975/s)](https://replicate.com/stability-ai/sdxl/train)
- [fal LoRA training (commercial use, ~$0.008/step)](https://fal.ai/models/fal-ai/flux-lora-fast-training)
- [PhotoMaker on fal (face-only, multi-ref)](https://fal.ai/models/fal-ai/photomaker)
- [Image model price comparison (Replicate vs fal)](https://pricepertoken.com/image)
- [fal Trust & Safety / NSFW policy](https://fal.ai/legal/trust-and-safety)
- [InstantID/InsightFace non-commercial (production blocker, not eval)](https://huggingface.co/InstantX/InstantID/discussions/2)
