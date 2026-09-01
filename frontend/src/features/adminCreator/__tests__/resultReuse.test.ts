// Staging a generated result as the reference for the next pass.
//
// This is the staged-generation loop in one operation: a face that was just
// generated becomes Person A, and the next board refines it. It is built
// entirely from primitives that already exist — the result is a saved
// CharacterImage, so putting it on the board stages its ID exactly as picking
// it from the library would. No bytes are copied and no row is created.
//
// The rule that needed pinning is the one about a full board: there is no safe
// card to overwrite by default, so nothing may move until the founder names
// one.
import { describe, it, expect } from 'vitest';
import type { LibraryImage } from '@/lib/types';
import {
  character1ReuseTarget,
  emptySlots,
  fillSlot,
  firstEmptySlot,
  toSubmission,
} from '../referenceSlots';
import { derivePassIntent } from '../passIntent';

function img(id: number, kind = 'uploaded'): LibraryImage {
  return { id, url: `/static/${id}.png`, kind } as LibraryImage;
}

/** A generated Admin Creator result, as the job hands it back. */
const RESULT = img(2116, 'scene_only');

describe('result reuse — Use as Character 1', () => {
  it('fills the first empty card when no Character 1 exists yet', () => {
    let slots = emptySlots();
    slots = fillSlot(slots, 0, img(1), 'eyes');
    const target = character1ReuseTarget(slots);
    expect(target).toBe(1);
    slots = fillSlot(slots, target!, RESULT, 'character_1');
    expect(slots[1]).toEqual({ image: RESULT, role: 'character_1' });
    // The card that was already there is untouched.
    expect(slots[0]?.role).toBe('eyes');
  });

  it('REPLACES an existing Character 1 rather than adding a second', () => {
    // The 2026-08-22 contamination: appending made the board assert that the
    // original photograph and every generated result were all one person, so
    // "replace Person A's hair" no longer named a single starting image.
    let slots = emptySlots();
    slots = fillSlot(slots, 0, img(1), 'character_1');
    slots = fillSlot(slots, 1, img(2), 'hair');
    expect(character1ReuseTarget(slots)).toBe(0);

    slots = fillSlot(slots, character1ReuseTarget(slots)!, RESULT, 'character_1');
    expect(slots[0]).toEqual({ image: RESULT, role: 'character_1' });
    expect(slots[1]?.role).toBe('hair');
    expect(slots.filter((s) => s?.role === 'character_1')).toHaveLength(1);
  });

  it('replaces the Character 1 card wherever it sits', () => {
    let slots = emptySlots();
    slots = fillSlot(slots, 0, img(1), 'hair');
    slots = fillSlot(slots, 2, img(2), 'character_1');
    expect(character1ReuseTarget(slots)).toBe(2);
  });

  it('keeps the card count stable across an iterative refinement', () => {
    // Three passes, each reusing the result. The board must stay at two cards
    // — that stability IS the fix.
    let slots = emptySlots();
    slots = fillSlot(slots, 0, img(1), 'character_1'); // Grace
    slots = fillSlot(slots, 1, img(2), 'hair'); // donor

    for (const pass of [img(101, 'scene_only'), img(102, 'scene_only'), img(103, 'scene_only')]) {
      slots = fillSlot(slots, character1ReuseTarget(slots)!, pass, 'character_1');
      expect(slots.filter(Boolean)).toHaveLength(2);
      expect(slots.filter((s) => s?.role === 'character_1')).toHaveLength(1);
    }
    // The last result is the current Person A; the donor never moved.
    expect(slots[0]?.image.id).toBe(103);
    expect(slots[1]?.image.id).toBe(2);
    expect(toSubmission(slots).reference_roles).toEqual(['character_1', 'hair']);
  });

  it('never produces a board the server would refuse', () => {
    let slots = emptySlots();
    slots = fillSlot(slots, 0, img(1), 'character_1');
    slots = fillSlot(slots, 1, img(2), 'hair');
    for (let i = 0; i < 5; i += 1) {
      slots = fillSlot(slots, character1ReuseTarget(slots)!, img(200 + i, 'scene_only'), 'character_1');
    }
    // Mirrors manual_references::has_ambiguous_refinement_subject.
    const roles = toSubmission(slots).reference_roles;
    const c1 = roles.filter((r) => r === 'character_1').length;
    const hasFeature = roles.some((r) => r === 'hair');
    expect(hasFeature && c1 > 1).toBe(false);
  });

  it('returns null only when there is no Character 1 and no empty card', () => {
    let slots = emptySlots();
    for (let i = 0; i < 4; i += 1) slots = fillSlot(slots, i, img(i + 1), 'eyes');
    expect(character1ReuseTarget(slots)).toBeNull();
  });

  it('reports no target when every card is occupied and none is Character 1', () => {
    let slots = emptySlots();
    for (let i = 0; i < 4; i += 1) slots = fillSlot(slots, i, img(i + 1), 'eyes');
    // The page turns this null into an explicit "choose a card" prompt rather
    // than silently evicting a reference the founder chose.
    expect(firstEmptySlot(slots)).toBeNull();
    expect(character1ReuseTarget(slots)).toBeNull();
  });

  it('still has a target on a FULL board when one card is Character 1', () => {
    // Replacing the current Person A is never an eviction — it is the
    // iteration the founder asked for.
    let slots = emptySlots();
    for (let i = 0; i < 4; i += 1) slots = fillSlot(slots, i, img(i + 1), 'eyes');
    slots = fillSlot(slots, 3, img(9), 'character_1');
    expect(character1ReuseTarget(slots)).toBe(3);
  });

  it('replaces only the card the founder named', () => {
    let slots = emptySlots();
    for (let i = 0; i < 4; i += 1) slots = fillSlot(slots, i, img(i + 1), 'eyes');
    const next = fillSlot(slots, 2, RESULT, 'character_1');
    expect(next[2]).toEqual({ image: RESULT, role: 'character_1' });
    expect(next[0]?.image.id).toBe(1);
    expect(next[1]?.image.id).toBe(2);
    expect(next[3]?.image.id).toBe(4);
  });

  it('is a generated image, and generated images are legal references', () => {
    // scene_only is in REFERENCE_SELECTABLE_IMAGE_KINDS server-side, which is
    // what makes the whole loop possible without a new endpoint.
    let slots = fillSlot(emptySlots(), 0, RESULT, 'character_1');
    expect(toSubmission(slots).reference_image_ids).toEqual([2116]);
    expect(toSubmission(slots).reference_roles).toEqual(['character_1']);
  });
});

