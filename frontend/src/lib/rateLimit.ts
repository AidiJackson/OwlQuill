/**
 * Wording for HTTP 429 responses.
 *
 * The backend sends the human sentence in `detail` (see
 * app/api/routes/auth.py). This module exists for the cases where it cannot:
 * slowapi's stock error body has no `detail` at all, and a throttle applied by
 * an edge proxy rather than the app may not be JSON. Without a fallback the
 * generic client renders the bare string "HTTP 429", which is what users hit
 * when login was failing.
 */

/** Fallback when the server sent no usable sentence of its own. */
export const RATE_LIMIT_FALLBACK_MESSAGE =
  'Too many attempts. Please wait a few minutes and try again.';

/** Approved copy for a throttled sign-in, mirrored from the backend. */
export const RATE_LIMIT_LOGIN_MESSAGE =
  'Too many login attempts. Please wait a few minutes and try again.';

/**
 * Pick the message to show for a 429.
 *
 * Prefers the server's `detail` so the endpoint-specific wording (e.g. the
 * login sentence) survives; falls back to generic copy otherwise. Never
 * returns a status code.
 */
export function rateLimitMessage(
  detail: unknown,
  fallback: string = RATE_LIMIT_FALLBACK_MESSAGE
): string {
  return typeof detail === 'string' && detail.trim() ? detail.trim() : fallback;
}
