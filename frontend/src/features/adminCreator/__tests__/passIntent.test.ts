// What the board says it is about to do.
//
// The banner is the whole reason Phase 2 needs no mode selector: the roles
// already determine the pass, so the page reads them back instead of asking the
// founder to declare an intent that could contradict the cards.
//
// These cases mirror backend test_admin_creator_feature_roles.py exactly. If
// the two derivations disagree, the banner promises one thing and the provider
// is told another — which is worse than having no banner at all.
import { describe, it, expect } from 'vitest';
import type { LibraryImage } from '@/lib/types';
import { derivePassIntent } from '../passIntent';
import { emptySlots, fillSlot } from '../referenceSlots';
import type { AdminCreatorRole } from '../referenceRoles';
import type { ReferenceSlots } from '../referenceSlots';

function img(id: number): LibraryImage {
  return { id, url: `/static/${id}.png`, kind: 'uploaded' } as LibraryImage;
}

/** A board built from roles in card order. */
function boardOf(...roles: AdminCreatorRole[]): ReferenceSlots {
  let slots = emptySlots();
  roles.forEach((role, i) => {
    slots = fillSlot(slots, i, img(100 + i), role);
  });
  return slots;
}

describe('pass intent — the four workflows', () => {
  it('says nothing about an empty board', () => {
    expect(derivePassIntent(emptySlots()).kind).toBe('empty');
  });

  it('reads features without Person A as building a new face', () => {
    const intent = derivePassIntent(boardOf('eyes', 'nose', 'mouth_lips', 'skin_complexion'));
    expect(intent.kind).toBe('build');
    expect(intent.headline).toBe('Building a new face');
    expect(intent.detail).toContain('one new person');
  });

  it('reads Person A plus features as a refinement', () => {
    const intent = derivePassIntent(boardOf('character_1', 'hair', 'eyebrows'));
    expect(intent.kind).toBe('refine');
    expect(intent.headline).toBe('Refining Person A');
    expect(intent.detail).toContain('hair and eyebrows');
    expect(intent.detail).toContain('face and likeness stay the same');
  });

  it('reads Person A plus a pose as a canon-card pass', () => {
    const intent = derivePassIntent(boardOf('character_1', 'pose_composition'));
    expect(intent.kind).toBe('pose');
    expect(intent.headline).toBe('Posing Person A');
  });

  it('reads both identity buckets as a two-person scene', () => {
    const intent = derivePassIntent(boardOf('character_1', 'character_2', 'environment'));
    expect(intent.kind).toBe('two_person');
    expect(intent.detail).toContain('separate identities');
  });

  it('falls back to a plain scene when nothing else applies', () => {
    expect(derivePassIntent(boardOf('clothing', 'environment')).kind).toBe('scene');
    expect(derivePassIntent(boardOf('unspecified')).kind).toBe('scene');
  });
});

describe('pass intent — agrees with the backend derivation', () => {
  it('does not let Character 2 trigger refinement', () => {
    // Person B is a second person in a scene, not the subject being built.
    // manual_references::_construction_lines takes the same position.
    expect(derivePassIntent(boardOf('character_2', 'eyes')).kind).toBe('build');
  });

  it('lets features win over a two-person board', () => {
    // Backend emits the refinement clause here, so the banner must not claim
    // this is an ordinary two-person scene.
    expect(derivePassIntent(boardOf('character_1', 'character_2', 'hair')).kind).toBe('refine');
  });

  it('treats a single feature as a build, with no minimum card count', () => {
    expect(derivePassIntent(boardOf('hair')).kind).toBe('build');
  });

  it('needs no feature to describe the pre-Phase-2 workflows', () => {
    // The boards that existed before attribute roles still get a sensible
    // banner rather than falling into 'build'.
    expect(derivePassIntent(boardOf('character_1', 'clothing')).kind).toBe('scene');
    expect(derivePassIntent(boardOf('character_1', 'tattoo_mark')).kind).toBe('scene');
  });
});

describe('pass intent — which boards may omit the prompt', () => {
  // Mirrors manual_references::board_is_self_describing. The server decides
  // this independently; if the two disagree the founder is offered a Generate
  // button that 422s, or is blocked from a generation the server would accept.
  const selfDescribing = (slots: ReferenceSlots) =>
    ['build', 'refine', 'pose'].includes(derivePassIntent(slots).kind);

  it('allows an empty prompt for the three self-describing passes', () => {
    expect(selfDescribing(boardOf('character_1', 'hair'))).toBe(true);
    expect(selfDescribing(boardOf('eyes', 'nose'))).toBe(true);
    expect(selfDescribing(boardOf('character_1', 'pose_composition'))).toBe(true);
  });

  it('requires a prompt for boards that state no operation', () => {
    expect(selfDescribing(boardOf('character_1', 'character_2'))).toBe(false);
    expect(selfDescribing(boardOf('clothing', 'environment'))).toBe(false);
    expect(selfDescribing(boardOf('unspecified', 'unspecified'))).toBe(false);
    expect(selfDescribing(boardOf('character_1', 'clothing'))).toBe(false);
  });

  it('requires a prompt for an empty board', () => {
    expect(selfDescribing(emptySlots())).toBe(false);
  });
});

describe('pass intent — reads roles, not board size', () => {
  it('dedupes repeated features rather than repeating the label', () => {
    const intent = derivePassIntent(boardOf('character_1', 'hair', 'hair'));
    expect(intent.detail).toContain('hair');
    expect(intent.detail).not.toContain('hair and hair');
  });

  it('is unaffected by which card a role sits in', () => {
    const front = derivePassIntent(boardOf('character_1', 'eyes'));
    let back = emptySlots();
    back = fillSlot(back, 3, img(1), 'character_1');
    back = fillSlot(back, 1, img(2), 'eyes');
    expect(derivePassIntent(back).kind).toBe(front.kind);
  });

  it('handles gaps between populated cards', () => {
    let slots = emptySlots();
    slots = fillSlot(slots, 0, img(1), 'character_1');
    slots = fillSlot(slots, 3, img(2), 'hair');
    expect(derivePassIntent(slots).kind).toBe('refine');
  });
});
