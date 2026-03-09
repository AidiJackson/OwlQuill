/**
 * B15.6: Pure session-guard helpers for the character creation flow.
 *
 * Keeping logic here (separate from React) makes it testable without a DOM
 * and lets both CharacterCreationFlow and StepSketch import a single source
 * of truth for session validation decisions.
 */

// ── Types ────────────────────────────────────────────────────────────

export type RecoveryAction =
  | 'none'
  | 'bfcache-mismatch:reset-to-step-0'
  | 'bfcache-restore:sketch-cleared';

export interface SessionCheckResult {
  /** True only when route characterId and state characterId diverge. */
  mismatch: boolean;
  recoveryAction: RecoveryAction;
}

// ── checkCreationSession ─────────────────────────────────────────────

/**
 * Decide what (if anything) needs to happen when the browser fires a
 * `pageshow` event (which includes bfcache forward/back restores).
 *
 * @param persisted   - `PageTransitionEvent.persisted`; true only on bfcache restore
 * @param stateCharacterId - the characterId currently in React state
 * @param routeCharacterId - characterId parsed from the URL query param (may be null)
 * @param step        - current creation step index (0-based)
 */
export function checkCreationSession({
  persisted,
  stateCharacterId,
  routeCharacterId,
  step,
}: {
  persisted: boolean;
  stateCharacterId: number | null;
  routeCharacterId: number | null;
  step: number;
}): SessionCheckResult {
  // Non-bfcache load: nothing to do
  if (!persisted) {
    return { mismatch: false, recoveryAction: 'none' };
  }

  // Bfcache restore: check for route/state id mismatch
  if (
    routeCharacterId !== null &&
    stateCharacterId !== null &&
    routeCharacterId !== stateCharacterId
  ) {
    return { mismatch: true, recoveryAction: 'bfcache-mismatch:reset-to-step-0' };
  }

  // Bfcache restore on the sketch step: clear stale sketch state
  if (step === 2) {
    return { mismatch: false, recoveryAction: 'bfcache-restore:sketch-cleared' };
  }

  // Bfcache restore on any other step: no sketch to clear
  return { mismatch: false, recoveryAction: 'none' };
}

// ── isSketchBlocked ──────────────────────────────────────────────────

/**
 * Returns true when characterId no longer matches the flow's authoritative
 * active creation character, meaning sketch generate/refine must be blocked.
 *
 * In normal operation this is always false — it guards against edge-case
 * prop drift that should be caught by the key={nonce} remount mechanism
 * in CharacterCreationFlow before it ever reaches StepSketch.
 */
export function isSketchBlocked({
  characterId,
  activeCreationCharacterId,
}: {
  characterId: number;
  activeCreationCharacterId: number | null | undefined;
}): boolean {
  // When undefined/null the flow hasn't resolved an active id yet — treat
  // as unblocked so the normal "Generate Sketch" prompt is shown immediately.
  if (activeCreationCharacterId == null) return false;
  return characterId !== activeCreationCharacterId;
}
