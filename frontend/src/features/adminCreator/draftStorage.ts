// Surviving a lost page: the Admin Creator draft and its in-flight job.
//
// Observed 2026-08-22: two 45-second OpenAI generations were interrupted by a
// full page load of "/" roughly 30s in. Both images were generated, paid for
// and saved correctly — the server never faltered — but the tab came back with
// an empty board and no way to reach either result, so three reference images
// were re-uploaded and a second generation was bought for nothing.
//
// Nothing here changes what is generated. It only means a reload costs the
// founder no work and no money.
//
// Two separate records, because they have different lifetimes:
//
//   * the DRAFT — cards, roles, prompt, provider — is per character and lives
//     until it is replaced;
//   * the JOB POINTER is a single submission's identity and is cleared the
//     moment its result is dismissed.
//
// sessionStorage, not localStorage: a draft belongs to the tab you were working
// in. Restoring a week-old board into a fresh session would be a surprise, and
// a stale reference id would fail server validation anyway.
//
// IMAGE BYTES ARE NEVER STORED. Only the ids and the few display fields the
// board renders — the images themselves already live on the server, and a
// quota-sized blob in session storage would be both wasteful and a way to
// resurrect an image the founder has since deleted.
//
// Pure functions over an injectable storage object so every rule below is
// testable without a DOM.
import type { LibraryImage } from '@/lib/types';
import { MAX_REFERENCES } from '@/features/images/referenceKinds';
import {
  DEFAULT_ROLE,
  isAdminCreatorRole,
  type AdminCreatorRole,
} from '@/features/adminCreator/referenceRoles';
import { emptySlots, normalizeSlots, type ReferenceSlots } from './referenceSlots';

/** The subset of a storage API this module uses; `sessionStorage` satisfies it. */
export interface DraftStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

// Versioned keys. A shape change bumps the version rather than trying to
// migrate a draft — the cost of losing one unsent board is a re-pick, and the
// cost of mis-reading an old shape is a corrupted submission.
const DRAFT_PREFIX = 'ficshon.adminCreator.draft.v1.';
const JOB_KEY = 'ficshon.adminCreator.job.v1';

/** What the board needs to come back exactly as it was left. */
export interface AdminCreatorDraft {
  slots: ReferenceSlots;
  prompt: string;
  providerOption: string;
}

/** Identity of one submitted generation — enough to ask the server about it. */
export interface JobPointer {
  characterId: number;
  jobId: string;
}

/** Per-character key, so switching character can never show another's board. */
function draftKey(characterId: number): string {
  return `${DRAFT_PREFIX}${characterId}`;
}

