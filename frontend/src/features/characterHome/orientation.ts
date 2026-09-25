import { safeGet, safeSet } from '@/lib/safeStorage';

/**
 * The public Character Home's one-time orientation — whether it has been
 * dismissed.
 *
 * ONE key for all of Ficshon, never per character: a visitor who dismisses the
 * welcome on Pan and then follows a commenter to another Home has already been
 * welcomed. Versioned so a future rewrite of the orientation can be shown again
 * by moving to `.v2`, without anyone having to clear storage.
 *
 * Storage is optional (see `lib/safeStorage`). Anything other than the exact
 * dismissed marker — nothing stored, storage denied, a throwing read, a value
 * someone else wrote — reads as NOT dismissed, so the orientation shows. That
 * is the deterministic fallback: an unexplained page is worse than a welcome
 * shown one extra time.
 */
export const ORIENTATION_KEY = 'ficshon.publicHomeOrientation.v1';
export const ORIENTATION_DISMISSED = 'dismissed';

export function isOrientationDismissed(): boolean {
  return safeGet(ORIENTATION_KEY) === ORIENTATION_DISMISSED;
}

/** Best effort. The caller hides the orientation whether or not this persisted. */
export function persistOrientationDismissed(): boolean {
  return safeSet(ORIENTATION_KEY, ORIENTATION_DISMISSED);
}
