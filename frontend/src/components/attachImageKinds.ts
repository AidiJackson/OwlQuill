import type { LibraryImage } from '@/lib/types';

// Image kinds that are attachable to a normal post: user-generated scene images
// (`scene_only`, the current Image Generator output) and legacy library images
// (`generated`). Identity/anchor/accessory canon reference cards and cover banners
// are intentionally excluded — they are not normal post attachments.
const ATTACHABLE_IMAGE_KINDS = new Set(['scene_only', 'generated']);

export function isAttachableImage(img: Pick<LibraryImage, 'kind'>): boolean {
  return ATTACHABLE_IMAGE_KINDS.has(img.kind);
}
