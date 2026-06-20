/**
 * Extract a human-readable message from a StoryLab backend error payload.
 *
 * FastAPI wraps HTTPException detail under the top-level `detail` key. StoryLab
 * endpoints return a structured object whose human text lives in `detail.detail`
 * (e.g. quota, canon-contradiction, generation-failure responses). Earlier code
 * read `detail.message` — which these payloads never set — so every error
 * stringified to "[object Object]". The order below prefers the real text and
 * falls back to a plain string detail, then an HTTP status string.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function extractApiErrorMessage(payload: any, status: number): string {
  return (
    payload?.detail?.detail ||
    payload?.detail?.message ||
    (typeof payload?.detail === 'string' ? payload.detail : '') ||
    `HTTP ${status}`
  );
}
