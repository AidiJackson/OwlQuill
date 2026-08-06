/**
 * The post-header badge set: what kind of writing this is, and what kind of
 * post it is.
 *
 * One component, one vocabulary — the same reason `ProvenanceBadge` exists.
 * These labels previously lived as private helpers inside Home, RealmDetail and
 * CommentSection, which had drifted into three different visual systems on the
 * same row of the same feed: quiet outlined chips in the Commons, solid
 * 12px blocks in raw palette colours in a Realm, and a third variant in
 * comments. Geometry and colour now come from `.badge` in index.css, shared
 * with the provenance badge, so every chip in a header is the same height
 * whatever it says.
 *
 * Accessibility: "IC" and "OOC" are jargon abbreviations that a screen reader
 * spells out and a new reader cannot expand. Each badge therefore carries a
 * plain-language `title` and `aria-label`, so the abbreviation stays for people
 * who know it and the meaning is available to everyone else.
 */

/** Exported so the tests assert against *this* table rather than a copy of it —
 *  a mirrored table in a test file can never catch the two drifting apart. */
export const TYPES: Record<string, { label: string; full: string; className: string }> = {
  ic: { label: 'IC', full: 'In character', className: 'badge-ic' },
  ooc: { label: 'OOC', full: 'Out of character', className: 'badge-ooc' },
  narration: { label: 'Narration', full: 'Narration', className: 'badge-narration' },
};

export const KINDS: Record<string, { label: string; full: string; className: string }> = {
  open_starter: {
    label: 'Open Starter',
    full: 'Open starter — anyone may join this scene',
    className: 'badge-starter',
  },
  finished_piece: {
    label: 'Finished Piece',
    full: 'A finished piece of writing',
    className: 'badge-finished',
  },
};

/** IC / OOC / Narration. Unknown values render nothing rather than guessing —
 *  the same rule the provenance badge follows. */
export function PostTypeBadge({ contentType }: { contentType?: string | null }) {
  const badge = contentType ? TYPES[contentType] : undefined;
  if (!badge) return null;
  return (
    <span className={`badge badge-type ${badge.className}`} title={badge.full} aria-label={badge.full}>
      {badge.label}
    </span>
  );
}

/** Open Starter / Finished Piece. `general` is the default and gets no badge —
 *  a badge on every post is a badge on none. */
export function PostKindBadge({ postKind }: { postKind?: string | null }) {
  const badge = postKind ? KINDS[postKind] : undefined;
  if (!badge) return null;
  return (
    <span className={`badge ${badge.className}`} title={badge.full} aria-label={badge.full}>
      {badge.label}
    </span>
  );
}
