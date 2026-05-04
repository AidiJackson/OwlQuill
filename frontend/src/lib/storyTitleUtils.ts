const _UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuidLike(value: string): boolean {
  return _UUID_RE.test(value.trim());
}

const _STOP_WORDS = new Set([
  'a','an','the','of','in','on','at','to','is','are','was','were','and','or','but',
]);

/**
 * Derives a short readable title from the first meaningful words of a premise.
 * Returns fallback when there is nothing useful to extract.
 */
export function deriveReadableTitle(
  premise: string | null | undefined,
  fallback = 'Untitled Story',
): string {
  if (!premise?.trim()) return fallback;
  const words = premise
    .replace(/[^\w\s]/g, ' ')
    .trim()
    .split(/\s+/)
    .filter((w) => w.length > 1 && !_STOP_WORDS.has(w.toLowerCase()))
    .slice(0, 6);
  if (words.length === 0) return fallback;
  const title = words.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ');
  return title.length > 60 ? title.slice(0, 57) + '…' : title;
}
