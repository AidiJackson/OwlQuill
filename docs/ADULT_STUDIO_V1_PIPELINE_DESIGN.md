# Adult Studio v1 — Technical Pipeline Design

**Status:** Design only. No image generation implemented. No code changes in this checkpoint.
**Date:** 2026-06-06
**Scope:** Identity-lock approach for Adult Studio (swimwear / bikini / lingerie / underwear / mature romance / adult-adjacent character imagery), using the existing **Canon Pack** as source of truth.
**Constraint:** Canon Studio, Identity OS, Face/Body Canon, permanent markings, Scene/Canon routers, and tattoo routing are **untouched**. Adult Studio is a separate workflow.

---

## TL;DR

- **Recommendation (v1):** **Per-character SDXL Character LoRA**, trained from the existing Canon Pack, served on **self-hosted ComfyUI on raw GPU (RunPod / Modal)**.
- **Fallback (v1.0 / pre-training):** **IP-Adapter (SDXL) zero-shot** conditioning from canon face/body refs on the same self-hosted stack — no per-character training, weaker identity, ships fastest.
- **Why not the obvious zero-shot face tools:** InstantID, IP-Adapter **FaceID**, and PuLID all depend on **InsightFace** face encoders whose model weights are **non-commercial** by license. Managed APIs (fal.ai PhotoMaker/InstantID) additionally apply **content moderation** that will block adult-adjacent prompts. Both kill them for our commercial + mature-content use case.

The two decisive constraints are **commercial licensing** and **adult-content policy**. They eliminate most of the convenient options before quality even enters the conversation.

---

## The two constraints that decide everything

### 1. The InsightFace licensing trap

InstantID, IP-Adapter **FaceID**, and PuLID get their strong face identity from an **InsightFace** recognition model (e.g. `antelopev2` / `buffalo_l`). The wrapper *code* is often Apache-2.0, but the **InsightFace model weights are licensed for non-commercial / research use only**. Shipping them in a paid product (Ficshon) requires a **separate commercial license from InsightFace** — or replacing the encoder.

This single fact demotes the three strongest zero-shot face-identity methods to "needs a license deal before we can ship."

### 2. Adult-content moderation on managed APIs

Adult Studio's entire reason to exist is swimwear / lingerie / mature scenes. Managed model endpoints (fal.ai, Replicate) run automated moderation (fal integrates OpenAI's Omni moderation) and will **filter or refuse adult-adjacent generations** — and even where lawful adult content is tolerated, the policy surface is a moving target we don't control.

Raw-GPU platforms (**RunPod, Modal**) sell *compute* and put content responsibility on us. A **private, authenticated, self-hosted** ComfyUI/SDXL stack is therefore the only path that gives us *both* commercial control *and* the ability to render mature content lawfully — with our own moderation (block illegal categories: CSAM, NCII, real-person likeness).

> Net: the serving decision is essentially forced — **self-hosted on raw GPU**, not a managed model API. The remaining real choice is *which identity-lock method* runs on that stack.

---

## Method comparison

Scored against the eight evaluation axes. "Commercial" = shippable in a paid product without a bespoke license deal. "Adult OK" = the *method* doesn't block mature content (assumes self-hosted serving).

| Method | 1. Face identity | 2. Multi face refs | 3. Body/tattoo | 4. Adult-adjacent | 5. Commercial | 6. Cost | 7. Complexity | 8. Fits MVP |
|---|---|---|---|---|---|---|---|---|
| **InstantID** | Excellent (1 ref) | Weak (single embed) | No (face only) | Method yes / **API no** | ❌ InsightFace NC | Low/gen, no train | Low | Blocked by license |
| **IP-Adapter FaceID** | Strong | Partial (avg embeds) | No (face only) | Method yes | ❌ InsightFace NC | Low/gen, no train | Low–Med | Blocked by license |
| **PuLID** | Excellent | Partial | No (face only) | Method yes | ❌ InsightFace NC (+ FLUX-dev NC if FLUX variant) | Low/gen | Med | Blocked by license |
| **PhotoMaker** | Good (stacks multi refs) | **Yes** (native) | No (face only) | **API-moderated** | ✅ code OK | Low/gen | Low | Self-host only; face-only |
| **IP-Adapter (plain, SDXL)** | Moderate | Yes (multi-image) | Partial (style/clothing cues) | Method yes | ✅ Apache-2.0, no InsightFace | Low/gen, no train | Low | **Yes — fallback** |
| **Character LoRA (SDXL)** | **Excellent** | **Yes** (whole training set) | **Yes** (learns body, markings, tattoos) | **Yes** (self-host) | ✅ trained weights are ours | Train: ~$0.5–3 once; gen low | Med–High | **Yes — recommended** |

