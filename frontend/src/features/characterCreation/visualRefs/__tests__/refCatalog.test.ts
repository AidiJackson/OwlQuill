import { describe, it, expect } from 'vitest';
import {
  CHEEKBONE_TYPES,
  EYE_SHAPES,
  FACE_SHAPES,
  JAW_TYPES,
  LIP_TYPES,
  NOSE_TYPES,
} from '../../shared/types';
import {
  CHEEKBONE_CATEGORY,
  DEFAULT_EXAMPLE_SET,
  EXAMPLE_SETS,
  EYE_SHAPE_CATEGORY,
  FACE_SHAPE_CATEGORY,
  JAW_CATEGORY,
  LIP_CATEGORY,
  NOSE_CATEGORY,
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

  it('the 3C categories ARE the Interview constants too', () => {
    expect(JAW_CATEGORY.options).toBe(JAW_TYPES);
    expect(CHEEKBONE_CATEGORY.options).toBe(CHEEKBONE_TYPES);
    expect(EYE_SHAPE_CATEGORY.options).toBe(EYE_SHAPES);
    expect(NOSE_CATEGORY.options).toBe(NOSE_TYPES);
    expect(LIP_CATEGORY.options).toBe(LIP_TYPES);
  });

  it('every hint names a real option and no option is orphaned, in every category', () => {
    for (const cat of VISUAL_CATEGORIES) {
      const values = new Set<string>(cat.options.map((o) => o.value));
      const hints = cat.hints as Record<string, string> | undefined;
      for (const k of Object.keys(hints ?? {})) expect(values.has(k)).toBe(true);
      for (const v of values) expect(hints?.[v]).toBeTruthy();
    }
  });

  it('hints stay short enough for one line on a ~104px card', () => {
    for (const cat of VISUAL_CATEGORIES) {
      for (const hint of Object.values(cat.hints ?? {})) {
        expect((hint as string).length).toBeLessThanOrEqual(17); // 'Soft, full cheeks' measures 76px of 83
        expect((hint as string).split(' ').length).toBeLessThanOrEqual(3);
      }
    }
  });

  it('the six approved geometry fields are visual categories, in Interview order, keyed by their spec field', () => {
    expect(VISUAL_CATEGORIES.map((c) => c.key)).toEqual([
      'face_shape', 'jaw_type', 'cheekbone_type', 'eye_shape', 'nose_type', 'lip_type',
    ]);
    // 26 values per example set: the 5 face shapes already shipped plus the
    // 21 that the 3C folders will hold (42 assets across both sets).
    expect(VISUAL_CATEGORIES.reduce((n, c) => n + c.options.length, 0)).toBe(26);
    expect(VISUAL_CATEGORIES.filter((c) => c.key !== 'face_shape').reduce((n, c) => n + c.options.length, 0)).toBe(21);
  });

  it('face shape is portrait; every feature crop (jaw and cheekbones included) is landscape', () => {
    expect(FACE_SHAPE_CATEGORY.aspect).toBe('4 / 5');
    for (const c of [JAW_CATEGORY, CHEEKBONE_CATEGORY, EYE_SHAPE_CATEGORY, NOSE_CATEGORY, LIP_CATEGORY]) expect(c.aspect).toBe('3 / 2');
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

  it('every category resolves to <key>/<set>/<value>.webp — the folder is the spec field, the file is the stored value', () => {
    for (const cat of VISUAL_CATEGORIES) {
      for (const set of EXAMPLE_SETS.map((s) => s.value)) {
        for (const { value } of cat.options) {
          expect(refAssetUrl(cat.key, set, value)).toBe(`/creator-refs/${cat.key}/${set}/${value}.webp`);
        }
      }
    }
    expect(refAssetUrl('eye_shape', 'feminine', 'deep_set')).toBe('/creator-refs/eye_shape/feminine/deep_set.webp');
    expect(refAssetUrl('lip_type', 'masculine', 'cupid_bow')).toBe('/creator-refs/lip_type/masculine/cupid_bow.webp');
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
