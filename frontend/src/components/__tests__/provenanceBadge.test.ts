import { describe, it, expect } from 'vitest';
import { BADGES } from '../ProvenanceBadge';

/**
 * The badge vocabulary, pinned as data.
 *
 * Three user-facing states. The rule that matters most is the one that is
 * absent: there is no path by which a post Ficshon did not observe can end up
 * showing "Written in Ficshon".
 *
 * The table comes from the component itself. The icon is a separate field
 * because it is `aria-hidden` in the markup — "writing hand Written in
 * Ficshon" is noise read aloud — so what a sighted reader sees is the two
 * joined, and what a screen reader hears is the label alone.
 */
const labelFor = (provenance?: string | null): string | null => {
  const badge = provenance ? BADGES[provenance] : undefined;
  return badge ? `${badge.icon} ${badge.label}` : null;
};

/** What a screen reader gets: no emoji. */
const spokenLabelFor = (provenance?: string | null): string | null =>
  (provenance ? BADGES[provenance]?.label : undefined) ?? null;

describe('provenance badge vocabulary', () => {
  it('labels content composed in Ficshon', () => {
    expect(labelFor('user_written')).toBe('✍️ Written in Ficshon');
  });

  it('labels content assisted by Ficshon AI', () => {
    expect(labelFor('ai_assisted')).toBe('✨ AI Assisted');
  });

  it('labels content created elsewhere', () => {
    expect(labelFor('external')).toBe('📄 Created elsewhere');
  });

  it('shows legacy rows as created elsewhere, not as unbadged', () => {
    // Pre-provenance posts were deliberately never backfilled. They still say
    // something true: Ficshon did not watch them being created.
    expect(labelFor('unknown')).toBe('📄 Created elsewhere');
  });

  it('makes no claim about which kind of elsewhere', () => {
    // A Notepad paste and an outside AI are indistinguishable to us and must
    // therefore read identically. "Created elsewhere" is not an AI accusation.
    expect(labelFor('external')).not.toMatch(/AI/);
    expect(BADGES.external.title).not.toMatch(/\bAI-generated\b/);
  });

  it('says the same thing to a screen reader, minus the decoration', () => {
    expect(spokenLabelFor('user_written')).toBe('Written in Ficshon');
    expect(spokenLabelFor('ai_assisted')).toBe('AI Assisted');
    expect(spokenLabelFor('external')).toBe('Created elsewhere');
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
      expect(spokenLabelFor(state)).not.toBe('Written in Ficshon');
    }
  });
});
