// The Admin Creator role vocabulary, and the boundary that keeps it out of
// /images.
//
// The selector — not the card's position — decides what a reference is
// authority for. These tests pin the offered list, the identity buckets, and
// the compatibility decision for drafts written before the selector existed.
import { describe, it, expect } from 'vitest';
import { REFERENCE_ROLES } from '@/features/images/referenceKinds';
import {
  ADMIN_CREATOR_ROLES,
  ADMIN_CREATOR_ROLE_VALUES,
  DEFAULT_ROLE,
  FEATURE_ROLES,
  IDENTITY_ROLES,
  ROLE_GROUPS,
  ROLE_HINTS,
  isAdminCreatorRole,
  isFeatureRole,
  isIdentityRole,
  roleLabel,
} from '../referenceRoles';

describe('admin creator roles — the offered vocabulary', () => {
  it('offers exactly the documented choices, in order', () => {
    expect(ADMIN_CREATOR_ROLE_VALUES).toEqual([
      'unspecified',
      'character_1',
      'character_2',
      'eyes',
      'nose',
      'mouth_lips',
      'eyebrows',
      'hair',
      'skin_complexion',
      'clothing',
      'environment',
      'tattoo_mark',
      'pose_composition',
      'other',
    ]);
  });

  it('keeps the selector list and its values in lockstep', () => {
    expect(ADMIN_CREATOR_ROLES.map((r) => r.value)).toEqual([...ADMIN_CREATOR_ROLE_VALUES]);
    expect(ADMIN_CREATOR_ROLES.every((r) => r.label.length > 0)).toBe(true);
  });

  it('labels them the way the founder was promised', () => {
    expect(roleLabel('character_1')).toBe('Character 1');
    expect(roleLabel('character_2')).toBe('Character 2');
    expect(roleLabel('clothing')).toBe('Clothing');
    expect(roleLabel('environment')).toBe('Environment / Scene');
    expect(roleLabel('tattoo_mark')).toBe('Tattoo / Permanent Mark');
    expect(roleLabel('pose_composition')).toBe('Pose / Composition');
    expect(roleLabel('other')).toBe('Other');
    expect(roleLabel('unspecified')).toBe('Unspecified');
    expect(roleLabel('eyes')).toBe('Eyes');
    expect(roleLabel('nose')).toBe('Nose');
    expect(roleLabel('mouth_lips')).toBe('Mouth / Lips');
    expect(roleLabel('eyebrows')).toBe('Eyebrows');
    expect(roleLabel('hair')).toBe('Hair');
    expect(roleLabel('skin_complexion')).toBe('Skin / Complexion');
  });

  it('defaults a card to unspecified', () => {
    // Backwards compatible: a card the founder has not classified says nothing
    // to the provider rather than something invented.
    expect(DEFAULT_ROLE).toBe('unspecified');
  });

  it('names both identity buckets and nothing else', () => {
    expect(IDENTITY_ROLES).toEqual(['character_1', 'character_2']);
    expect(isIdentityRole('character_1')).toBe(true);
    expect(isIdentityRole('character_2')).toBe(true);
    for (const role of ['clothing', 'environment', 'tattoo_mark', 'pose_composition', 'other', 'unspecified'] as const) {
      expect(isIdentityRole(role)).toBe(false);
    }
  });

  it('names the six ISOLATED attribute roles and no identity role', () => {
    expect(FEATURE_ROLES).toEqual([
      'eyes',
      'nose',
      'mouth_lips',
      'eyebrows',
      'hair',
      'skin_complexion',
    ]);
    for (const role of FEATURE_ROLES) {
      expect(isFeatureRole(role)).toBe(true);
      // The load-bearing separation: attribute evidence is never identity
      // evidence, on this side of the wire as well as the provider's.
      expect(isIdentityRole(role)).toBe(false);
    }
    for (const role of ['character_1', 'character_2', 'clothing', 'environment',
                        'tattoo_mark', 'pose_composition', 'other', 'unspecified'] as const) {
      expect(isFeatureRole(role)).toBe(false);
    }
  });

  it('groups every offered role exactly once for the selector', () => {
    // An ungrouped role would simply not render — the selector iterates the
    // groups, not the flat list.
    const grouped = ROLE_GROUPS.flatMap((g) => g.roles);
    expect([...grouped].sort()).toEqual([...ADMIN_CREATOR_ROLE_VALUES].sort());
    expect(new Set(grouped).size).toBe(grouped.length);
  });

  it('keeps every attribute hint honest about what it excludes', () => {
    // The hint is the only thing standing between "Eyes" and a founder
    // reasonably reading it as "this face".
    for (const role of FEATURE_ROLES) {
      expect(ROLE_HINTS[role]).toMatch(/^Only /);
      expect(ROLE_HINTS[role]).toMatch(/Not this person’s (identity|face)\.$/);
    }
  });

  it('has a hint for every offered role', () => {
    for (const role of ADMIN_CREATOR_ROLE_VALUES) {
      expect(ROLE_HINTS[role]).toBeTruthy();
    }
    expect(Object.keys(ROLE_HINTS).sort()).toEqual([...ADMIN_CREATOR_ROLE_VALUES].sort());
  });

  it('does not offer a role that cannot be isolated', () => {
    // The roles still exist on the wire and in the backend enum; they are not
    // OFFERED, so a founder cannot assemble a board the server will refuse.
    expect(isAdminCreatorRole('face_shape')).toBe(false);
    expect(isAdminCreatorRole('facial_hair')).toBe(false);
  });

  it('rejects anything it does not offer', () => {
    expect(isAdminCreatorRole('character_3')).toBe(false);
    expect(isAdminCreatorRole('')).toBe(false);
    // The legacy /images role is deliberately NOT offered here — see the
    // compatibility tests in draftStorage.test.ts.
    expect(isAdminCreatorRole('character_appearance')).toBe(false);
  });
});

