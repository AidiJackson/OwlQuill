import { describe, it, expect } from 'vitest';
import { computeGeneratorGuards } from '../generatorReadiness';

/**
 * The frontend readiness guard mirrors the ordinary generation path's server
 * rule (Polish Phase 5.8): ``/image-generator/generate`` with a character
 * requires a canon with content and consults no legacy identity source
 * (backend/tests/test_image_generator.py::test_include_character_without_canon_returns_409,
 * ::test_include_character_empty_canon_returns_409). ``has_identity_canon``
 * is the server's signal that the canon holds a generated face — so the
 * frontend offers generation only for visual_locked && has_identity_canon,
 * and a legacy anchor is no longer a substitute the backend does not honour.
 */
const READY = { lockedGuardActive: false, anchorGuardActive: false };

describe('computeGeneratorGuards', () => {
  it('no character selected → no guards active', () => {
    expect(computeGeneratorGuards(null, null)).toEqual(READY);
  });

  it('A/B/C/D: not established (visual_locked false) → locked guard blocks, whatever else exists', () => {
    for (const has_identity_canon of [false, true]) {
      expect(
        computeGeneratorGuards(7, { visual_locked: false, has_identity_canon }),
      ).toEqual({ lockedGuardActive: true, anchorGuardActive: false });
    }
  });

  it('E: established v2 character (locked + has_identity_canon) → ready', () => {
    expect(
      computeGeneratorGuards(62, { visual_locked: true, has_identity_canon: true }),
    ).toEqual(READY);
  });

  it('F: legacy locked character with no v2 canon → blocked, even with a legacy anchor', () => {
    // The backend would answer 409 "Character canon incomplete"; the anchor
    // is not consulted on this route, so it must not unlock the button.
    expect(
      computeGeneratorGuards(7, {
        visual_locked: true,
        has_identity_canon: false,
        identity_anchor_json: JSON.stringify({ anchors: { front: { url: 'https://x/a.png' } } }),
      } as Parameters<typeof computeGeneratorGuards>[1]),
    ).toEqual({ lockedGuardActive: false, anchorGuardActive: true });
    expect(
      computeGeneratorGuards(7, { visual_locked: true, has_identity_canon: false }),
    ).toEqual({ lockedGuardActive: false, anchorGuardActive: true });
  });

  it('G: bridged legacy character (locked + has_identity_canon, body not locked) → ready', () => {
    // has_identity_canon means face_front is in the canon, which satisfies
    // has_any_canon_content on the server.
    expect(
      computeGeneratorGuards(7, { visual_locked: true, has_identity_canon: true }),
    ).toEqual(READY);
  });

  it('a payload that predates has_identity_canon is treated as no canon', () => {
    expect(
      computeGeneratorGuards(7, { visual_locked: true } as Parameters<typeof computeGeneratorGuards>[1]),
    ).toEqual({ lockedGuardActive: false, anchorGuardActive: true });
  });
});
