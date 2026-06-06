import { describe, it, expect } from 'vitest';
import { isAdultAdjacent } from '../adultContent';

describe('isAdultAdjacent', () => {
  it('triggers on a swimwear prompt ("yellow bikini")', () => {
    expect(isAdultAdjacent('a woman in a yellow bikini')).toBe(true);
  });

  it('triggers on multi-word phrases like "bedroom scene"', () => {
    expect(isAdultAdjacent('intimate bedroom scene at night')).toBe(true);
  });

  it('is case-insensitive', () => {
    expect(isAdultAdjacent('LINGERIE photoshoot')).toBe(true);
  });

  it('does not trigger on a normal fantasy/café/meadow prompt', () => {
    expect(isAdultAdjacent('a knight in a sunny meadow near a café')).toBe(false);
  });

  it('does not false-positive on word fragments (e.g. "brave" contains "bra")', () => {
    expect(isAdultAdjacent('a brave adventurer')).toBe(false);
  });

  it('returns false for empty input', () => {
    expect(isAdultAdjacent('')).toBe(false);
    expect(isAdultAdjacent('   ')).toBe(false);
  });

  it('covers the full term list', () => {
    const terms = [
      'bikini', 'swimsuit', 'swimwear', 'lingerie', 'underwear', 'bra',
      'panties', 'topless', 'nude', 'naked', 'erotic', 'adult',
      'bedroom scene', 'poolside', 'beachwear',
    ];
    for (const term of terms) {
      expect(isAdultAdjacent(`scene with ${term} here`)).toBe(true);
    }
  });
});
