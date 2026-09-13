// The visual-reference catalog — which Interview fields are shown as
// explanatory picture cards, and with what.
//
// Polish Phase 3A. DATA ONLY. The options for every category are the SAME
// constants the Interview already uses (shared/types.ts) — the catalog adds
// presentation (aspect, an optional one-line hint per value) and never a
// second vocabulary. A category that is not listed here keeps its chip row.
//
// The reference images are explanatory UI assets and nothing else: they are
// not generation references, not canon evidence, not identity anchors, and
// the chosen EXAMPLE SET (feminine / masculine) is a viewing preference that
// is never written to the spec, the DNA, the character, or any request.
import { FACE_SHAPES } from '../shared/types';

/** Which explanatory set of example images is shown. Presentation only. */
export type ExampleSet = 'feminine' | 'masculine';
export const EXAMPLE_SETS: readonly { value: ExampleSet; label: string }[] = [
  { value: 'feminine', label: 'Feminine' },
  { value: 'masculine', label: 'Masculine' },
];
export const DEFAULT_EXAMPLE_SET: ExampleSet = 'feminine';

/** localStorage key for a deliberately chosen example set. UI preference only. */
export const EXAMPLE_SET_STORAGE_KEY = 'ficshon.creator.exampleSet';

export function isExampleSet(v: unknown): v is ExampleSet {
  return v === 'feminine' || v === 'masculine';
}

/**
 * The example set a character's gender suggests, or null when it suggests
 * none (non-binary / unset). A suggestion only — a manual choice wins.
 */
export function exampleSetForGender(gender: string | undefined | null): ExampleSet | null {
  if (gender === 'female') return 'feminine';
  if (gender === 'male') return 'masculine';
  return null;
}

/** Image aspect ratios a category may use, as CSS `aspect-ratio` values. */
export type RefAspect = '4 / 5' | '3 / 2';

export interface VisualCategory<V extends string = string> {
  /** The IdentitySpec field and the asset folder name. */
  key: 'face_shape';
  /** The Interview's own option list — never a copy. */
  options: readonly { label: string; value: V }[];
  aspect: RefAspect;
  /** One short physical cue per value, shown under the label. Optional. */
  hints?: Partial<Record<V, string>>;
}

export type FaceShapeValue = (typeof FACE_SHAPES)[number]['value'];

export const FACE_SHAPE_CATEGORY: VisualCategory<FaceShapeValue> = {
  key: 'face_shape',
  options: FACE_SHAPES,
  aspect: '4 / 5',
  // Three words at most: cards are ~104px wide and a hint must stay one line.
  hints: {
    oval: 'Gently curved',
    round: 'Soft, full cheeks',
    square: 'Broad, straight sides',
    angular: 'Sharper planes',
    long: 'Longer than wide',
  },
};

/** Every category that currently renders as picture cards. */
export const VISUAL_CATEGORIES = [FACE_SHAPE_CATEGORY] as const;
