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