Notes:
- **Face-only methods (InstantID/FaceID/PuLID/PhotoMaker) cannot preserve body or tattoos** — they encode the *face*. Our permanent body markings and body canon would not survive them. That's a structural mismatch with Ficshon's canon model, independent of licensing.
- **LoRA is the only method that learns face + body + tattoos together**, because it trains on the full canon pack (multi-view face, body, marking refs) rather than a single face embedding.
- **FLUX-based variants** (FLUX PuLID, FLUX LoRA) inherit **FLUX.1 [dev]'s non-commercial license** from Black Forest Labs → another license deal. SDXL avoids this entirely (open RAIL-M, commercial OK). **Stay on SDXL for v1.**

---

## Per-axis findings

1. **Preserve face identity** — LoRA: best (learns from many views). InstantID/PuLID: excellent zero-shot but face-only + licensed. IP-Adapter plain: moderate.
2. **Multiple face refs** — LoRA and PhotoMaker and plain IP-Adapter: yes. InstantID: effectively single-ref. Canon Pack gives us multi-view refs, which favors LoRA.
3. **Body / tattoo detail** — **Only LoRA** does this well. All face-encoder methods ignore body/markings → would break permanent-marking canon.
4. **Adult-adjacent content** — Any method is *capable*; the gate is the **serving platform**, not the method. Self-host → OK. Managed API → filtered.
5. **Commercial in Ficshon** — LoRA (SDXL) and plain IP-Adapter (SDXL): clean. InstantID/FaceID/PuLID: need InsightFace license. PhotoMaker code OK but face-only.
6. **Cost** — LoRA: one-time train ~$0.5–3/character (≈10–15 min on an L40S-class GPU at ~$0.001/s; fal LoRA training ≈ $0.008/step as a reference point), then cheap per-gen. Zero-shot methods: no training, ~$0.01–0.08-equivalent of GPU-seconds per image self-hosted. At scale, **self-hosted GPU-seconds beat per-image API pricing.**
7. **Implementation complexity** — Plain IP-Adapter: low. LoRA: medium (adds a training job + weight storage + status states, which the MVP shell already anticipates). InstantID family: low *code* but high *legal*.
8. **Fits current MVP** — The Adult Studio shell already has: character selector, **Not trained / Training / Ready / Failed** status, and a **"Prepare 18+ Identity"** action. That state machine maps **exactly onto a LoRA training job**. The MVP was, in effect, designed for the LoRA path.

---

## Recommendation — Adult Studio v1

**Per-character SDXL Character LoRA, trained from the Canon Pack, served on self-hosted ComfyUI (RunPod or Modal), private + authenticated, with our own moderation layer.**

Why it wins:
- **Only option that preserves face + body + tattoos** — matches Ficshon's canon contract (face anchor + body canon + permanent markings).
- **Commercially clean** on SDXL — trained weights are ours; no InsightFace or FLUX-dev license dependency.
- **Adult-capable** because we self-host and own the moderation policy (block illegal categories ourselves).
- **The MVP's existing training-status UI is already the right shape** — Prepare → Training → Ready maps to a real LoRA job with near-zero UI rework.
- **Canon Pack is the perfect training set** — multi-view face refs, body refs, and marking refs are exactly what a character LoRA needs.

