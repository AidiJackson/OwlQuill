import { describe, it, expect } from 'vitest';
import { GALLERY_KINDS, isGalleryKind } from '../galleryKinds';
import { ATTACHABLE_KIND_LIST } from '../../../components/attachImageKinds';
import {
  MAX_REFERENCES,
  REFERENCE_ROLES,
  REFERENCE_ROLE_LABELS,
  SELECTABLE_REFERENCE_KINDS,
  isSelectableReferenceKind,
} from '../referenceKinds';

describe('manual reference selection', () => {
  it('pins the selectable-kind allowlist that mirrors the backend', () => {
    // Fails loudly if this drifts from REFERENCE_SELECTABLE_IMAGE_KINDS in
    // backend/app/models/character_image.py. The server is the authority; this
    // list decides what the founder is even shown.
    expect([...SELECTABLE_REFERENCE_KINDS]).toEqual([
      'uploaded',
      'generated',
      'scene_only',
      'cover',
    ]);
  });

  it('never offers canon or identity material as a hand-pickable reference', () => {
    // Which canon slots reach the provider is the reference router's decision,
    // made from locked canon. A second, hand-picked path into the same payload
    // would blur the canon-vs-manual boundary this feature has to keep sharp.
    for (const kind of [
      'identity_face_ref',
      'identity_sketch',
      'identity_body_front',
      'identity_body_map',
      'accessory_design',
      'accessory_fit',
      'anchor_front',
      'anchor_full_body',
    ]) {
      expect(SELECTABLE_REFERENCE_KINDS as readonly string[]).not.toContain(kind);
    }
  });

  it('caps the selection at four, matching MAX_MANUAL_REFERENCES', () => {
    expect(MAX_REFERENCES).toBe(4);
  });

  it('offers exactly the documented roles', () => {
    expect([...REFERENCE_ROLES]).toEqual([
      'unspecified',
      'character_appearance',
      'clothing',
      'environment',
      'other',
    ]);
    for (const role of REFERENCE_ROLES) {
      expect(REFERENCE_ROLE_LABELS[role]).toBeTruthy();
    }
  });
});

describe('uploaded images stay private', () => {
  it('is not a public gallery kind', () => {
    // An upload is a private working reference: the founder supplied it to
    // steer generation, not to publish it, and Ficshon has no provenance for it.
    expect(GALLERY_KINDS as readonly string[]).not.toContain('uploaded');
    expect(isGalleryKind('uploaded')).toBe(false);
  });

  it('is not attachable to a post', () => {
    expect(ATTACHABLE_KIND_LIST as readonly string[]).not.toContain('uploaded');
  });

  it('is still selectable as a generation reference', () => {
    // The whole point of storing it: private to the character, usable as input.
    expect(SELECTABLE_REFERENCE_KINDS as readonly string[]).toContain('uploaded');
    expect(isSelectableReferenceKind('uploaded')).toBe(true);
  });

  it('treats an unknown kind as unselectable', () => {
    // Fail closed, same rule as the gallery allowlist: a kind the backend grows
    // later is not hand-pickable until this list is deliberately updated.
    expect(isSelectableReferenceKind('some_future_kind')).toBe(false);
  });
});
