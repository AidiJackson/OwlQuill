/**
 * WriteSpace finalisation — carrying a finished draft to the composer that
 * publishes it.
 *
 * WriteSpace composes the writing; the Commons or Realm composer prepares the
 * post (character, IC/OOC, post kind, image) and creates it. "Continue to
 * publish" writes one record here and navigates; the destination composer
 * reads it, prefills itself, and adopts the draft's composition session with
 * `CompositionTracker.resume()`. Nothing is posted by leaving WriteSpace.
 *
 * ## This record is not evidence
 *
 * Everything in it is client navigation state, as editable as the textarea it
 * fills. The server trusts none of it:
 *
 * - `sessionId` is only a pointer. Provenance comes from the counters the
 *   server holds for that session, which it only returns to its owner; a
 *   foreign or invented id adopts nothing and continues nothing.
 * - `characterId` is a preselection. The post endpoint checks ownership.
 * - `body`, `title` and `contentType` are prefill, edited freely before Post.
 *
 * Deliberately separate from `ficshon.composition.handoff` (copy-for-posting):
 * that key is taken by whichever tracker opens a session next, and this flow
 * must neither write nor consume it.
 */
import { safeRemove } from './safeStorage';

/** WriteSpace's autosaved draft, in localStorage. Shared so that the composer
 *  that finally publishes the draft can clear it without repeating the keys. */
export const WRITESPACE_TITLE_KEY = 'ficshon.workspace.title';
export const WRITESPACE_BODY_KEY = 'ficshon.workspace.body';
/** The composition session the autosaved draft belongs to. Holds an opaque id
 *  and nothing else — see CompositionTracker.resume(). */
export const WRITESPACE_SESSION_KEY = 'ficshon.writespace.composition_session_id';

/** Remove the draft, its title and its session id. Called once the draft has
 *  been published: its session is spent and must not be resumed again. */
export function clearWriteSpaceDraft(): void {
  safeRemove(WRITESPACE_TITLE_KEY);
  safeRemove(WRITESPACE_BODY_KEY);
  safeRemove(WRITESPACE_SESSION_KEY);
}

const FINALISE_KEY = 'ficshon.writespace.finalise';
const FINALISE_VERSION = 1;

/** A record older than this is ignored. Matches the server's session age cap:
 *  past it, what was handed off is no longer the draft anyone is finishing. */
const FINALISE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

export type FinaliseContentType = 'ic' | 'ooc' | 'narration';

export interface WriteSpaceFinalisation {
  v: typeof FINALISE_VERSION;
  /** WriteSpace's composition session, or null when it never opened one. */
  sessionId: string | null;
  characterId: number;
  contentType: FinaliseContentType;
  title: string;
  body: string;
  /** Target realm, or null for the Commons. */
  realmId: number | null;
  createdAt: number;
}

export type FinaliseDestination = { commons: true } | { realmId: number };

/** sessionStorage: a handoff belongs to the tab it was made in and survives a
 *  reload of it, which is exactly the lifetime wanted. */
function store(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

const isPositiveInt = (n: unknown): n is number =>
  typeof n === 'number' && Number.isInteger(n) && n > 0;

function parse(raw: string, now: number): WriteSpaceFinalisation | null {
  let r: Record<string, unknown>;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    r = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  if (r.v !== FINALISE_VERSION) return null;
  if (r.sessionId !== null && !(typeof r.sessionId === 'string' && r.sessionId.length > 0 && r.sessionId.length <= 36)) {
    return null;
  }
  if (!isPositiveInt(r.characterId)) return null;
  if (r.contentType !== 'ic' && r.contentType !== 'ooc' && r.contentType !== 'narration') return null;
  if (typeof r.title !== 'string') return null;
  if (typeof r.body !== 'string' || !r.body.trim()) return null;
  if (r.realmId !== null && !isPositiveInt(r.realmId)) return null;
  if (typeof r.createdAt !== 'number' || !Number.isFinite(r.createdAt)) return null;
  if (now - r.createdAt > FINALISE_MAX_AGE_MS || r.createdAt - now > 60_000) return null;
  return {
    v: FINALISE_VERSION,
    sessionId: r.sessionId as string | null,
    characterId: r.characterId,
    contentType: r.contentType,
    title: r.title,
    body: r.body,
    realmId: r.realmId as number | null,
    createdAt: r.createdAt,
  };
}

/** Store a finalisation. `false` when storage refused it — the caller must not
 *  navigate as if the draft will arrive. */
export function writeFinalisation(
  input: Omit<WriteSpaceFinalisation, 'v' | 'createdAt'>,
  now: number = Date.now(),
): boolean {
  const s = store();
  if (!s) return false;
  const record: WriteSpaceFinalisation = { ...input, v: FINALISE_VERSION, createdAt: now };
  try {
    s.setItem(FINALISE_KEY, JSON.stringify(record));
    return true;
  } catch {
    return false;
  }
}

/**
 * The stored finalisation if it is valid and addressed to `destination`.
 *
 * Reading does not consume: a reload of the destination restores it, and it is
 * cleared only by a successful post, Discard, or WriteSpace reopening. A record
 * that is malformed or expired is removed; one for another destination is left
 * for its own composer.
 */
export function readFinalisation(
  destination: FinaliseDestination,
  now: number = Date.now(),
): WriteSpaceFinalisation | null {
  const s = store();
  if (!s) return null;
  let raw: string | null;
  try {
    raw = s.getItem(FINALISE_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  const record = parse(raw, now);
  if (!record) {
    clearFinalisation();
    return null;
  }
  const wanted = 'commons' in destination ? null : destination.realmId;
  return record.realmId === wanted ? record : null;
}

export function clearFinalisation(): void {
  try {
    store()?.removeItem(FINALISE_KEY);
  } catch {
    /* nothing to clear if storage is unreachable */
  }
}