describe('result reuse — Send to card', () => {
  it('can stage the result without claiming an identity', () => {
    const slots = fillSlot(emptySlots(), 2, RESULT, 'unspecified');
    expect(slots[2]).toEqual({ image: RESULT, role: 'unspecified' });
  });

  it('moves rather than duplicates when re-sent to another card', () => {
    // resolve_manual_references refuses a repeated id outright, so a result
    // sitting in two cards would fail the whole submission.
    let slots = fillSlot(emptySlots(), 0, RESULT, 'character_1');
    slots = fillSlot(slots, 2, RESULT, 'character_1');
    expect(slots[0]).toBeNull();
    expect(slots[2]?.image.id).toBe(2116);
    expect(toSubmission(slots).reference_image_ids).toEqual([2116]);
  });
});

describe('result reuse — the staged workflow it exists for', () => {
  it('turns a build pass into a refinement pass', () => {
    // Pass 1: four features, no identity yet.
    let pass1 = emptySlots();
    (['eyes', 'nose', 'mouth_lips', 'skin_complexion'] as const).forEach((role, i) => {
      pass1 = fillSlot(pass1, i, img(200 + i), role);
    });
    expect(derivePassIntent(pass1).kind).toBe('build');

    // Pass 2: the generated face becomes Person A, plus hair and eyebrows.
    let pass2 = emptySlots();
    pass2 = fillSlot(pass2, 0, RESULT, 'character_1');
    pass2 = fillSlot(pass2, 1, img(301), 'hair');
    pass2 = fillSlot(pass2, 2, img(302), 'eyebrows');
    expect(derivePassIntent(pass2).kind).toBe('refine');

    // Pass 3: the approved face plus a pose — a canon-card pass.
    let pass3 = emptySlots();
    pass3 = fillSlot(pass3, 0, RESULT, 'character_1');
    pass3 = fillSlot(pass3, 1, img(400), 'pose_composition');
    expect(derivePassIntent(pass3).kind).toBe('pose');
  });
});
