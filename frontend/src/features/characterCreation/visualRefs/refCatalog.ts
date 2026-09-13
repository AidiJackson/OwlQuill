// The visual-reference catalog — which Interview fields are shown as
// explanatory picture cards, and with what.
//
// Polish Phase 3A (face shape) and 3C (the other five approved geometry
// fields). DATA ONLY. The options for every category are the SAME constants
// the Interview already uses (shared/types.ts) — the catalog adds
// presentation (aspect, an optional one-line hint per value) and never a
// second vocabulary. A category that is not listed here keeps its chip row.
//
// The reference images are explanatory UI assets and nothing else: they are
// not generation references, not canon evidence, not identity anchors, and
// the chosen EXAMPLE SET (feminine / masculine) is a viewing preference that
// is never written to the spec, the DNA, the character, or any request.
// Until a category's images exist the picker shows its neutral tile, so the
// whole Interview can be walked before a single asset is made.
import {
  CHEEKBONE_TYPES,
  EYE_SHAPES,
  FACE_SHAPES,
  JAW_TYPES,
  LIP_TYPES,
  NOSE_TYPES,
} from '../shared/types';

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

/**
 * The IdentitySpec fields that render as picture cards. Each is also the
 * asset folder name: `public/creator-refs/<key>/<set>/<value>.webp`.
 */
export type VisualCategoryKey =
  | 'face_shape'
  | 'jaw_type'
  | 'cheekbone_type'
  | 'eye_shape'
  | 'nose_type'
  | 'lip_type';

export interface VisualCategory<V extends string = string> {
  /** The IdentitySpec field and the asset folder name. */
  key: VisualCategoryKey;
  /** The Interview's own option list — never a copy. */
  options: readonly { label: string; value: V }[];
  aspect: RefAspect;
  /** One short physical cue per value, shown under the label. Optional. */
  hints?: Partial<Record<V, string>>;
}

// Hints are three words at most: cards are ~104px wide (83px of text at
// 10px Inter) and a hint must stay on one line or the two card rows stop
// matching in height.

export type FaceShapeValue = (typeof FACE_SHAPES)[number]['value'];
export type JawValue = (typeof JAW_TYPES)[number]['value'];
export type CheekboneValue = (typeof CHEEKBONE_TYPES)[number]['value'];
export type EyeShapeValue = (typeof EYE_SHAPES)[number]['value'];
export type NoseValue = (typeof NOSE_TYPES)[number]['value'];
export type LipValue = (typeof LIP_TYPES)[number]['value'];

// Face shape is portrait (4:5): the whole head fills the card. Every other
// category is a feature crop, landscape (3:2): the lower face for jaw and
// cheekbones, the eyes, the nose or the mouth — the card shows the part
// being asked about, not the whole head, and stays short.
export const FACE_SHAPE_CATEGORY: VisualCategory<FaceShapeValue> = {
  key: 'face_shape',
  options: FACE_SHAPES,
  aspect: '4 / 5',
  hints: {
    oval: 'Gently curved',
    round: 'Soft, full cheeks',
    square: 'Broad, flat jaw',
    angular: 'Sharper planes',
    long: 'Longer than wide',
  },
};

export const JAW_CATEGORY: VisualCategory<JawValue> = {
  key: 'jaw_type',
  options: JAW_TYPES,
  aspect: '3 / 2',
  hints: {
    soft: 'Gently rounded',
    narrow: 'Tapers inward',
    square: 'Wide and flat',
    sharp: 'Crisp, defined',
  },
};

export const CHEEKBONE_CATEGORY: VisualCategory<CheekboneValue> = {
  key: 'cheekbone_type',
  options: CHEEKBONE_TYPES,
  aspect: '3 / 2',
  hints: {
    subtle: 'Barely raised',
    high: 'Set up high',
    wide: 'Set far apart',
  },
};

export const EYE_SHAPE_CATEGORY: VisualCategory<EyeShapeValue> = {
  key: 'eye_shape',
  options: EYE_SHAPES,
  aspect: '3 / 2',
  hints: {
    almond: 'Tapered ends',
    round: 'Open, circular',
    narrow: 'Slim opening',
    deep_set: 'Under the brow',
  },
};

export const NOSE_CATEGORY: VisualCategory<NoseValue> = {
  key: 'nose_type',
  options: NOSE_TYPES,
  aspect: '3 / 2',
  hints: {
    straight: 'Even bridge',
    narrow: 'Slim bridge',
    broad: 'Wide bridge',
    hooked: 'Curves down',
    roman: 'Raised bridge',
    upturned: 'Tip turns up',
  },
};

export const LIP_CATEGORY: VisualCategory<LipValue> = {
  key: 'lip_type',
  options: LIP_TYPES,
  aspect: '3 / 2',
  hints: {
    thin: 'Slim, fine',
    balanced: 'Evenly matched',
    full: 'Fuller, plump',
    cupid_bow: 'Peaked top lip',
  },
};

/** Every category that renders as picture cards, in Interview order. */
export const VISUAL_CATEGORIES = [
  FACE_SHAPE_CATEGORY,
  JAW_CATEGORY,
  CHEEKBONE_CATEGORY,
  EYE_SHAPE_CATEGORY,
  NOSE_CATEGORY,
  LIP_CATEGORY,
] as const;
