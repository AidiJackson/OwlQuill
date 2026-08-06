import { describe, it, expect } from 'vitest';
import { TYPES, KINDS } from '../PostBadges';

/**
 * The post-header badge family, pinned as data.
 *
 * These chips sit on one row with the provenance badge, so they are one
 * family: same geometry class, same rule for unknown values, and a
 * plain-language expansion for every abbreviation. The tables come from the
 * component itself — asserting against a copy of them would pass happily while
 * the two drifted apart, which is the failure this file exists to prevent.
 */
const typeBadge = (v?: string | null) => (v ? TYPES[v] : undefined) ?? null;
const kindBadge = (v?: string | null) => (v ? KINDS[v] : undefined) ?? null;

describe('post type badges', () => {
  it('labels the three writing modes', () => {
    expect(typeBadge('ic')?.label).toBe('IC');
    expect(typeBadge('ooc')?.label).toBe('OOC');
    expect(typeBadge('narration')?.label).toBe('Narration');
  });

  it('expands every abbreviation in plain language', () => {
    // "IC" is jargon a new reader cannot expand and a screen reader spells out.
    for (const key of Object.keys(TYPES)) {
      expect(TYPES[key].full.length).toBeGreaterThan(TYPES[key].label.length - 1);
      expect(TYPES[key].full).not.toMatch(/^(IC|OOC)$/);
    }
  });

  it('renders nothing for an unknown or absent type', () => {
    // Previously an unrecognised content_type silently fell back to "IC",
    // labelling out-of-character text as in-character.
    expect(typeBadge('some_future_mode')).toBeNull();
    expect(typeBadge(undefined)).toBeNull();
    expect(typeBadge(null)).toBeNull();
  });
});

describe('post kind badges', () => {
  it('labels the two special post kinds', () => {
    expect(kindBadge('open_starter')?.label).toBe('Open Starter');
    expect(kindBadge('finished_piece')?.label).toBe('Finished Piece');
  });

  it('says nothing about an ordinary post', () => {
    // A badge on every post is a badge on none.
    expect(kindBadge('general')).toBeNull();
  });

  it('renders nothing for an unknown kind', () => {
    expect(kindBadge('anthology')).toBeNull();
  });
});

describe('badge geometry', () => {
  it('puts every badge on the one shared geometry class', () => {
    // Height, padding and radius live in `.badge` so a chip is exactly as tall
    // as its neighbour whatever it contains. Colour is the only per-badge part.
    for (const badge of [...Object.values(TYPES), ...Object.values(KINDS)]) {
      expect(badge.className).toMatch(/^badge-/);
      expect(badge.className.split(' ')).toHaveLength(1);
    }
  });
});
