import { describe, it, expect } from 'vitest';
import type { LibraryImage } from '@/lib/types';
import { MAX_REFERENCES } from '@/features/images/referenceKinds';
import {
  ADMIN_CREATOR_REFERENCE_MODE,
  clearSlot,
  emptySlots,
  fillSlot,
  filledCount,
  firstEmptySlot,
  normalizeSlots,
  removeImage,
  setSlotRole,
  slotSource,
  toSubmission,
  usedImageIds,
} from '../referenceSlots';

/** Minimal LibraryImage stand-in — only the fields the slot rules read. */
function img(id: number, kind = 'generated'): LibraryImage {
  return { id, kind, url: `https://example.test/${id}.png` } as unknown as LibraryImage;
}

describe('reference slots — shape', () => {
  it('always holds exactly four cards', () => {
    expect(emptySlots()).toHaveLength(MAX_REFERENCES);
    expect(emptySlots().every((s) => s === null)).toBe(true);
  });

  it('normalises a short or long array back to four cards', () => {
    // Guards the boundary where slots arrive from outside the module: no render
    // can index past the end, and no card is silently lost.
    expect(normalizeSlots([])).toHaveLength(MAX_REFERENCES);
    expect(normalizeSlots([null, null, null, null, null, null])).toHaveLength(MAX_REFERENCES);
  });
});

describe('reference slots — independence', () => {
  it('fills one card without touching the others', () => {
    const next = fillSlot(emptySlots(), 2, img(10));
    expect(next[0]).toBeNull();
    expect(next[1]).toBeNull();
    expect(next[2]?.image.id).toBe(10);
    expect(next[3]).toBeNull();
  });

  it('allows any mix of library images and uploads across the four cards', () => {
    let s = emptySlots();
    s = fillSlot(s, 0, img(1, 'generated'));
    s = fillSlot(s, 1, img(2, 'uploaded'));
    s = fillSlot(s, 2, img(3, 'cover'));
    s = fillSlot(s, 3, img(4, 'uploaded'));
    expect(s.map((x) => x && slotSource(x))).toEqual(['library', 'upload', 'library', 'upload']);
  });

  it('leaves gaps rather than shifting cards up when one is cleared', () => {
    // Card order is priority order: the server drops overflow from the tail of
    // the manual block, so a card must never silently change position.
    let s = emptySlots();
    s = fillSlot(s, 0, img(1));
    s = fillSlot(s, 1, img(2));
    s = fillSlot(s, 2, img(3));
    s = clearSlot(s, 1);
    expect(s[0]?.image.id).toBe(1);
    expect(s[1]).toBeNull();
    expect(s[2]?.image.id).toBe(3);
  });

  it('ignores an out-of-range index instead of growing the board', () => {
    expect(fillSlot(emptySlots(), 4, img(1))).toHaveLength(MAX_REFERENCES);
    expect(filledCount(fillSlot(emptySlots(), 4, img(1)))).toBe(0);
    expect(filledCount(fillSlot(emptySlots(), -1, img(1)))).toBe(0);
  });
});

describe('reference slots — no duplicate ids', () => {
  it('MOVES an image rather than letting it occupy two cards', () => {
    // resolve_manual_references refuses duplicate ids outright rather than
    // deduping them, so a duplicate would fail the WHOLE submission and take
    // the other references down with it.
    let s = fillSlot(emptySlots(), 0, img(7));
    s = fillSlot(s, 3, img(7));
    expect(s[0]).toBeNull();
    expect(s[3]?.image.id).toBe(7);
    expect(filledCount(s)).toBe(1);
  });

  it('never emits a repeated id in a submission', () => {
    let s = emptySlots();
    s = fillSlot(s, 0, img(5));
    s = fillSlot(s, 1, img(6));
    s = fillSlot(s, 2, img(5)); // same image again
    const { reference_image_ids } = toSubmission(s);
    expect(new Set(reference_image_ids).size).toBe(reference_image_ids.length);
  });
});

