// Where to send someone after they authenticate.
//
// Two jobs, kept in one place because they are the same decision seen from
// both ends: recording the destination a redirect interrupted, and deciding
// whether a recorded destination may be navigated to.
//
// Every navigation that consumes a caller-influenced destination must go
// through `safeReturnTo`. The value travels in React Router location state,
// which is same-origin and not user-typed today — but a `?returnTo=` query
// parameter is the obvious next request, and a validator added only when that
// lands is a validator added too late.

/** Where an unknown, missing or unsafe destination sends the user instead. */
export const DEFAULT_RETURN_TO = '/';

/**
 * Routes that must never be a post-authentication destination.
 *
 * Returning to one of these bounces the user straight back into the flow they
 * just completed — /login redirects an authenticated visitor to their return
 * destination, so a return destination of /login is a redirect cycle.
 */
const AUTH_ROUTES = ['/login', '/register', '/forgot-password', '/reset-password'];

/**
 * Anything a browser might normalise away before we see the result: C0
 * controls (including tab, CR and LF), space, DEL, and the backslash.
 *
 * These are rejected rather than stripped. `/\evil.example` and
 * `/<tab>/evil.example` both become `//evil.example` once the browser is done
 * with them, so sanitising is not a safe repair — a rewritten string is still
 * an attacker's string. A legitimate path carries `%20`, never a raw space.
 */
const UNSAFE_CHARACTERS = /[\u0000-\u0020\u007f\\]/;

type PartialLocation = {
  pathname: string;
  search?: string;
  hash?: string;
};

/**
 * Flatten a router location into the string form we hand back after login.
 *
 * Search and hash are included because a deep link is rarely just a pathname —
 * `/characters/59?tab=media#gallery` and `/characters/59` are different
 * destinations, and dropping the tail silently returns the user to the wrong
 * one while looking like it worked.
 */
export function buildReturnTo(location: PartialLocation): string {
  return `${location.pathname}${location.search ?? ''}${location.hash ?? ''}`;
}

/**
 * Validate a return destination, falling back to `/` when it is missing,
 * malformed, external, or would loop.
 *
 * Accepts only same-origin absolute paths. Fail-closed and total: any input
 * type, any shape, always yields a path this app can safely navigate to.
 */
export function safeReturnTo(value: unknown): string {
  if (typeof value !== 'string' || value === '') return DEFAULT_RETURN_TO;
  if (UNSAFE_CHARACTERS.test(value)) return DEFAULT_RETURN_TO;

  // Must be a root-relative path. This alone rejects `https://evil.example`,
  // `javascript:...` and every other scheme, since a scheme cannot precede a
  // leading slash.
  if (!value.startsWith('/')) return DEFAULT_RETURN_TO;
  // ...and `//evil.example`, which is a path by that test but an absolute URL
  // to the browser.
  if (value.startsWith('//')) return DEFAULT_RETURN_TO;

  // Compare the pathname only, lowercased: React Router matches routes
  // case-insensitively by default, so `/LOGIN` reaches the login route and
  // would cycle exactly as `/login` does.
  const pathname = value.split(/[?#]/, 1)[0].toLowerCase();
  if (AUTH_ROUTES.includes(pathname)) return DEFAULT_RETURN_TO;

  return value;
}

/** Read a return destination out of React Router location state, validated. */
export function returnToFromState(state: unknown): string {
  return safeReturnTo((state as { from?: unknown } | null)?.from);
}
