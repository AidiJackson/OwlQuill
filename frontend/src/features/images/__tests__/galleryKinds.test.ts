import { describe, it, expect } from 'vitest';
import {
  GALLERY_KINDS,
  GALLERY_KIND_LABELS,
  isGalleryKind,
} from '../galleryKinds';

describe('gallery kind allowlist', () => {
  it('pins the exact allowlist that mirrors the backend', () => {
    // This assertion is the point of the file. It fails loudly when someone
    // adds a kind here without adding it to PUBLIC_GALLERY_KINDS in
    // backend/app/schemas/character_image.py — or, worse, removes one and
    // silently empties every gallery.
    expect([...GALLERY_KINDS]).toEqual(['generated', 'cover', 'scene_only']);
  });

  it('rejects identity and anchor working references', () => {
    // These are the kinds a character is BUILT from. They must never be
    // offered as an avatar, a cover, or a public gallery piece.
    for (const kind of [
      'identity_sketch',
      'anchor_front',
      'anchor_side',
      'face_ref',
      'body_front',
    ]) {
      expect(isGalleryKind(kind)).toBe(false);
    }
  });

  it('accepts finished output', () => {
    expect(isGalleryKind('generated')).toBe(true);
    expect(isGalleryKind('cover')).toBe(true);
    expect(isGalleryKind('scene_only')).toBe(true);
  });

  it('treats an unknown kind as not shareable', () => {
    // Fail closed: a kind the backend grows later is a working reference until
    // this list is deliberately updated, never shareable by default.
    expect(isGalleryKind('some_future_kind')).toBe(false);
    expect(isGalleryKind('')).toBe(false);
  });

  it('labels every allowlisted kind', () => {
    // A kind with no label renders as its raw enum name in a <select>, which
    // is how "scene_only" leaks into the UI.
    for (const kind of GALLERY_KINDS) {
      expect(GALLERY_KIND_LABELS[kind]).toBeTruthy();
    }
    expect(Object.keys(GALLERY_KIND_LABELS).sort()).toEqual([...GALLERY_KINDS].sort());
  });
});
