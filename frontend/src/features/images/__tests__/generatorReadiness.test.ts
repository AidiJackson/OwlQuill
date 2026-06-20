import { describe, it, expect } from 'vitest';
import { computeGeneratorGuards, parseHasIdentityAnchor } from '../generatorReadiness';

const legacyAnchor = JSON.stringify({ anchors: { front: { url: 'https://x/a.png' } } });

describe('parseHasIdentityAnchor', () => {
  it('returns undefined when JSON is absent', () => {
    expect(parseHasIdentityAnchor(null)).toBeUndefined();
    expect(parseHasIdentityAnchor(undefined)).toBeUndefined();
  });

  it('returns true when anchors.front.url is present', () => {
    expect(parseHasIdentityAnchor(legacyAnchor)).toBe(true);
  });

  it('returns false when the front url is missing or JSON is malformed', () => {
    expect(parseHasIdentityAnchor(JSON.stringify({ anchors: { front: {} } }))).toBe(false);
    expect(parseHasIdentityAnchor('{not json')).toBe(false);
  });
});

describe('computeGeneratorGuards', () => {
  it('no character selected → no guards active', () => {
    expect(computeGeneratorGuards(null, null)).toEqual({
      lockedGuardActive: false,
      anchorGuardActive: false,
    });
  });

  it('incomplete draft (not locked) → locked guard blocks', () => {
    expect(
      computeGeneratorGuards(7, { visual_locked: false, identity_anchor_json: null }),
    ).toEqual({ lockedGuardActive: true, anchorGuardActive: false });
  });

  it('legacy locked character with valid anchor → ready', () => {
    expect(
      computeGeneratorGuards(7, { visual_locked: true, identity_anchor_json: legacyAnchor }),
    ).toEqual({ lockedGuardActive: false, anchorGuardActive: false });
  });

  it('legacy locked character with missing anchor and no canon → anchor guard blocks', () => {
    expect(
      computeGeneratorGuards(7, {
        visual_locked: true,
        has_identity_canon: false,
        identity_anchor_json: JSON.stringify({ anchors: { front: {} } }),
      }),
    ).toEqual({ lockedGuardActive: false, anchorGuardActive: true });
  });

  it('v2 canon character (locked + has_identity_canon, no legacy anchor) → ready (Bertie id=62)', () => {
    expect(
      computeGeneratorGuards(62, {
        visual_locked: true,
        has_identity_canon: true,
        identity_anchor_json: null,
      }),
    ).toEqual({ lockedGuardActive: false, anchorGuardActive: false });
  });

  it('v2 canon character whose stale anchor JSON lacks front.url → still ready', () => {
    expect(
      computeGeneratorGuards(62, {
        visual_locked: true,
        has_identity_canon: true,
        identity_anchor_json: JSON.stringify({ anchors: { front: {} } }),
      }),
    ).toEqual({ lockedGuardActive: false, anchorGuardActive: false });
  });
});
