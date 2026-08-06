import { describe, it, expect } from 'vitest';

/**
 * The badge vocabulary, pinned as data.
 *
 * Three user-facing states. The rule that matters most is the one that is
 * absent: there is no path by which a post Ficshon did not observe can end up
 * showing "Written in Ficshon".
 */
const BADGE_LABELS: Record<string, string> = {
  user_written: '✍️ Written in Ficshon',
  ai_assisted: '✨ AI Assisted',
  external: '📄 Written elsewhere',
  unknown: '📄 Written elsewhere',
};

function labelFor(provenance?: string | null): string | null {
  return (provenance ? BADGE_LABELS[provenance] : undefined) ?? null;
}

describe('provenance badge vocabulary', () => {
  it('labels content composed in Ficshon', () => {
    expect(labelFor('user_written')).toBe('✍️ Written in Ficshon');
  });

  it('labels content assisted by Ficshon AI', () => {
    expect(labelFor('ai_assisted')).toBe('✨ AI Assisted');
  });

  it('labels content written elsewhere', () => {
    expect(labelFor('external')).toBe('📄 Written elsewhere');
  });

  it('shows legacy rows as written elsewhere, not as unbadged', () => {
    // Pre-provenance posts were deliberately never backfilled. They still say
    // something true: Ficshon did not watch them being written.
    expect(labelFor('unknown')).toBe('📄 Written elsewhere');
  });

  it('makes no claim about which kind of elsewhere', () => {
    // A Notepad paste and an outside AI are indistinguishable to us and must
    // therefore read identically. "Written elsewhere" is not an AI accusation.
    expect(labelFor('external')).not.toMatch(/AI/);
  });

  it('renders nothing for an unrecognised state', () => {
    // A verdict the server ships before the client knows it shows no badge
    // rather than a wrong one.
    expect(labelFor('some_future_state')).toBeNull();
  });

  it('renders nothing when provenance is absent', () => {
    expect(labelFor(undefined)).toBeNull();
    expect(labelFor(null)).toBeNull();
  });

  it('never labels an unproven state as written in Ficshon', () => {
    for (const state of ['external', 'unknown', 'some_future_state']) {
      expect(labelFor(state)).not.toBe('✍️ Written in Ficshon');
    }
  });
});
