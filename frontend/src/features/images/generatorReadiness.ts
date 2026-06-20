import type { Character } from '@/lib/types';

/**
 * Mirrors _parse_anchor_json on the backend: the legacy identity anchor is
 * considered present only when anchors.front.url is non-empty.
 *
 * Returns true / false / undefined — undefined means the JSON is absent
 * (legacy path; the backend may still fall back to DB data).
 */
export function parseHasIdentityAnchor(
  raw: string | null | undefined,
): boolean | undefined {
  if (!raw) return undefined;
  try {
    const data = JSON.parse(raw);
    return !!data?.anchors?.front?.url;
  } catch {
    return false;
  }
}

export interface GeneratorGuards {
  /** Character is selected but its visual identity is not locked yet. */
  lockedGuardActive: boolean;
  /** Locked legacy character whose identity anchor data is missing. */
  anchorGuardActive: boolean;
}

/**
 * Decide which (if any) readiness guard should block image generation.
 *
 * A character is ready when EITHER the legacy identity anchor exists, OR the
 * character is visual_locked with a v2 identity canon (has_identity_canon).
 * v2 canon characters (S24AR/S24AU.2) are accepted by the backend scene route
 * directly, so the legacy anchor guard must not block them.
 */
export function computeGeneratorGuards(
  selectedCharacterId: number | null,
  selectedChar: Pick<
    Character,
    'visual_locked' | 'has_identity_canon' | 'identity_anchor_json'
  > | null,
): GeneratorGuards {
  const isCharacterLocked = selectedChar?.visual_locked ?? false;
  const hasIdentityCanon = selectedChar?.has_identity_canon ?? false;
  const hasIdentityAnchor = parseHasIdentityAnchor(selectedChar?.identity_anchor_json);

  const lockedGuardActive = selectedCharacterId !== null && !isCharacterLocked;
  const anchorGuardActive =
    selectedCharacterId !== null &&
    isCharacterLocked &&
    !hasIdentityCanon &&
    hasIdentityAnchor === false;

  return { lockedGuardActive, anchorGuardActive };
}