describe('admin creator roles — /images vocabulary is untouched', () => {
  it('leaves the Image Generator picker exactly as it was', () => {
    // Adding a role to referenceKinds would put it in the /images picker. The
    // two vocabularies are separate precisely so this list cannot drift.
    expect(REFERENCE_ROLES).toEqual([
      'unspecified',
      'character_appearance',
      'clothing',
      'environment',
      'other',
    ]);
  });

  it('shares no identity-bucket or attribute role with /images', () => {
    for (const role of [
      'character_1',
      'character_2',
      'tattoo_mark',
      'pose_composition',
      ...FEATURE_ROLES,
    ]) {
      expect(REFERENCE_ROLES as readonly string[]).not.toContain(role);
    }
  });

  it('keeps character_appearance out of the Admin Creator selector', () => {
    expect(ADMIN_CREATOR_ROLE_VALUES as readonly string[]).not.toContain('character_appearance');
  });
});

describe('admin creator roles — the four-card combinations the founder asked for', () => {
  const COMBINATIONS = [
    ['character_1', 'character_1', 'environment', 'clothing'],
    ['character_1', 'character_2', 'environment', 'clothing'],
    ['character_1', 'character_2', 'character_2', 'environment'],
    ['character_1', 'clothing', 'tattoo_mark', 'pose_composition'],
    ['clothing', 'clothing', 'environment', 'environment'],
  ];

  it('accepts every one of them, duplicates included', () => {
    for (const combo of COMBINATIONS) {
      expect(combo.every(isAdminCreatorRole)).toBe(true);
    }
  });

  it('places no uniqueness constraint on roles', () => {
    // Two Character 1 cards are two views of one person, not an error.
    const duplicated = ['character_1', 'character_1', 'character_1', 'character_1'];
    expect(duplicated.every(isAdminCreatorRole)).toBe(true);
  });
});
