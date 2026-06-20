/**
 * S24AQ — v2 pack timeout recovery tests.
 *
 * Verifies the "all 13 slots populated" detection and pack reconstruction used
 * to recover a completed-but-timed-out generation without regenerating.
 */

import { describe, it, expect } from 'vitest';
import {
  V2_RECOVERY_SLOTS,
  isV2PackComplete,
  buildPackFromCanon,
} from '../canonRecovery';
import type { CharacterCanonRead } from '../types';

/** A canon with every v2 slot populated (mirrors character 62's recovered state). */
function fullCanon(): CharacterCanonRead {
  return {
    id: 8,
    character_id: 62,
    status: 'draft',
    face_locked: false,
    body_locked: false,
    face_canon: {
      face_front_image_url: 'https://cdn/face_front.png',
      face_left_3q_image_url: 'https://cdn/face_left_3q.png',
      face_right_3q_image_url: 'https://cdn/face_right_3q.png',
      face_profile_image_url: 'https://cdn/face_profile.png',
      face_expression_image_url: 'https://cdn/face_expression.png',
    },
    body_canon: {
      body_front_image_url: 'https://cdn/body_front.png',
      body_left_image_url: 'https://cdn/body_left.png',
      body_right_image_url: 'https://cdn/body_right.png',
      body_back_image_url: 'https://cdn/body_back.png',
      torso_front_image_url: 'https://cdn/torso_front.png',
      torso_side_image_url: 'https://cdn/torso_side.png',
      standing_relaxed_image_url: 'https://cdn/standing_relaxed.png',
      seated_relaxed_image_url: 'https://cdn/seated_relaxed.png',
    },
  };
}

describe('V2_RECOVERY_SLOTS', () => {
  it('covers exactly the 13 v2 canon slots', () => {
    expect(V2_RECOVERY_SLOTS).toHaveLength(13);
    expect(V2_RECOVERY_SLOTS.map((s) => s.slot)).toEqual([
      'face_front', 'face_left_3q', 'face_right_3q', 'face_profile', 'face_expression',
      'body_front', 'body_left', 'body_right', 'body_back',
      'torso_front', 'torso_side', 'standing_relaxed', 'seated_relaxed',
    ]);
  });
});

describe('isV2PackComplete', () => {
  it('returns true when all 13 slots hold a URL', () => {
    expect(isV2PackComplete(fullCanon())).toBe(true);
  });

  it('returns false when a single body slot is missing', () => {
    const canon = fullCanon();
    canon.body_canon!.seated_relaxed_image_url = null;
    expect(isV2PackComplete(canon)).toBe(false);
  });

  it('returns false when a single face slot is missing', () => {
    const canon = fullCanon();
    delete canon.face_canon!.face_profile_image_url;
    expect(isV2PackComplete(canon)).toBe(false);
  });

  it('treats empty/whitespace URLs as not populated', () => {
    const canon = fullCanon();
    canon.body_canon!.body_back_image_url = '   ';
    expect(isV2PackComplete(canon)).toBe(false);
  });

  it('returns false for null / missing canon sections', () => {
    expect(isV2PackComplete(null)).toBe(false);
    expect(isV2PackComplete(undefined)).toBe(false);
    expect(isV2PackComplete({ ...fullCanon(), body_canon: null })).toBe(false);
    expect(isV2PackComplete({ ...fullCanon(), face_canon: undefined })).toBe(false);
  });
});

describe('buildPackFromCanon', () => {
  it('reconstructs a clean 13-card pack with zero spend when complete', () => {
    const pack = buildPackFromCanon(fullCanon());
    expect(pack).not.toBeNull();
    expect(pack!.cards).toHaveLength(13);
    expect(pack!.image_count).toBe(13);
    expect(pack!.total_spend).toBe(0);
    expect(pack!.clean_pass).toBe(true);
    expect(pack!.dry_run).toBe(false);
    // Every card carries its slot URL and a generated status.
    for (const card of pack!.cards) {
      expect(card.url).toBeTruthy();
      expect(card.status).toBe('generated');
    }
    // Face/body sections line up with the slot taxonomy.
    expect(pack!.cards.filter((c) => c.section === 'face')).toHaveLength(5);
    expect(pack!.cards.filter((c) => c.section === 'body')).toHaveLength(8);
  });

  it('returns null when the pack is incomplete (so the real error surfaces)', () => {
    const canon = fullCanon();
    canon.body_canon!.torso_side_image_url = null;
    expect(buildPackFromCanon(canon)).toBeNull();
  });

  it('returns null for an empty canon', () => {
    expect(buildPackFromCanon(null)).toBeNull();
  });
});
