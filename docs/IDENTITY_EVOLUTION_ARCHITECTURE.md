# Identity Evolution Architecture

**Status:** Phase 1 complete — foundations and scaffolding. Generation pipeline: not yet built.

---

## Philosophy

A locked character identity is a canon contract, not a frozen artifact. Evolution must be possible — characters age, scar, change their hair, acquire new accessories. But the **face is the anchor**. The underlying geometry, morphology, and species are permanent. Only presentation may drift.

The system distinguishes between two categories of identity fields, enforced before any refresh generation begins.

---

## Canon Field Classification

### Immutable Canon Fields

These fields define the physical and taxonomic core of a character. **Any proposed evolution that changes these is rejected.** No images are generated. No exceptions.

| Field | Rationale |
|---|---|
| `gender` | Taxonomic identity — not a stylistic choice |
| `age_band` | Anchored to the character's established era |
| `species` | Core morphology root — all downstream traits derive from this |
| `species_tells` | Visual markers that identify species — tied to anchors |
| `body_height` | Structural — embedded in all existing anchor images |
| `body_build` | Structural — embedded in all existing anchor images |
| `face_shape` | B14 facial geometry — the primary similarity anchor |
| `jaw_type` | B14 — defines facial silhouette |
| `cheekbone_type` | B14 — structural midface |
| `eye_shape` | Core identity marker — most recognizable feature |
| `eye_spacing` | Proportional geometry — reader perception |
| `eye_color` | Canonical colorimetry — identity marker |
| `brow_type` | Expression architecture — tied to identity |
| `nose_type` | B14 — facial geometry |
| `lip_type` | B14 — facial geometry |
| `skin_tone` | Canonical colorimetry — identity marker |

### Mutable Canon Fields

These fields may change between versions. The system validates proposed changes and generates a new identity pass if all checks pass.

| Field | Examples of valid evolution |
|---|---|
| `hair_style` | Tied back → loose; long → short |
| `hair_color` | Natural progression, dye, age |
| `hair_length` | Cut, grown out |
| `hair_texture` | Texture can shift with styling |
| `hairline_type` | Aging, shaving |
| `eyebrow_shape` | Grooming, styling |
| `facial_hair_type` | Grown/shaved between arcs |
| `extra_notes` | New scars, tattoos, cosmetics, piercings |
| `style` | Artistic style can shift across arcs (realistic → cinematic) |
| **Signature accessories** | Managed via the accessory system, not spec fields |

---

## Rollback Model

Every evolution attempt automatically takes a **snapshot** of the current identity state before any mutation. The `identity_snapshots` table stores:

- `identity_anchor_json` — full anchor at snapshot time (4 images, face signature, accessories, lock string)
- `identity_spec_json` — full CharacterIdentitySpec at snapshot time
- `snapshot_version` — copied from `character.identity_spec_version`
- `anchor_version` — copied from `character.dna.anchor_version`
- `reason` — `"pre_evolution"` (automatic) or `"manual_backup"` (user-initiated)

**Rollback behaviour:**
- Restores `identity_anchor_json` and `identity_spec_json` on the Character record
- Does **not** touch `visual_locked` — the character remains locked
- Does **not** delete or archive CharacterImage records — all generated images are preserved in history
- The rollback is itself snapshotted before execution (so you can roll forward again)

**Snapshot retention:** No automatic expiry in Phase 1. Pruning strategy TBD based on storage costs.

---

## Refresh Pipeline (Phase 2 — not yet built)

```
User requests evolution →
  1. Validate proposed spec (validate_evolution_spec)
     → Reject if any immutable field changed
  2. take_snapshot(reason="pre_evolution")           ← always, before anything
  3. Similarity pre-check against front anchor
     → vision model compares proposed description to locked face_signature
     → Reject if similarity < threshold (TBD, ~0.80)
  4. Build evolution prompt
     → Starts from locked identity_lock_string as base
     → Applies only mutable field deltas
  5. Generate candidate images (same 4-angle pack flow)
  6. B6 front validation (existing gate — unchanged)
  7. Present candidates to user for review
  8. User accepts → promote to anchors, increment anchor_version
     User rejects → discard images, rollback_to_snapshot
```

