// Manual generation references — the kinds a founder may hand-pick, the cap,
// and the roles a reference can carry.
//
// A plain constants module (no React, no runtime imports) for the same reason
// galleryKinds.ts is one: these mirror server-side allowlists, and a mirror is
// worth nothing if it can't be pinned by a test.
//
// The server is the authority on every value here — it re-validates each id and
// role on submission. This module decides only what the founder is OFFERED.
import type { LibraryImage } from '@/lib/types';

/** Mirror of backend MAX_MANUAL_REFERENCES (app/services/manual_references.py). */
export const MAX_REFERENCES = 4;

/**
 * Kinds that may be hand-picked as a reference. Mirror of
 * REFERENCE_SELECTABLE_IMAGE_KINDS in backend/app/models/character_image.py —
 * change both together.
 *
 * Identity, anchor and accessory kinds are deliberately absent: which canon
 * slots reach the provider is the reference router's decision, made from locked
 * canon. A second hand-picked path into the same payload would blur the
 * canon-vs-manual boundary this feature has to keep sharp.
 */
export const SELECTABLE_REFERENCE_KINDS = [
  'uploaded',
  'generated',
  'scene_only',
  'cover',
] as const;

export type SelectableReferenceKind = (typeof SELECTABLE_REFERENCE_KINDS)[number];

export function isSelectableReferenceKind(kind: string): kind is SelectableReferenceKind {
  // Fail closed: a kind the backend grows later is unselectable until this list
  // is deliberately updated.
  return (SELECTABLE_REFERENCE_KINDS as readonly string[]).includes(kind);
}

/**
 * What a reference is FOR. Mirror of backend
 * app/services/manual_references.py::ReferenceRole.
 *
 * A role is advisory prompt context and confers no authority: tagging an image
 * "Character / Appearance" does not make it identity truth. Canon still defines
 * who the character is, and the compiled prompt says so explicitly.
 */
export const REFERENCE_ROLES = [
  'unspecified',
  'character_appearance',
  'clothing',
  'environment',
  'other',
] as const;

export type ReferenceRole = (typeof REFERENCE_ROLES)[number];

export const REFERENCE_ROLE_LABELS: Record<ReferenceRole, string> = {
  unspecified: 'Unspecified',
  character_appearance: 'Character / Appearance',
  clothing: 'Clothing',
  environment: 'Environment',
  other: 'Other reference',
};

/** One hand-picked reference, as the composer holds it before submission. */
export interface SelectedReference {
  image: LibraryImage;
  role: ReferenceRole;
}
