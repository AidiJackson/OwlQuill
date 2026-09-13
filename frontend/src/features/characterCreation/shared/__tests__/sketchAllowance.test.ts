import { describe, it, expect } from 'vitest';
import { ApiError } from '../api';
import { allowanceCopy, allowanceFromError, formatWait } from '../sketchAllowance';
import type { SketchAllowance } from '../types';

function a(over: Partial<SketchAllowance> = {}): SketchAllowance {
  return { limit: 3, used: 0, remaining: 3, allowed: true, window_hours: 24, next_available_at: null, ...over };
}

describe('allowance copy (C10)', () => {
  it('states what is available, then what remains, then that it is spent', () => {
    expect(allowanceCopy(a())).toBe('3 sketch attempts available');
    expect(allowanceCopy(a({ used: 1, remaining: 2 }))).toBe('2 sketch attempts remaining');
    expect(allowanceCopy(a({ used: 2, remaining: 1 }))).toBe('1 sketch attempt remaining');
    expect(allowanceCopy(a({ used: 3, remaining: 0, allowed: false }))).toBe(
      "You've used your 3 sketch attempts for now.",
    );
  });

  it('never promises a calendar reset', () => {
    const now = new Date('2026-09-13T12:00:00Z');
    const text = allowanceCopy(
      a({ used: 3, remaining: 0, allowed: false, next_available_at: '2026-09-13T17:30:00Z' }),
      now,
    );
    expect(text).toBe("You've used your 3 sketch attempts for now — another opens in about 6 hours.");
    expect(text).not.toMatch(/midnight|tomorrow|reset/i);
  });

  it('is empty until the server has answered', () => {
    expect(allowanceCopy(null)).toBe('');
  });
});

describe('formatWait', () => {
  const now = new Date('2026-09-13T12:00:00Z');
  it('rounds to minutes, then hours', () => {
    expect(formatWait('2026-09-13T12:00:30Z', now)).toBe('in a moment');
    expect(formatWait('2026-09-13T12:25:00Z', now)).toBe('in about 25 minutes');
    expect(formatWait('2026-09-13T12:59:00Z', now)).toBe('in about 59 minutes');
    expect(formatWait('2026-09-13T13:05:00Z', now)).toBe('in about an hour');
    expect(formatWait('2026-09-14T11:40:00Z', now)).toBe('in about 24 hours');
  });
  it('is null for nothing or garbage', () => {
    expect(formatWait(null, now)).toBeNull();
    expect(formatWait('not a date', now)).toBeNull();
  });
});

describe('allowanceFromError', () => {
  it("recognises the server's exhausted refusal and nothing else", () => {
    const spent = a({ used: 3, remaining: 0, allowed: false });
    expect(allowanceFromError(new ApiError('spent', 429, { error: 'sketch_allowance_exhausted', allowance: spent }))).toEqual(spent);
    expect(allowanceFromError(new ApiError('other 429', 429, { error: 'identity_pack_rate_limited' }))).toBeNull();
    expect(allowanceFromError(new ApiError('down', 503, { detail: 'down' }))).toBeNull();
    expect(allowanceFromError(new Error('network'))).toBeNull();
  });
});
