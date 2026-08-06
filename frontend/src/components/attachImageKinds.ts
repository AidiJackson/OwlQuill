import type { LibraryImage } from '@/lib/types';

// Image kinds a character may attach to a post. Mirrors the server's
// POST_ATTACHABLE_IMAGE_KINDS (backend/app/models/character_image.py), which is
// the authority — this list only decides what the picker *offers*.
//
// An allowlist, not a denylist, so a newly added kind is private by default.
// Identity sketches, face/body references, anchors and accessory sheets are
// private production material and are never attachable.
const ATTACHABLE_IMAGE_KINDS = new Set(['generated', 'cover', 'scene_only']);

export function isAttachableImage(img: Pick<LibraryImage, 'kind'>): boolean {
  return ATTACHABLE_IMAGE_KINDS.has(img.kind);
}

/** The same list, for sending as a server-side `kind` filter. */
export const ATTACHABLE_KIND_LIST = [...ATTACHABLE_IMAGE_KINDS];
