// Recovery rules for the Admin Creator draft and its submitted job.
//
// These exist because of a real, expensive failure: on 2026-08-22 two OpenAI
// generations completed and were paid for while the tab was away, and the
// founder came back to an empty board with no route to either image. Every
// assertion below is one half of "a lost page costs nothing".
import { describe, it, expect, beforeEach } from 'vitest';
import type { LibraryImage } from '@/lib/types';
import { MAX_REFERENCES } from '@/features/images/referenceKinds';
import { emptySlots, fillSlot, clearSlot, toSubmission } from '../referenceSlots';
import {
  clearDraft,
  clearJobPointer,
  loadDraft,
  loadJobPointer,
  providerForDraft,
  saveDraft,
  saveJobPointer,
  type DraftStore,
} from '../draftStorage';

/** In-memory stand-in for sessionStorage. */
class MemoryStore implements DraftStore {
  map = new Map<string, string>();
  getItem(k: string) {
    return this.map.has(k) ? (this.map.get(k) as string) : null;
  }
  setItem(k: string, v: string) {
    this.map.set(k, v);
  }
  removeItem(k: string) {
    this.map.delete(k);
  }
}

/** A store that throws on every access, like a webview with site data blocked. */
const hostileStore: DraftStore = {
  getItem() {
    throw new Error('blocked');
  },
  setItem() {
    throw new Error('blocked');
  },
  removeItem() {
    throw new Error('blocked');
  },
};

function img(id: number, kind = 'uploaded'): LibraryImage {
  return { id, kind, url: `https://cdn.test/${id}.png` } as unknown as LibraryImage;
}

let store: MemoryStore;
beforeEach(() => {
  store = new MemoryStore();
});

describe('admin creator draft — round trip', () => {
  it('brings four cards and their roles back exactly', () => {
    let s = emptySlots();
    s = fillSlot(s, 0, img(11), 'character_1');
    s = fillSlot(s, 1, img(22), 'clothing');
    s = fillSlot(s, 2, img(33), 'environment');
    s = fillSlot(s, 3, img(44), 'other');

    saveDraft(store, 38, { slots: s, prompt: 'in a doorway', providerOption: 'option1' });
    const back = loadDraft(store, 38);

    expect(back).not.toBeNull();
    expect(back!.slots).toHaveLength(MAX_REFERENCES);
    // What actually matters is that the SUBMISSION is identical — the ids and
    // roles in card order are what the server acts on.
    expect(toSubmission(back!.slots)).toEqual(toSubmission(s));
    expect(toSubmission(back!.slots).reference_image_ids).toEqual([11, 22, 33, 44]);
  });

  it('brings the prompt and provider back', () => {
    saveDraft(store, 38, { slots: emptySlots(), prompt: 'a scene', providerOption: 'option1' });
    const back = loadDraft(store, 38);
    expect(back!.prompt).toBe('a scene');
    expect(back!.providerOption).toBe('option1');
  });

  it('preserves empty cards and their positions', () => {
    // Card order is priority order all the way to the provider, so a gap must
    // come back as a gap rather than shifting the cards after it forward.
    let s = emptySlots();
    s = fillSlot(s, 1, img(20), 'clothing');
    s = fillSlot(s, 3, img(40), 'environment');
    saveDraft(store, 38, { slots: s, prompt: 'x', providerOption: 'option2' });

    const back = loadDraft(store, 38)!;
    expect(back.slots[0]).toBeNull();
    expect(back.slots[2]).toBeNull();
    expect(back.slots[1]?.image.id).toBe(20);
    expect(back.slots[3]?.image.id).toBe(40);
  });

  it('stores no image bytes — only ids and display fields', () => {
    let s = emptySlots();
    s = fillSlot(s, 0, { ...img(11), metadata_json: { huge: 'x'.repeat(500) } } as LibraryImage);
    saveDraft(store, 38, { slots: s, prompt: '', providerOption: 'option2' });

    const raw = store.getItem('ficshon.adminCreator.draft.v1.38')!;
    expect(raw).not.toContain('xxxxxxxxxx');
    expect(raw).not.toMatch(/data:image/);
    expect(JSON.parse(raw).slots[0].image).toEqual({
      id: 11,
      url: 'https://cdn.test/11.png',
      kind: 'uploaded',
    });
  });

  it('reflects a cleared card', () => {
    let s = fillSlot(emptySlots(), 0, img(11));
    saveDraft(store, 38, { slots: s, prompt: '', providerOption: 'option2' });
    s = clearSlot(s, 0);
    saveDraft(store, 38, { slots: s, prompt: 'still here', providerOption: 'option2' });

    expect(loadDraft(store, 38)!.slots[0]).toBeNull();
  });

  it('reflects a replaced card', () => {
    let s = fillSlot(emptySlots(), 0, img(11), 'clothing');
    saveDraft(store, 38, { slots: s, prompt: '', providerOption: 'option2' });
    s = fillSlot(s, 0, img(99));
    saveDraft(store, 38, { slots: s, prompt: '', providerOption: 'option2' });

    const back = loadDraft(store, 38)!;
    expect(back.slots[0]?.image.id).toBe(99);
    expect(back.slots[0]?.role).toBe('clothing'); // replace keeps the role
  });
});