describe('reference slots — roles', () => {
  it('defaults a new reference to unspecified', () => {
    expect(fillSlot(emptySlots(), 0, img(1))[0]?.role).toBe('unspecified');
  });

  it('sets a role on one card only', () => {
    let s = fillSlot(emptySlots(), 0, img(1));
    s = fillSlot(s, 1, img(2));
    s = setSlotRole(s, 1, 'clothing');
    expect(s[0]?.role).toBe('unspecified');
    expect(s[1]?.role).toBe('clothing');
  });

  it('keeps the role when the picture behind it is replaced', () => {
    // Swapping the image under "Clothing" is a replace, not a reset.
    let s = fillSlot(emptySlots(), 0, img(1));
    s = setSlotRole(s, 0, 'environment');
    s = fillSlot(s, 0, img(9));
    expect(s[0]?.image.id).toBe(9);
    expect(s[0]?.role).toBe('environment');
  });

  it('does nothing when a role is set on an empty card', () => {
    expect(setSlotRole(emptySlots(), 2, 'clothing')[2]).toBeNull();
  });
});

describe('reference slots — submission transport', () => {
  it('sends nothing when no card is filled', () => {
    expect(toSubmission(emptySlots())).toEqual({
      reference_image_ids: [],
      reference_roles: [],
      reference_mode: 'deliberate',
    });
  });

  it('skips empty cards and preserves board order', () => {
    let s = emptySlots();
    s = fillSlot(s, 1, img(20), 'clothing');
    s = fillSlot(s, 3, img(40), 'environment');
    expect(toSubmission(s)).toEqual({
      reference_image_ids: [20, 40],
      reference_roles: ['clothing', 'environment'],
      reference_mode: 'deliberate',
    });
  });

  it('always asks for deliberate mode, empty board included', () => {
    // The mode is a property of THIS workflow, not of a particular selection:
    // an Admin Creator submission can never silently fall back to the
    // Image Generator's canon-first budgeting.
    expect(toSubmission(emptySlots()).reference_mode).toBe(ADMIN_CREATOR_REFERENCE_MODE);
    let s = emptySlots();
    for (let i = 0; i < MAX_REFERENCES; i += 1) s = fillSlot(s, i, img(i + 1));
    expect(toSubmission(s).reference_mode).toBe('deliberate');
  });

  it('pairs ids and roles positionally for a mixed board', () => {
    let s = emptySlots();
    s = fillSlot(s, 0, img(1, 'generated'), 'character_1');
    s = fillSlot(s, 1, img(2, 'uploaded'), 'clothing');
    s = fillSlot(s, 2, img(3, 'generated'), 'environment');
    s = fillSlot(s, 3, img(4, 'uploaded'), 'other');
    const { reference_image_ids, reference_roles } = toSubmission(s);
    expect(reference_image_ids).toEqual([1, 2, 3, 4]);
    expect(reference_roles).toEqual(['character_1', 'clothing', 'environment', 'other']);
    expect(reference_image_ids).toHaveLength(reference_roles.length);
  });

  it('never exceeds the server cap', () => {
    let s = emptySlots();
    for (let i = 0; i < MAX_REFERENCES; i += 1) s = fillSlot(s, i, img(i + 1));
    expect(toSubmission(s).reference_image_ids.length).toBeLessThanOrEqual(MAX_REFERENCES);
  });
});

describe('reference slots — helpers', () => {
  it('reports the first empty card, then null when full', () => {
    let s = emptySlots();
    expect(firstEmptySlot(s)).toBe(0);
    s = fillSlot(s, 0, img(1));
    expect(firstEmptySlot(s)).toBe(1);
    for (let i = 1; i < MAX_REFERENCES; i += 1) s = fillSlot(s, i, img(i + 1));
    expect(firstEmptySlot(s)).toBeNull();
  });

  it('collects staged ids for the library modal', () => {
    let s = fillSlot(emptySlots(), 0, img(3));
    s = fillSlot(s, 2, img(8));
    expect(usedImageIds(s)).toEqual(new Set([3, 8]));
  });

  it('unstages a deleted upload from wherever it sat', () => {
    // A deleted image left staged would be refused at submission, and the
    // founder would have no way to see why.
    let s = fillSlot(emptySlots(), 1, img(11, 'uploaded'));
    s = fillSlot(s, 2, img(12));
    s = removeImage(s, 11);
    expect(s[1]).toBeNull();
    expect(s[2]?.image.id).toBe(12);
  });

  it('reads the source badge from the image kind', () => {
    expect(slotSource({ image: img(1, 'uploaded'), role: 'unspecified' })).toBe('upload');
    for (const kind of ['generated', 'scene_only', 'cover']) {
      expect(slotSource({ image: img(1, kind), role: 'unspecified' })).toBe('library');
    }
  });
});
