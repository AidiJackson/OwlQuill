// The four reference slots, as pure data.
//
// The generator presents exactly MAX_REFERENCES fixed cards. A card is either
// empty or holds one image plus its role, and the four are independent: filling
// card 3 says nothing about cards 1, 2 or 4.
//
// This module is deliberately free of React so the rules below can be pinned by
// tests. The component renders these functions' output and owns no logic of its
// own — the same split galleryKinds.ts and referenceKinds.ts already use, and
// the reason this file exists rather than useState juggling inside the panel.
//
// The server remains the authority: it re-validates every id and role on
// submission. These rules decide only what a founder can assemble locally.
import type { LibraryImage } from '@/lib/types';
import { MAX_REFERENCES } from '@/features/images/referenceKinds';
import { DEFAULT_ROLE, type AdminCreatorRole } from '@/features/adminCreator/referenceRoles';

/**
 * One populated card: an image and what it represents.
 *
 * Not features/images::SelectedReference. That type carries the Image
 * Generator's role vocabulary, which is frozen; Admin Creator's selector offers
 * the identity buckets and the attribute roles instead.
 */
export interface AdminCreatorReference {
  image: LibraryImage;
  role: AdminCreatorRole;
}

/** One card: an image with its role, or empty. */
export type ReferenceSlot = AdminCreatorReference | null;

/** Always exactly MAX_REFERENCES entries, in card order. */
export type ReferenceSlots = readonly ReferenceSlot[];

/** Where a populated card's image came from, for the source badge. */
export type ReferenceSource = 'library' | 'upload';

/** Four empty cards. */
export function emptySlots(): ReferenceSlots {
  return Array.from({ length: MAX_REFERENCES }, () => null);
}

/**
 * Force an array to exactly MAX_REFERENCES entries.
 *
 * Guards the boundary where slots arrive from outside this module (props,
 * persisted state), so no render can index past the end or lose a card.
 */
export function normalizeSlots(slots: ReferenceSlots): ReferenceSlots {
  const out: ReferenceSlot[] = [];
  for (let i = 0; i < MAX_REFERENCES; i += 1) out.push(slots[i] ?? null);
  return out;
}

function isValidIndex(index: number): boolean {
  return Number.isInteger(index) && index >= 0 && index < MAX_REFERENCES;
}

/**
 * Put an image in one card.
 *
 * If that image already occupies a DIFFERENT card it is MOVED, not copied.
 * `resolve_manual_references` refuses duplicate ids outright ("a repeated id is
 * a client bug") rather than deduping them, so letting one image sit in two
 * cards would build a payload the server rejects wholesale — losing the other
 * three references to a mistake the founder can't see. Moving is also what a
 * physical reference board does.
 *
 * Re-filling a card keeps its existing role: swapping the picture behind
 * "Clothing" is a replace, not a reset.
 */
export function fillSlot(
  slots: ReferenceSlots,
  index: number,
  image: LibraryImage,
  role?: AdminCreatorRole,
): ReferenceSlots {
  if (!isValidIndex(index)) return normalizeSlots(slots);
  const base = normalizeSlots(slots);
  const nextRole = role ?? base[index]?.role ?? DEFAULT_ROLE;
  return base.map((slot, i) => {
    if (i === index) return { image, role: nextRole };
    // Vacate wherever this image used to sit.
    if (slot && slot.image.id === image.id) return null;
    return slot;
  });
}

/** Empty one card. The other three are untouched and do not shift up. */
export function clearSlot(slots: ReferenceSlots, index: number): ReferenceSlots {
  if (!isValidIndex(index)) return normalizeSlots(slots);
  return normalizeSlots(slots).map((slot, i) => (i === index ? null : slot));
}

/** Change one card's role. A no-op on an empty card. */
export function setSlotRole(
  slots: ReferenceSlots,
  index: number,
  role: AdminCreatorRole,
): ReferenceSlots {
  if (!isValidIndex(index)) return normalizeSlots(slots);
  return normalizeSlots(slots).map((slot, i) => (i === index && slot ? { ...slot, role } : slot));
}