describe('admin creator draft — character scoping', () => {
  it('never leaks one character board onto another', () => {
    const davies = fillSlot(emptySlots(), 0, img(11));
    saveDraft(store, 38, { slots: davies, prompt: 'davies', providerOption: 'option1' });

    expect(loadDraft(store, 58)).toBeNull();

    const shadow = fillSlot(emptySlots(), 0, img(77));
    saveDraft(store, 58, { slots: shadow, prompt: 'shadow', providerOption: 'option2' });

    expect(loadDraft(store, 38)!.prompt).toBe('davies');
    expect(toSubmission(loadDraft(store, 38)!.slots).reference_image_ids).toEqual([11]);
    expect(loadDraft(store, 58)!.prompt).toBe('shadow');
    expect(toSubmission(loadDraft(store, 58)!.slots).reference_image_ids).toEqual([77]);
  });

  it('clears one character without touching another', () => {
    saveDraft(store, 38, { slots: emptySlots(), prompt: 'davies', providerOption: 'option2' });
    saveDraft(store, 58, { slots: emptySlots(), prompt: 'shadow', providerOption: 'option2' });
    clearDraft(store, 38);
    expect(loadDraft(store, 38)).toBeNull();
    expect(loadDraft(store, 58)!.prompt).toBe('shadow');
  });
});

describe('admin creator draft — provider is character-scoped', () => {
  // The page's own values, mirrored here so these tests describe the real rule
  // rather than an invented one.
  const PROVIDERS = ['option2', 'option1'];
  const DEFAULT_PROVIDER = 'option2';
  const isSupported = (v: string) => PROVIDERS.includes(v);

  /** What the page does on mount and on every character change. */
  function providerFor(characterId: number): string {
    return providerForDraft(loadDraft(store, characterId), isSupported, DEFAULT_PROVIDER);
  }

  it("restores character A's saved OpenAI choice", () => {
    saveDraft(store, 38, { slots: emptySlots(), prompt: 'davies', providerOption: 'option1' });
    expect(providerFor(38)).toBe('option1');
  });

  it('gives a character with no draft the default, not the previous choice', () => {
    saveDraft(store, 38, { slots: emptySlots(), prompt: 'davies', providerOption: 'option1' });
    expect(providerFor(58)).toBe('option2');
  });

  it('does not let character B acquire OpenAI just because A had it selected', () => {
    // A picks OpenAI; the founder switches to B and types a prompt, which
    // persists B's draft. B's stored provider must be the default.
    saveDraft(store, 38, { slots: emptySlots(), prompt: 'davies', providerOption: 'option1' });
    const bProvider = providerFor(58);
    saveDraft(store, 58, { slots: emptySlots(), prompt: 'shadow', providerOption: bProvider });

    expect(loadDraft(store, 58)!.providerOption).toBe('option2');
    expect(loadDraft(store, 58)!.providerOption).not.toBe('option1');
  });

  it("switching back restores A's own OpenAI choice", () => {
    saveDraft(store, 38, { slots: emptySlots(), prompt: 'davies', providerOption: 'option1' });
    saveDraft(store, 58, { slots: emptySlots(), prompt: 'shadow', providerOption: 'option2' });

    expect(providerFor(58)).toBe('option2');
    expect(providerFor(38)).toBe('option1');
    expect(loadDraft(store, 38)!.providerOption).toBe('option1');
  });

  it('falls back to the default for a provider the page no longer offers', () => {
    // A retired option must not be re-selected from an old draft; the server
    // would gate it anyway and the button would render as nothing selected.
    saveDraft(store, 38, { slots: emptySlots(), prompt: 'p', providerOption: 'option5' });
    expect(providerFor(38)).toBe('option2');
  });

  it('falls back to the default when there is no draft at all', () => {
    expect(providerForDraft(null, isSupported, DEFAULT_PROVIDER)).toBe('option2');
  });
});