/** Every storage access is best-effort: private mode and quota both throw. */
function safeRead(store: DraftStore | null, key: string): string | null {
  if (!store) return null;
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

function safeWrite(store: DraftStore | null, key: string, value: string): void {
  if (!store) return;
  try {
    store.setItem(key, value);
  } catch {
    // A full or unavailable store must never break the page the founder is
    // working in. Losing the draft is the already-tolerated outcome.
  }
}

function safeRemove(store: DraftStore | null, key: string): void {
  if (!store) return;
  try {
    store.removeItem(key);
  } catch {
    /* see safeWrite */
  }
}

/**
 * A stored role, or the safe default.
 *
 * DELIBERATE DOWNGRADE, not a migration. A draft written before the selector
 * existed can carry `character_appearance`, which the Admin Creator vocabulary
 * no longer offers. It is NOT remapped to `character_1`: the two are not
 * equivalent. `character_appearance` is supporting likeness evidence with no
 * grouping claim, whereas `character_1` asserts "this is Person A, and every
 * other Person A card is the same individual" — a strictly stronger statement
 * that would start reaching the provider without the founder ever choosing it.
 * Silently upgrading authority is the one thing this feature must not do, so an
 * unrecognised role becomes `unspecified`: visible in the selector, trivially
 * re-picked, and carrying no claim in the meantime.
 */
function reviveRole(value: unknown): AdminCreatorRole {
  return typeof value === 'string' && isAdminCreatorRole(value) ? value : DEFAULT_ROLE;
}

/**
 * Rebuild one card from stored JSON, or null if it is not trustworthy.
 *
 * Deliberately strict about the two fields that carry meaning to the SERVER —
 * the image id and the role — and forgiving about the display fields, which
 * only affect what the thumbnail looks like until the next refresh. A card that
 * fails this check is dropped rather than guessed at: an empty slot is obvious
 * and fixable, whereas a card carrying a wrong id would be submitted.
 */
function reviveSlot(raw: unknown): { image: LibraryImage; role: AdminCreatorRole } | null {
  if (!raw || typeof raw !== 'object') return null;
  const entry = raw as Record<string, unknown>;
  const image = entry.image as Record<string, unknown> | undefined;
  if (!image || typeof image !== 'object') return null;
  const id = image.id;
  const url = image.url;
  if (typeof id !== 'number' || !Number.isFinite(id) || typeof url !== 'string' || !url) {
    return null;
  }
  const role = reviveRole(entry.role);
  return {
    image: {
      id,
      url,
      kind: typeof image.kind === 'string' ? image.kind : 'uploaded',
    } as LibraryImage,
    role,
  };
}

/** Store only what the board renders, never the image itself. */
function packSlots(slots: ReferenceSlots) {
  return normalizeSlots(slots).map((slot) =>
    slot
      ? {
          image: { id: slot.image.id, url: slot.image.url, kind: slot.image.kind },
          role: slot.role,
        }
      : null,
  );
}

export function saveDraft(
  store: DraftStore | null,
  characterId: number,
  draft: AdminCreatorDraft,
): void {
  safeWrite(
    store,
    draftKey(characterId),
    JSON.stringify({
      slots: packSlots(draft.slots),
      prompt: draft.prompt,
      providerOption: draft.providerOption,
    }),
  );
}

/**
 * The stored draft for one character, or null when there is nothing usable.
 *
 * Never throws and never returns a partially-valid board: malformed JSON, a
 * wrong top-level shape, or a slots array of the wrong length all resolve to
 * either a clean draft or null.
 */
export function loadDraft(store: DraftStore | null, characterId: number): AdminCreatorDraft | null {
  const raw = safeRead(store, draftKey(characterId));
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const data = parsed as Record<string, unknown>;

  const storedSlots = Array.isArray(data.slots) ? data.slots : [];
  const slots = normalizeSlots(
    Array.from({ length: MAX_REFERENCES }, (_, i) => reviveSlot(storedSlots[i])),
  );
  const prompt = typeof data.prompt === 'string' ? data.prompt : '';
  const providerOption = typeof data.providerOption === 'string' ? data.providerOption : '';

  // An entirely empty draft is indistinguishable from no draft, and returning
  // null lets the caller keep its own defaults (notably the default provider)
  // instead of being handed empty strings.
  if (!prompt && !providerOption && slots.every((s) => s === null)) return null;
  return { slots, prompt, providerOption };
}

export function clearDraft(store: DraftStore | null, characterId: number): void {
  safeRemove(store, draftKey(characterId));
}

/**
 * Which provider a character's board should show.
 *
 * The provider is part of the character-scoped draft, not a tool-wide
 * preference, so a character with no draft of its own gets the DEFAULT — never
 * whatever the previously selected character happened to be using. Inheriting
 * it looked harmless but was not: the write effect immediately persisted the
 * inherited value into the new character's draft, so a provider chosen for
 * Davies silently became another character's stored choice.
 *
 * ``isSupported`` is passed in rather than imported so this module stays
 * ignorant of which providers the page happens to offer; adding or removing one
 * is a change to the page, not to storage.
 */
export function providerForDraft(
  draft: AdminCreatorDraft | null,
  isSupported: (value: string) => boolean,
  fallback: string,
): string {
  if (draft && isSupported(draft.providerOption)) return draft.providerOption;
  return fallback;
}

/** Remember which job this session submitted, so it can be asked about by id. */
export function saveJobPointer(store: DraftStore | null, pointer: JobPointer): void {
  safeWrite(store, JOB_KEY, JSON.stringify(pointer));
}

/**
 * The submitted job to re-attach to, or null.
 *
 * ``characterId`` scopes the answer: a pointer for another character is not
 * this board's job and must not be resumed onto it. One pointer is stored at a
 * time because Admin Creator runs one generation at a time; a new submission
 * replaces it.
 */
export function loadJobPointer(store: DraftStore | null, characterId: number): JobPointer | null {
  const raw = safeRead(store, JOB_KEY);
  if (!raw) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') return null;
  const data = parsed as Record<string, unknown>;
  const storedId = data.characterId;
  const jobId = data.jobId;
  if (typeof storedId !== 'number' || typeof jobId !== 'string' || !jobId) return null;
  if (storedId !== characterId) return null;
  return { characterId: storedId, jobId };
}

export function clearJobPointer(store: DraftStore | null): void {
  safeRemove(store, JOB_KEY);
}

/** `sessionStorage` when it exists and is reachable, otherwise null. */
export function defaultStore(): DraftStore | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    // Some embedded webviews throw on access when site data is blocked.
    return null;
  }
}

export { emptySlots };
