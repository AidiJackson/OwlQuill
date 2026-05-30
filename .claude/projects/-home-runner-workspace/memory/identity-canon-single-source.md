---
name: identity-canon-single-source
description: CharacterIdentityCanon is the only identity-truth source; legacy identity systems must not feed generation
metadata:
  type: project
---

Identity truth for image generation lives **only** in `CharacterIdentityCanon` (table `character_identity_canon`), compiled via `app/services/canon_compiler.py`. The main "Generate Images" route is `POST /characters/{id}/image-generator/generate` in `app/api/routes/image_generator.py`.

These legacy sources must **never** be read as identity truth in generation: `identity_anchor_json` (signature accessory / anchors), `body_identity_json` (body slots), `CharacterStyleElements` (shop/acquisition data only), candidate slots, jewellery auto-injection (`style_elements._jewellery_neck_context_trigger`), signature-accessory auto-preserve (`character_accessory.build_accessory_prompt_block`).

Rules confirmed by the user (2026-05-30):
- `include_character=True` requires CharacterIdentityCanon; if missing/incomplete return graceful HTTP 409 `"Character canon incomplete"` — no legacy fallback.
- Scene generations save as `SCENE_ONLY` and never mutate canon.
- Removable accessories inject only when explicitly requested via canon `accessories_json` trigger keywords.
- When removing a legacy contract, **migrate** affected route tests to the canon contract rather than skipping — unless a test purely covers a deleted legacy helper.

**Why:** legacy reads caused accessory/tattoo leakage (e.g. Leonardo's silver chain) and made the canon rebuild cosmetic.
**How to apply:** route prompt assembly through `compile_canon_prompt` + `collect_canon_reference_urls`; keep legacy helper functions only if still covered by their own unit tests, but never call them from the generation route.
