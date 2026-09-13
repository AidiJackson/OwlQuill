import { describe, it, expect } from 'vitest';
import { FACE_SHAPES } from '../../shared/types';
import {
  DEFAULT_EXAMPLE_SET,
  EXAMPLE_SETS,
  FACE_SHAPE_CATEGORY,
  VISUAL_CATEGORIES,
  exampleSetForGender,
  isExampleSet,
} from '../refCatalog';
import { refAssetUrl } from '../refAssetUrl';
import { resolveExampleSet } from '../useExampleSet';

describe('catalog derives from the Interview vocabulary (no second source of truth)', () => {
  it('face shape options ARE the Interview constants', () => {
    expect(FACE_SHAPE_CATEGORY.options).toBe(FACE_SHAPES);
    expect(FACE_SHAPE_CATEGORY.options.map((o) => o.value)).toEqual(['oval', 'round', 'square', 'angular', 'long']);
  });

  it('every hint names a real option and no option is orphaned', () => {
    const values = new Set(FACE_SHAPE_CATEGORY.options.map((o) => o.value));
    for (const k of Object.keys(FACE_SHAPE_CATEGORY.hints ?? {})) expect(values.has(k as never)).toBe(true);
    for (const v of values) expect(FACE_SHAPE_CATEGORY.hints?.[v]).toBeTruthy();
  });

  it('only face shape is a visual category in Phase 3A', () => {
    expect(VISUAL_CATEGORIES.map((c) => c.key)).toEqual(['face_shape']);
  });
});

describe('asset paths', () => {
  it('resolve predictably from category, set and the stored value', () => {
    for (const set of EXAMPLE_SETS.map((s) => s.value)) {
      for (const { value } of FACE_SHAPES) {
        expect(refAssetUrl('face_shape', set, value)).toBe(`/creator-refs/face_shape/${set}/${value}.webp`);
      }
    }
    expect(refAssetUrl('face_shape', 'feminine', 'oval')).toBe('/creator-refs/face_shape/feminine/oval.webp');
    expect(refAssetUrl('face_shape', 'masculine', 'long')).toBe('/creator-refs/face_shape/masculine/long.webp');
  });
});

describe('example set resolution (UI preference only)', () => {
  it('suggests from gender, never from anything else', () => {
    expect(exampleSetForGender('female')).toBe('feminine');
    expect(exampleSetForGender('male')).toBe('masculine');
    expect(exampleSetForGender('other')).toBeNull();
    expect(exampleSetForGender('')).toBeNull();
    expect(exampleSetForGender(undefined)).toBeNull();
  });

  it('a deliberate choice wins over gender; otherwise gender; otherwise the default', () => {
    expect(resolveExampleSet('masculine', 'female')).toBe('masculine');
    expect(resolveExampleSet(null, 'female')).toBe('feminine');
    expect(resolveExampleSet(null, 'male')).toBe('masculine');
    expect(resolveExampleSet(null, 'other')).toBe(DEFAULT_EXAMPLE_SET);
    expect(resolveExampleSet(null, undefined)).toBe(DEFAULT_EXAMPLE_SET);
  });

  it('validates stored values', () => {
    expect(isExampleSet('feminine')).toBe(true);
    expect(isExampleSet('masculine')).toBe(true);
    expect(isExampleSet('neutral')).toBe(false);
    expect(isExampleSet(null)).toBe(false);
  });
});
