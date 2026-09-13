import { describe, it, expect } from 'vitest';
import type { IdentitySpec } from '../types';
import {
  SHAVED,
  characterFieldsFromSpec,
  hairDetailApplies,
  isInterviewComplete,
  withHairLength,
} from '../interviewRules';

function spec(overrides: Partial<IdentitySpec> = {}): IdentitySpec {
  return {
    style: '',
    gender: 'female',
    age_band: '26-35',
    species: 'human',
    species_tells: [],
    identity: { hair_color: 'Auburn', hair_length: 'Long', eye_color: 'Green', skin_tone: 'Fair', face_features: [] },
    build: { body_type: '', height_band: '' },
    marks_accessories: { items: [] },
    wardrobe: { outfit_type: '', primary_color: '', secondary_color: '', footwear: '', accessory: '', notes: '' },
    extra_notes: '',
    hair_style: 'slicked_back',
    hair_texture: 'wavy',
    ...overrides,
  };
}

describe('interview completeness (C2 / C11)', () => {
  it('is complete only when gender and age band are answered', () => {
    expect(isInterviewComplete(spec())).toBe(true);
    expect(isInterviewComplete(spec({ gender: '' }))).toBe(false);
    expect(isInterviewComplete(spec({ age_band: '' }))).toBe(false);
    expect(isInterviewComplete(spec({ gender: '   ' }))).toBe(false);
  });

  it('is never complete for a missing spec', () => {
    expect(isInterviewComplete(null)).toBe(false);
    expect(isInterviewComplete(undefined)).toBe(false);
  });

  it('does not require any geometry answer — the Interview is optional past Q1', () => {
    expect(isInterviewComplete({ gender: 'male', age_band: '36-50' })).toBe(true);
  });
});

describe('hair length rule (C9)', () => {
  it('clears style and texture when the length becomes Shaved', () => {
    const next = withHairLength(spec(), SHAVED);
    expect(next.identity.hair_length).toBe('Shaved');
    expect(next.hair_style).toBeUndefined();
    expect(next.hair_texture).toBeUndefined();
    expect(hairDetailApplies(next)).toBe(false);
  });

  it('leaves style and texture alone for every other length', () => {
    for (const length of ['Short', 'Medium', 'Long']) {
      const next = withHairLength(spec(), length);
      expect(next.identity.hair_length).toBe(length);
      expect(next.hair_style).toBe('slicked_back');
      expect(next.hair_texture).toBe('wavy');
      expect(hairDetailApplies(next)).toBe(true);
    }
  });

  it('clearing the length (toggle off) keeps whatever was there', () => {
    const next = withHairLength(spec(), '');
    expect(next.identity.hair_length).toBe('');
    expect(next.hair_style).toBe('slicked_back');
  });

  it('never mutates the input spec', () => {
    const before = spec();
    withHairLength(before, SHAVED);
    expect(before.hair_style).toBe('slicked_back');
    expect(before.identity.hair_length).toBe('Long');
  });
});

describe('character display fields come from the Interview (C8)', () => {
  it('stores the species LABEL and the age band', () => {
    expect(characterFieldsFromSpec(spec({ species: 'vampire', age_band: '50+' }))).toEqual({
      species: 'Vampire',
      age: '50+',
    });
  });

  it('falls back to the raw value for an unknown species and omits an empty age', () => {
    expect(characterFieldsFromSpec(spec({ species: 'dryad' as never, age_band: '' }))).toEqual({
      species: 'dryad',
      age: undefined,
    });
  });
});
