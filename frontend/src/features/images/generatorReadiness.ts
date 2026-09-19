import type { Character } from '@/lib/types';

export interface GeneratorGuards {
  /** Character is selected but its Character Canon is not established
   *  (visual_locked is false). */
  lockedGuardActive: boolean;
  /** Character is marked established but has no generated Character Canon —
   *  a pre-canon (legacy) character the ordinary generator cannot ground. */
  anchorGuardActive: boolean;
}

/**
 * Decide which (if any) readiness guard should block image generation.
 *
 * Mirrors the ordinary generation path's server rule (Polish Phase 5.8):
 * ``POST /{id}/image-generator/generate`` with ``include_character`` requires
 * a CharacterIdentityCanon with content (``has_any_canon_content``) and
 * consults NO legacy identity source — a character is grounded on its canon
 * or refused with 409 "Character canon incomplete". ``has_identity_canon``
 * is the server's own signal that the canon holds a generated face, so a
 * character is offered generation only when it is established
 * (``visual_locked``) AND has that canon.
 *
 * The legacy ``identity_anchor_json`` used to count as a substitute here.
 * It never did on the server for this route, so the frontend offered a
 * Generate button the backend deterministically rejected. It no longer
 * counts: the frontend is now at least as strict as the backend.
 */
export function computeGeneratorGuards(
  selectedCharacterId: number | null,
  selectedChar: Pick<Character, 'visual_locked' | 'has_identity_canon'> | null,
): GeneratorGuards {
  const isCharacterLocked = selectedChar?.visual_locked ?? false;
  const hasIdentityCanon = selectedChar?.has_identity_canon ?? false;

  const lockedGuardActive = selectedCharacterId !== null && !isCharacterLocked;
  const anchorGuardActive =
    selectedCharacterId !== null && isCharacterLocked && !hasIdentityCanon;

  return { lockedGuardActive, anchorGuardActive };
}