describe('admin creator job pointer — exact job identity', () => {
  it('survives so the exact submitted job can be asked about by id', () => {
    saveJobPointer(store, { characterId: 38, jobId: '53ce621059dc44efbdf9f8b35862d8d1' });
    expect(loadJobPointer(store, 38)).toEqual({
      characterId: 38,
      jobId: '53ce621059dc44efbdf9f8b35862d8d1',
    });
  });

  it('is not offered to a different character', () => {
    // Recovery must never adopt a generation belonging to another board.
    saveJobPointer(store, { characterId: 38, jobId: 'abc123' });
    expect(loadJobPointer(store, 58)).toBeNull();
  });

  it('is replaced by the next submission', () => {
    saveJobPointer(store, { characterId: 38, jobId: 'first' });
    saveJobPointer(store, { characterId: 38, jobId: 'second' });
    expect(loadJobPointer(store, 38)!.jobId).toBe('second');
  });

  it('is gone once the result is dismissed', () => {
    saveJobPointer(store, { characterId: 38, jobId: 'abc123' });
    clearJobPointer(store);
    expect(loadJobPointer(store, 38)).toBeNull();
  });
});

describe('admin creator recovery — failing safely', () => {
  it('returns null for a missing draft or pointer', () => {
    expect(loadDraft(store, 38)).toBeNull();
    expect(loadJobPointer(store, 38)).toBeNull();
  });

  it('survives malformed JSON', () => {
    store.setItem('ficshon.adminCreator.draft.v1.38', '{not json');
    store.setItem('ficshon.adminCreator.job.v1', 'nonsense');
    expect(loadDraft(store, 38)).toBeNull();
    expect(loadJobPointer(store, 38)).toBeNull();
  });

  it('survives a valid-JSON payload of the wrong shape', () => {
    store.setItem('ficshon.adminCreator.draft.v1.38', '[1,2,3]');
    store.setItem('ficshon.adminCreator.job.v1', '"a string"');
    expect(loadDraft(store, 38)).toBeNull();
    expect(loadJobPointer(store, 38)).toBeNull();
  });

  it('drops individual cards it cannot trust, keeping the rest', () => {
    // A card without a usable id would be submitted to the server and rejected,
    // taking the whole board with it. An empty slot is visible and fixable.
    store.setItem(
      'ficshon.adminCreator.draft.v1.38',
      JSON.stringify({
        slots: [
          { image: { id: 'not-a-number', url: 'u' }, role: 'clothing' },
          { image: { id: 22, url: 'https://cdn.test/22.png', kind: 'uploaded' }, role: 'clothing' },
          { role: 'clothing' },
          null,
        ],
        prompt: 'kept',
        providerOption: 'option2',
      }),
    );
    const back = loadDraft(store, 38)!;
    expect(back.prompt).toBe('kept');
    expect(toSubmission(back.slots).reference_image_ids).toEqual([22]);
  });

  it('falls back to a safe role for an unknown one', () => {
    store.setItem(
      'ficshon.adminCreator.draft.v1.38',
      JSON.stringify({
        slots: [{ image: { id: 5, url: 'u', kind: 'uploaded' }, role: 'wildly_invalid' }],
        prompt: '',
        providerOption: 'option2',
      }),
    );
    expect(loadDraft(store, 38)!.slots[0]?.role).toBe('unspecified');
  });

  it('DOWNGRADES a legacy character_appearance card rather than promoting it', () => {
    // The compatibility decision, pinned. character_appearance is supporting
    // likeness evidence with no grouping claim; character_1 asserts "this is
    // Person A and every other Person A card is the same individual". Remapping
    // one to the other would start sending a stronger claim to the provider
    // that the founder never made. Unspecified is visible, harmless, and one
    // click from being re-picked correctly.
    store.setItem(
      'ficshon.adminCreator.draft.v1.38',
      JSON.stringify({
        slots: [
          { image: { id: 5, url: 'u', kind: 'uploaded' }, role: 'character_appearance' },
          { image: { id: 6, url: 'u', kind: 'uploaded' }, role: 'clothing' },
        ],
        prompt: 'legacy board',
        providerOption: 'option2',
      }),
    );
    const back = loadDraft(store, 38)!;
    expect(back.slots[0]?.role).toBe('unspecified');
    expect(back.slots[0]?.role).not.toBe('character_1');
    // The card itself and every still-valid role survive — only the retired
    // role is downgraded.
    expect(back.slots[0]?.image.id).toBe(5);
    expect(back.slots[1]?.role).toBe('clothing');
    expect(back.prompt).toBe('legacy board');
  });

  it('round-trips the attribute roles a Character Build pass uses', () => {
    // Phase 2 added eight roles to the vocabulary and no new storage shape.
    // reviveRole validates through isAdminCreatorRole, so the widened value
    // domain is picked up without a version bump — and without discarding the
    // boards a bump would have thrown away.
    let s = emptySlots();
    s = fillSlot(s, 0, img(1), 'eyes');
    s = fillSlot(s, 1, img(2), 'nose');
    s = fillSlot(s, 2, img(3), 'mouth_lips');
    s = fillSlot(s, 3, img(4), 'eyebrows');
    saveDraft(store, 38, { slots: s, prompt: 'pass 1', providerOption: 'option2' });

    expect(loadDraft(store, 38)!.slots.map((x) => x?.role)).toEqual([
      'eyes',
      'nose',
      'mouth_lips',
      'eyebrows',
    ]);
  });

  it('round-trips a refinement board', () => {
    let s = emptySlots();
    s = fillSlot(s, 0, img(2116), 'character_1');
    s = fillSlot(s, 1, img(2), 'hair');
    s = fillSlot(s, 2, img(3), 'eyes');
    s = fillSlot(s, 3, img(4), 'skin_complexion');
    saveDraft(store, 38, { slots: s, prompt: 'pass 2', providerOption: 'option2' });

    const back = loadDraft(store, 38)!;
    expect(back.slots.map((x) => x?.role)).toEqual([
      'character_1',
      'hair',
      'eyes',
      'skin_complexion',
    ]);
    // The reused result is stored as an id, never as bytes.
    expect(back.slots[0]?.image.id).toBe(2116);
  });

  it('downgrades a saved role that is no longer offered', () => {
    // A draft saved when Face Shape was selectable must not silently submit a
    // role the server now refuses. The existing downgrade rule covers it.
    store.setItem(
      'ficshon.adminCreator.draft.v1.38',
      JSON.stringify({
        slots: [
          { image: { id: 9, url: 'u', kind: 'uploaded' }, role: 'face_shape' },
          { image: { id: 10, url: 'u', kind: 'uploaded' }, role: 'facial_hair' },
        ],
        prompt: 'older board',
        providerOption: 'option2',
      }),
    );
    const back = loadDraft(store, 38)!;
    expect(back.slots[0]?.role).toBe('unspecified');
    expect(back.slots[1]?.role).toBe('unspecified');
    expect(back.slots[0]?.image.id).toBe(9);
  });

  it('still downgrades a role this build does not recognise', () => {
    // A draft written by a NEWER tab and reopened by older code must not
    // submit a role that side does not understand. The rule is unchanged by
    // Phase 2: unknown downgrades, never upgrades.
    store.setItem(
      'ficshon.adminCreator.draft.v1.38',
      JSON.stringify({
        slots: [{ image: { id: 7, url: 'u', kind: 'uploaded' }, role: 'ears' }],
        prompt: 'from the future',
        providerOption: 'option2',
      }),
    );
    expect(loadDraft(store, 38)!.slots[0]?.role).toBe('unspecified');
  });

  it('round-trips every role the selector offers', () => {
    let s = emptySlots();
    s = fillSlot(s, 0, img(1), 'character_1');
    s = fillSlot(s, 1, img(2), 'character_2');
    s = fillSlot(s, 2, img(3), 'tattoo_mark');
    s = fillSlot(s, 3, img(4), 'pose_composition');
    saveDraft(store, 38, { slots: s, prompt: 'p', providerOption: 'option2' });

    expect(loadDraft(store, 38)!.slots.map((x) => x?.role)).toEqual([
      'character_1',
      'character_2',
      'tattoo_mark',
      'pose_composition',
    ]);
  });

  it('round-trips duplicate identity roles as the same bucket', () => {
    // Two Character 1 cards must come back as two Character 1 cards — the
    // grouping is the whole reason the bucket exists.
    let s = emptySlots();
    s = fillSlot(s, 0, img(1), 'character_1');
    s = fillSlot(s, 1, img(2), 'character_1');
    s = fillSlot(s, 2, img(3), 'character_2');
    saveDraft(store, 38, { slots: s, prompt: 'p', providerOption: 'option2' });

    expect(toSubmission(loadDraft(store, 38)!.slots).reference_roles).toEqual([
      'character_1',
      'character_1',
      'character_2',
    ]);
  });

  it('normalises a slots array of the wrong length back to four cards', () => {
    store.setItem(
      'ficshon.adminCreator.draft.v1.38',
      JSON.stringify({ slots: [], prompt: 'p', providerOption: 'option2' }),
    );
    expect(loadDraft(store, 38)!.slots).toHaveLength(MAX_REFERENCES);
  });

  it('treats a pointer without a usable job id as absent', () => {
    store.setItem('ficshon.adminCreator.job.v1', JSON.stringify({ characterId: 38, jobId: '' }));
    expect(loadJobPointer(store, 38)).toBeNull();
    store.setItem('ficshon.adminCreator.job.v1', JSON.stringify({ characterId: 38 }));
    expect(loadJobPointer(store, 38)).toBeNull();
  });

  it('treats an entirely empty draft as no draft', () => {
    // So the page keeps its own defaults (notably the default provider) rather
    // than being handed empty strings.
    saveDraft(store, 38, { slots: emptySlots(), prompt: '', providerOption: '' });
    expect(loadDraft(store, 38)).toBeNull();
  });

  it('never throws when storage is unavailable', () => {
    // Private mode, blocked site data, or a full quota must not break the page.
    expect(() => saveDraft(null, 38, { slots: emptySlots(), prompt: 'p', providerOption: 'o' }))
      .not.toThrow();
    expect(loadDraft(null, 38)).toBeNull();
    expect(loadJobPointer(null, 38)).toBeNull();
    expect(() => clearJobPointer(null)).not.toThrow();

    expect(() =>
      saveDraft(hostileStore, 38, { slots: emptySlots(), prompt: 'p', providerOption: 'o' }),
    ).not.toThrow();
    expect(loadDraft(hostileStore, 38)).toBeNull();
    expect(loadJobPointer(hostileStore, 38)).toBeNull();
    expect(() => clearDraft(hostileStore, 38)).not.toThrow();
  });
});
