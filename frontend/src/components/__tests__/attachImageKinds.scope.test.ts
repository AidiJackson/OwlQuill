import { describe, it, expect } from 'vitest';
import { isAttachableImage, ATTACHABLE_KIND_LIST } from '../attachImageKinds';

/**
 * The post picker's kind allowlist. This mirrors the server's
 * POST_ATTACHABLE_IMAGE_KINDS, which is the actual boundary — but a drift here
 * means offering a user something the server will then refuse, so it is worth
 * pinning.
 */
describe('post image kind allowlist', () => {
  it('offers the three publishable kinds', () => {
    expect([...ATTACHABLE_KIND_LIST].sort()).toEqual(['cover', 'generated', 'scene_only']);
  });

  it.each(['generated', 'cover', 'scene_only'])('allows %s', (kind) => {
    expect(isAttachableImage({ kind })).toBe(true);
  });

  it.each([
    'identity_sketch',
    'identity_face_ref',
    'identity_body_front',
    'identity_body_back',
    'identity_tattoo_layout',
    'identity_body_map',
    'identity_final_character_card',
    'anchor_front',
    'anchor_torso',
    'anchor_full_body',
    'accessory_design',
    'accessory_fit',
  ])('never offers private production material: %s', (kind) => {
    expect(isAttachableImage({ kind })).toBe(false);
  });

  it('rejects unknown kinds by default', () => {
    // Allowlist, not denylist: a kind added server-side is private here until
    // someone opts it in deliberately.
    expect(isAttachableImage({ kind: 'some_future_private_kind' })).toBe(false);
  });
});