The key invariant: **the generation pipeline never runs if the validation gate fails.** Credits/quota are never consumed on rejected evolutions.

---

## Validation Strategy

### Phase 1 (complete)

- `validate_evolution_spec(current_spec_json, proposed_spec)` — pure Python comparison
- Returns: `ok`, `immutable_violations`, `mutable_changes`, `message`
- Zero cost, instant rejection for spec-level violations

### Phase 2 (planned)

- Vision-based similarity check against the locked `face_signature` in `identity_anchor_json`
- Compares: proposed textual description → face_signature.text using embedding similarity
- Threshold: configurable, default ~0.80
- Purpose: catch drift that slips past spec validation (e.g., extreme lighting that obscures features)

### Phase 3 (future)

- Post-generation similarity gate: generated front anchor must match face_signature via CLIP or similar
- Reject and retry (up to N times) before surfacing to user
- Hard reject if similarity < hard floor (~0.65)

---

## Drift Detection

The existing `identity_prompt_hash` in `identity_anchor_json` (SHA256[:16] of the identity lock string) provides a baseline drift fingerprint. Phase 1 adds `compute_immutable_fingerprint()` which hashes only the immutable fields.

For an evolution to be valid:
- `immutable_fingerprint` must match the pre-evolution value (checked in validation gate)
- `identity_prompt_hash` may differ — it reflects the full spec including mutable fields

---

## Future Premium Gating

Identity evolution is a high-value, high-cost operation (4 generated images + validation passes). Premium tier considerations:

| Tier | Evolution access |
|---|---|
| Free | No evolution — initial lock is permanent |
| Standard | 1 evolution per character per calendar month |
| Premium | Unlimited evolutions; priority queue; faster turnaround |
| Collaborator (future) | Co-owned characters: both owners must approve evolution |

**Implementation hook:** The `/characters/{id}/identity-evolution/validate` endpoint already exists and returns a `ok` boolean. Gating is a matter of adding a subscription check before any evolution snapshot is taken. The validation endpoint itself remains free (no images generated).

---

## API Surface (Phase 1)

All endpoints require authentication and character ownership.

| Method | Path | Description |
|---|---|---|
| `GET` | `/characters/{id}/identity-evolution/snapshots` | List snapshots, newest first |
| `POST` | `/characters/{id}/identity-evolution/snapshot` | Take a manual backup snapshot |
| `POST` | `/characters/{id}/identity-evolution/rollback/{snapshot_id}` | Restore from snapshot |
| `POST` | `/characters/{id}/identity-evolution/validate` | Validate proposed spec (dry-run) |

Phase 2 will add:
- `POST /characters/{id}/identity-evolution/begin` — start a refresh (takes snapshot, validates, queues generation)
- `POST /characters/{id}/identity-evolution/accept/{candidate_pack_id}` — accept generated candidates
- `POST /characters/{id}/identity-evolution/abort` — discard candidates and rollback

---

## Files

| File | Purpose |
|---|---|
| `backend/app/models/identity_snapshot.py` | Snapshot ORM model |
| `backend/app/schemas/identity_snapshot.py` | Pydantic read schema |
| `backend/app/services/identity_evolution.py` | Service: immutable/mutable fields, snapshot, validate, rollback |
| `backend/app/api/routes/identity_evolution.py` | REST API scaffolding |
| `backend/alembic/versions/f2a3b4c5d6e7_add_identity_snapshots_table.py` | DB migration |
| `frontend/src/pages/CharacterDetail.tsx` | "Evolve Identity" button + coming-soon modal |

**Untouched by Phase 1:**
- `character_visual.py` — existing generation pipeline unchanged
- `identity_compiler.py` — prompt compilation unchanged
- `identity_front_validator.py` — B6 validation unchanged
- `character_accessory.py` — accessory system unchanged
- All StoryLab files
- All existing anchor, pack, and locking flows
