import { describe, it, expect } from 'vitest';
import { isAttachableImage } from '../attachImageKinds';

function img(kind: string) {
  return { kind };
}

describe('isAttachableImage', () => {
  it('accepts current scene generator output (scene_only)', () => {
    expect(isAttachableImage(img('scene_only'))).toBe(true);
  });

  it('accepts legacy library images (generated)', () => {
    expect(isAttachableImage(img('generated'))).toBe(true);
  });

  it('excludes identity/anchor canon reference cards', () => {
    for (const k of [
      'anchor_front',
      'identity_face_ref',
      'identity_body_front',
      'identity_final_character_card',
      'accessory_design',
    ]) {
      expect(isAttachableImage(img(k))).toBe(false);
    }
  });

  // Changed deliberately in the character-scoped-media fix: `cover` is now part
  // of the publishable allowlist alongside `generated` and `scene_only`. It was
  // previously excluded as "not a normal post attachment"; a character's cover
  // is its own public banner, so publishing it leaks nothing.
  //
  // The kinds that must never be attachable are the private production material
  // covered above and in attachImageKinds.scope.test.ts.
  it('accepts a character cover banner', () => {
    expect(isAttachableImage(img('cover'))).toBe(true);
  });
});