Trade-off accepted: a **per-character training step** (minutes + a few cents) before first adult generation. The shell already communicates this ("Prepare 18+ Identity" → "Ready").

## Fallback — Adult Studio v1.0 (ship-first, pre-training)

**Plain IP-Adapter on SDXL (multi-image), zero-shot from canon face/body refs, same self-hosted stack.**

Use when: we want to demo/ship *before* the training pipeline is wired, or for characters that haven't trained yet.
- No per-character training → instant "generate."
- Commercially clean (Apache-2.0, no InsightFace).
- **Weaker identity**, especially body/tattoo fidelity → position as "preview quality," and upgrade the character to LoRA for "locked" quality.

This gives a graceful degradation ladder: **IP-Adapter preview → LoRA locked**, surfaced through the same Not-trained/Ready states.

---

## Rough implementation phases (future work — not in this checkpoint)

**Phase A — Serving foundation (infra)**
- Stand up private ComfyUI on RunPod or Modal (serverless GPU), authenticated, no public ComfyUI endpoint, short-lived output storage.
- Base model: SDXL (commercial-clean checkpoint).
- Define our own moderation gate (hard-block: CSAM, NCII, real-person likeness; allow: lawful adult-adjacent).

**Phase B — Fallback path live (IP-Adapter zero-shot)**
- Wire Adult Studio "generate" to SDXL + IP-Adapter using canon refs pulled from the existing Canon Pack (read-only; Canon Studio untouched).
- Ship as "preview quality." Validate the end-to-end self-hosted pipeline with real adult-adjacent prompts.

**Phase C — LoRA training job (the real v1)**
- Backend job: given a character's Canon Pack, export training set → train SDXL LoRA → store weights keyed to character.
- Drive the existing **Prepare 18+ Identity** button: enqueue → `Training` → `Ready` / `Failed` (replace the current placeholder timer with real job status).
- Storage + lifecycle for per-character LoRA weights (and re-train when canon refreshes).

**Phase D — LoRA generation path**
- Adult Studio generate loads the character's LoRA + SDXL and renders. Prefer LoRA when `Ready`, else fall back to IP-Adapter preview.

**Phase E — Hardening**
- Moderation/audit logging, rate limits, cost controls, consent/age gating, takedown path, and red-team of identity-leak and policy edge cases before any public exposure.

---

## Explicitly out of scope here
- No image generation implemented.
- No provider integration.
- No content-policy change.
- No changes to Canon Studio / Identity OS / Face Canon / Body Canon / permanent markings / Scene Router / Canon Router / tattoo routing / normal image generator provider logic.

---

## Sources
- [InstantX/InstantID — non-commercial due to InsightFace (HF discussion)](https://huggingface.co/InstantX/InstantID/discussions/2)
- [InsightFace enterprise/commercial model licensing](https://www.insightface.ai/services/models-commercial-licensing)
- [InstantID repo](https://github.com/instantX-research/InstantID)
- [PhotoMaker on fal (compute-second pricing, commercial use)](https://fal.ai/models/fal-ai/photomaker)
- [FLUX PuLID (Apache-2.0 wrapper; FLUX.1 [dev] non-commercial base)](https://www.aimodels.fyi/models/replicate/flux-pulid-zsxkib)
- [Replicate SDXL LoRA training (L40S ~$0.000975/s)](https://replicate.com/stability-ai/sdxl/train)
- [fal LoRA training (commercial use, ~$0.008/step)](https://fal.ai/models/fal-ai/flux-lora-fast-training)
- [Image model price comparison (Replicate vs fal)](https://pricepertoken.com/image)
- [fal Trust & Safety / NSFW policy](https://fal.ai/legal/trust-and-safety)
- [RunPod NSFW policy analysis (compute, not content marketplace)](https://cling-ai.com/blog/runpod-nsfw-policy-adult-content-allowed-2026)
- [PuLID vs InstantID vs FaceID comparison](https://medium.com/design-bootcamp/ai-face-swap-battle-pulid-vs-instantid-vs-faceid-2f08db230509)