/**
 * Drop an image from wherever it sits.
 *
 * Called when an upload is deleted: a removed image must not stay staged, or
 * the server would refuse the submission and the founder would not know why.
 */
export function removeImage(slots: ReferenceSlots, imageId: number): ReferenceSlots {
  return normalizeSlots(slots).map((slot) => (slot && slot.image.id === imageId ? null : slot));
}

/** The first empty card, or null when all four are full. */
export function firstEmptySlot(slots: ReferenceSlots): number | null {
  const base = normalizeSlots(slots);
  for (let i = 0; i < MAX_REFERENCES; i += 1) if (!base[i]) return i;
  return null;
}

/**
 * Where a generated result belongs when it is reused as Character 1.
 *
 * REPLACES an existing Character 1 rather than adding a second one. That
 * distinction is the whole point: two Character 1 cards mean "two views of one
 * person", which is a legitimate thing to say about two photographs and a
 * actively harmful thing to say about successive generations of an edit.
 *
 * Observed 2026-08-22: reusing a result three times over a Hair refinement left
 * the board holding the original Grace plus two generated results, all marked
 * Character 1. The compiler correctly grouped them — "Reference images 1, 3 and
 * 4 are all the same person … reproduce that person's face and likeness
 * exactly" — so "replace Person A's hair" no longer named a single starting
 * image, and the original hairstyle came back.
 *
 * Returns the existing Character 1 card if there is one, otherwise the first
 * empty card, otherwise null (the caller must ask which card to overwrite —
 * nothing is ever silently evicted).
 */
export function character1ReuseTarget(slots: ReferenceSlots): number | null {
  const base = normalizeSlots(slots);
  const existing = base.findIndex((slot) => slot?.role === 'character_1');
  if (existing !== -1) return existing;
  return firstEmptySlot(base);
}

/** How many cards are populated. */
export function filledCount(slots: ReferenceSlots): number {
  return normalizeSlots(slots).filter(Boolean).length;
}

/** Ids currently staged, for disabling them in the library modal. */
export function usedImageIds(slots: ReferenceSlots): Set<number> {
  const ids = new Set<number>();
  for (const slot of normalizeSlots(slots)) if (slot) ids.add(slot.image.id);
  return ids;
}

/**
 * Library media or a device upload.
 *
 * Read from the image's own kind rather than remembered at pick time, so the
 * badge stays truthful for an upload chosen later from the library modal.
 */
export function slotSource(slot: AdminCreatorReference): ReferenceSource {
  return slot.image.kind === 'uploaded' ? 'upload' : 'library';
}

/**
 * The merge policy Admin Creator asks the server for.
 *
 * "deliberate" means the cards ARE the reference set: they are sent first, in
 * card order, and canon references fill whatever capacity is left. The Image
 * Generator on /images sends no mode at all and keeps the server default
 * ("augment", canon-first) — that default is what makes this one flag the
 * entire difference between the two workflows.
 */
export const ADMIN_CREATOR_REFERENCE_MODE = 'deliberate' as const;

/**
 * Compact the cards into the existing submission transport.
 *
 * Empty cards are skipped and populated cards keep their board order, because
 * the server preserves the listed order — and under `deliberate` that order is
 * priority order all the way to the provider. The two arrays are positionally
 * paired, exactly as `reference_image_ids` / `reference_roles` already expect.
 *
 * The mode travels with the ids rather than being set at the call site: it is a
 * property of THIS workflow, not of one button, so nothing on this page can
 * submit the cards without it.
 */
export function toSubmission(slots: ReferenceSlots): {
  reference_image_ids: number[];
  reference_roles: AdminCreatorRole[];
  reference_mode: typeof ADMIN_CREATOR_REFERENCE_MODE;
} {
  const reference_image_ids: number[] = [];
  const reference_roles: AdminCreatorRole[] = [];
  for (const slot of normalizeSlots(slots)) {
    if (!slot) continue;
    reference_image_ids.push(slot.image.id);
    reference_roles.push(slot.role);
  }
  return {
    reference_image_ids,
    reference_roles,
    reference_mode: ADMIN_CREATOR_REFERENCE_MODE,
  };
}
