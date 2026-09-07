// Ficshon's built-in account sigils — the ONLY account avatar that is a string.
//
// Eight small inline SVG marks offered as an account avatar. They are not
// media: no bytes in a bucket, no UserImage row, nothing to own. For a Writer
// the sigil stays private (their public face is the character); for a Wanderer
// it is the avatar shown beside their public username on comments.
//
// WHY THIS IS A MODULE AND NOT A CONST IN Profile.tsx. As of Beta Boundary 2
// these exact strings are a SERVER-VALIDATED CONTRACT: `PATCH /users/me` now
// accepts `avatar_url` only when it is byte-identical to one of them
// (backend/app/core/account_sigils.py). A value the client can render but the
// server refuses is a save that fails in front of the user, so the two sides
// are pinned against each other rather than trusted to stay in step.
//
// THE PIN. Neither side imports the other — they are different runtimes — so
// they are pinned the way this codebase already pins PUBLIC_GALLERY_KINDS
// against galleryKinds.ts: each side derives the same SHA-256 over its own
// sorted URL set and asserts the same constant. Editing the template or the
// palette here without editing the Python fails this side's test; the reverse
// fails theirs. SIGIL_SET_DIGEST is that constant.
//
// The template below must stay character-for-character identical to
// `_sigil_url` in account_sigils.py — attribute order and the absence of
// whitespace between elements both change the encoded output.

/** `[id, label, gradientFrom, gradientTo, glyphPath]`, in picker order. */
const SIGIL_SPECS: readonly (readonly [string, string, string, string, string])[] = [
  ['ember',    'Ember',    '#f59e0b', '#7c2d12', 'M32 14 L38 28 L52 32 L38 36 L32 50 L26 36 L12 32 L26 28 Z'],
  ['tide',     'Tide',     '#38bdf8', '#1e3a8a', 'M12 38 Q22 28 32 38 T52 38 Q42 48 32 42 T12 38 Z'],
  ['grove',    'Grove',    '#34d399', '#064e3b', 'M32 12 Q46 26 32 52 Q18 26 32 12 Z'],
  ['dusk',     'Dusk',     '#a78bfa', '#312e81', 'M40 14 A18 18 0 1 0 50 40 A14 14 0 1 1 40 14 Z'],
  ['rose',     'Rose',     '#fb7185', '#881337', 'M32 18 A8 8 0 0 1 46 24 Q46 38 32 46 Q18 38 18 24 A8 8 0 0 1 32 18 Z'],
  ['aurum',    'Aurum',    '#fbbf24', '#78350f', 'M32 12 L36 28 L52 32 L36 36 L32 52 L28 36 L12 32 L28 28 Z'],
  ['mist',     'Mist',     '#94a3b8', '#1e293b', 'M20 40 A12 12 0 1 1 30 22 A10 10 0 1 1 46 30 A8 8 0 1 1 44 40 Z'],
  ['sol',      'Sol',      '#f97316', '#7c2d12', 'M32 20 A12 12 0 1 0 32 44 A12 12 0 1 0 32 20 Z'],
] as const;

function sigilUrl(from: string, to: string, glyph: string): string {
  return `data:image/svg+xml,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="${from}"/><stop offset="1" stop-color="${to}"/>` +
    `</linearGradient></defs>` +
    `<rect width="64" height="64" fill="url(#g)"/>` +
    `<path d="${glyph}" fill="rgba(255,255,255,0.85)"/>` +
    `</svg>`
  )}`;
}

export interface AccountSigil {
  id: string;
  label: string;
  url: string;
}

/** The eight sigils, in the order the picker shows them. */
export const ACCOUNT_SIGILS: AccountSigil[] = SIGIL_SPECS.map(
  ([id, label, from, to, glyph]) => ({ id, label, url: sigilUrl(from, to, glyph) })
);

/** Every sigil URL, for membership checks. */
export const ACCOUNT_SIGIL_URLS: ReadonlySet<string> = new Set(
  ACCOUNT_SIGILS.map((s) => s.url)
);

/**
 * SHA-256 over the sorted sigil URLs joined by newline — the value the backend
 * derives from its own copy as `SIGIL_SET_DIGEST`. Asserted by
 * `__tests__/accountSigils.test.ts`; the Python side asserts the same constant.
 */
export const SIGIL_SET_DIGEST =
  'cb88ec9be326ec416636510c74008658925b43f208ff0d8de8481ac8e1206042';
