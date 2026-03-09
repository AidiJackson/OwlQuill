/**
 * B15.6: Session guard unit tests.
 *
 * Tests cover all four key scenarios from the B15.6 requirements:
 *  1. bfcache restore with stale prior character (route/state id mismatch)
 *  2. route id != active draft id (mismatch → reset-to-step-0)
 *  3. stale sketch state cleared on bfcache restore when on sketch step
 *  4. sketch actions blocked when characterId doesn't match activeCreationCharacterId
 */

import { describe, it, expect } from 'vitest';
import { checkCreationSession, isSketchBlocked } from '../sessionGuard';

// ── checkCreationSession ─────────────────────────────────────────────

describe('checkCreationSession', () => {
  // Non-bfcache navigations should never trigger any recovery
  it('returns none when persisted=false (normal navigation, not bfcache)', () => {
    const result = checkCreationSession({
      persisted: false,
      stateCharacterId: 5,
      routeCharacterId: 5,
      step: 2,
    });
    expect(result.recoveryAction).toBe('none');
    expect(result.mismatch).toBe(false);
  });

  it('returns none when persisted=false even if ids differ (not a bfcache event)', () => {
    const result = checkCreationSession({
      persisted: false,
      stateCharacterId: 5,
      routeCharacterId: 99,
      step: 2,
    });
    expect(result.recoveryAction).toBe('none');
    expect(result.mismatch).toBe(false);
  });

  // ── Scenario 1 & 2: bfcache restore + route/state id mismatch ───────

  it('detects mismatch when bfcache restores with a different route characterId', () => {
    // User visited /create?characterId=5, navigated away, pressed Back.
    // State still has id=5, but the URL now reads ?characterId=99 (manipulated or stale).
    const result = checkCreationSession({
      persisted: true,
      stateCharacterId: 5,
      routeCharacterId: 99,
      step: 2,
    });
    expect(result.mismatch).toBe(true);
    expect(result.recoveryAction).toBe('bfcache-mismatch:reset-to-step-0');
  });

  it('detects mismatch on any step, not just sketch step', () => {
    const result = checkCreationSession({
      persisted: true,
      stateCharacterId: 1,
      routeCharacterId: 2,
      step: 0,
    });
    expect(result.mismatch).toBe(true);
    expect(result.recoveryAction).toBe('bfcache-mismatch:reset-to-step-0');
  });

  // ── Scenario 3: bfcache restore on sketch step, same ids → sketch cleared ──

  it('clears sketch state on bfcache restore when on step 2 (sketch step)', () => {
    const result = checkCreationSession({
      persisted: true,
      stateCharacterId: 5,
      routeCharacterId: 5,
      step: 2,
    });
    expect(result.mismatch).toBe(false);
    expect(result.recoveryAction).toBe('bfcache-restore:sketch-cleared');
  });

  it('clears sketch state even when routeCharacterId is null (no route param)', () => {
    // Flow started without a ?characterId= param (fresh creation).
    const result = checkCreationSession({
      persisted: true,
      stateCharacterId: 7,
      routeCharacterId: null,
      step: 2,
    });
    expect(result.mismatch).toBe(false);
    expect(result.recoveryAction).toBe('bfcache-restore:sketch-cleared');
  });

  it('clears sketch state even when stateCharacterId is null', () => {
    // Draft not yet created, user pressed Back/Forward.
    const result = checkCreationSession({
      persisted: true,
      stateCharacterId: null,
      routeCharacterId: null,
      step: 2,
    });
    expect(result.mismatch).toBe(false);
    expect(result.recoveryAction).toBe('bfcache-restore:sketch-cleared');
  });

  it('returns none on bfcache restore on step 0 with matching ids', () => {
    const result = checkCreationSession({
      persisted: true,
      stateCharacterId: 5,
      routeCharacterId: 5,
      step: 0,
    });
    expect(result.mismatch).toBe(false);
    expect(result.recoveryAction).toBe('none');
  });

  it('returns none on bfcache restore on step 1 with matching ids', () => {
    const result = checkCreationSession({
      persisted: true,
      stateCharacterId: 5,
      routeCharacterId: null,
      step: 1,
    });
    expect(result.mismatch).toBe(false);
    expect(result.recoveryAction).toBe('none');
  });
});

// ── isSketchBlocked ──────────────────────────────────────────────────

describe('isSketchBlocked', () => {
  // ── Scenario 4: sketch actions blocked when ids mismatch ─────────────

  it('returns false when characterId matches activeCreationCharacterId', () => {
    expect(isSketchBlocked({ characterId: 5, activeCreationCharacterId: 5 })).toBe(false);
  });

  it('returns true when characterId differs from activeCreationCharacterId (mismatch)', () => {
    // This is the explicit mismatch guard — StepSketch must block generate/refine.
    expect(isSketchBlocked({ characterId: 5, activeCreationCharacterId: 99 })).toBe(true);
  });

  it('returns true for any non-equal pair', () => {
    expect(isSketchBlocked({ characterId: 1, activeCreationCharacterId: 2 })).toBe(true);
    expect(isSketchBlocked({ characterId: 100, activeCreationCharacterId: 101 })).toBe(true);
  });

  it('returns false when activeCreationCharacterId is undefined (not yet resolved)', () => {
    // When the flow hasn't passed an active id yet, treat as unblocked so the
    // normal "Generate Sketch" button is accessible immediately.
    expect(isSketchBlocked({ characterId: 5, activeCreationCharacterId: undefined })).toBe(false);
  });

  it('returns false when activeCreationCharacterId is null (not yet resolved)', () => {
    expect(isSketchBlocked({ characterId: 5, activeCreationCharacterId: null })).toBe(false);
  });

  it('returns false when ids match after a bfcache restore (nonce remount aligns them)', () => {
    // After a bfcache restore the nonce remounts StepSketch with the correct id.
    expect(isSketchBlocked({ characterId: 42, activeCreationCharacterId: 42 })).toBe(false);
  });
});
