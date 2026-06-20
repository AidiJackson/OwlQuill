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

  it('excludes cover banners (not a normal post attachment)', () => {
    expect(isAttachableImage(img('cover'))).toBe(false);
  });
});
