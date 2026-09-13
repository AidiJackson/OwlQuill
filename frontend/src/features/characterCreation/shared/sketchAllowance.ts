// Sketch allowance — pure helpers for what the creator is told (Polish Phase 2, C10).
//
// The server is the only authority on the numbers; nothing here counts,
// decrements or remembers. This module turns the server's allowance into
// copy, recognises the server's exhausted refusal, and formats the wait.
import type { SketchAllowance } from './types';
import { ApiError } from './api';

export const SKETCH_ALLOWANCE_EXHAUSTED = 'sketch_allowance_exhausted';

/** The allowance carried by an exhausted-allowance refusal, or null for any other error. */
export function allowanceFromError(err: unknown): SketchAllowance | null {
  if (!(err instanceof ApiError) || err.status !== 429) return null;
  const body = err.body as { error?: string; allowance?: SketchAllowance } | null;
  if (!body || body.error !== SKETCH_ALLOWANCE_EXHAUSTED || !body.allowance) return null;
  return body.allowance;
}

/**
 * How long until `nextIso`, in plain words. Never a calendar-day promise: the
 * window is rolling, so the honest statement is "another attempt in about…".
 */
export function formatWait(nextIso: string | null | undefined, now: Date = new Date()): string | null {
  if (!nextIso) return null;
  const next = new Date(nextIso);
  if (Number.isNaN(next.getTime())) return null;
  const minutes = Math.ceil((next.getTime() - now.getTime()) / 60_000);
  if (minutes <= 1) return 'in a moment';
  if (minutes < 60) return `in about ${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  if (hours <= 1) return 'in about an hour';
  return `in about ${hours} hours`;
}

/** The one-line allowance status shown above the Generate button. */
export function allowanceCopy(a: SketchAllowance | null, now: Date = new Date()): string {
  if (!a) return '';
  const noun = (n: number) => (n === 1 ? 'sketch attempt' : 'sketch attempts');
  if (a.remaining <= 0) {
    const wait = formatWait(a.next_available_at, now);
    return `You've used your ${a.limit} ${noun(a.limit)} for now${wait ? ` — another opens ${wait}` : ''}.`;
  }
  if (a.used === 0) return `${a.remaining} ${noun(a.remaining)} available`;
  return `${a.remaining} ${noun(a.remaining)} remaining`;
}
