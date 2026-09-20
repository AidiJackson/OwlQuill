// The image kinds that count as finished, shareable output.
//
// Mirror of the backend's PUBLIC_GALLERY_KINDS in
// backend/app/schemas/character_image.py. The server is the authority — it
// filters public galleries with its own copy — but the client needs the same
// list to ask for the right rows and to render the right controls, and three
// hand-maintained copies is how a list like this rots. Change both sides
// together; the test in __tests__/galleryKinds.test.ts pins this one.
//
// Everything NOT on this list (anchors, face refs, identity sketches, body
// plates) is a working reference used to build a character. Those are never
// gallery pieces, never eligible as an avatar or cover, and never deletable
// from the library.
export const GALLERY_KINDS = ['generated', 'cover', 'scene_only'] as const;

export type GalleryKind = (typeof GALLERY_KINDS)[number];

/** Human labels for the kinds a creator actually sees named in the UI. */
export const GALLERY_KIND_LABELS: Record<GalleryKind, string> = {
  generated: 'Generated',
  cover: 'Cover',
  scene_only: 'Scene',
};

/** True when an image is finished output rather than a working reference. */
export function isGalleryKind(kind: string): kind is GalleryKind {
  return (GALLERY_KINDS as readonly string[]).includes(kind);
}

/**
 * The label an ordinary surface shows for an image's kind — caption, alt
 * text, badge. The one place a stored kind becomes product language, so
 * "scene_only" reads as "Scene" everywhere rather than wherever someone
 * remembered to map it.
 *
 * Gallery kinds use GALLERY_KIND_LABELS. Anything else — the working
 * references an owner can see in their own gallery, or a kind the backend
 * grows later — falls back to a readable phrase ("Identity face ref") rather
 * than the raw enum, and never throws. Filtering must keep using the
 * canonical values; this is presentation only.
 */
export function imageKindLabel(kind: string | null | undefined): string {
  if (!kind) return 'Image';
  if (isGalleryKind(kind)) return GALLERY_KIND_LABELS[kind];
  const words = kind.replace(/_/g, ' ').trim();
  if (!words) return 'Image';
  return words.charAt(0).toUpperCase() + words.slice(1);
}
