// What the current board will actually ask for — derived, never chosen.
//
// Phase 2 deliberately has no "mode" control. A mode selector would be a second
// source of truth that can contradict the cards: picking "Canon Card" with no
// pose reference loaded has no good answer, and every answer is a surprise. The
// roles already determine the pass completely, so this module reads them back
// and says what is about to happen. It is feedback, not input — nothing here
// reaches the server, and the board is unchanged by what it reports.
//
// Mirrors the backend derivation in manual_references::_construction_lines. The
// two must agree, or the banner promises something the provider was not told;
// the tests pin both against the same table of cases.
//
// Like its backend counterpart, this reads MEMBERSHIP only — never how many
// cards there are or which position they sit in. The board offers four today
// and this file would behave identically at eight.
import {
  isFeatureRole,
  roleLabel,
  type AdminCreatorRole,
} from '@/features/adminCreator/referenceRoles';
import type { ReferenceSlots } from './referenceSlots';

/** Which of the recognised passes a board describes. */
export type PassKind = 'empty' | 'build' | 'refine' | 'pose' | 'two_person' | 'scene';

export interface PassIntent {
  kind: PassKind;
  /** Short headline: what this pass does. */
  headline: string;
  /** The specifics — which features, which person. Empty when there are none. */
  detail: string;
}

function joinLabels(roles: readonly AdminCreatorRole[]): string {
  const labels = roles.map((r) => roleLabel(r).toLowerCase());
  if (labels.length <= 1) return labels.join('');
  return `${labels.slice(0, -1).join(', ')} and ${labels[labels.length - 1]}`;
}

/**
 * Describe what generating from this board will do.
 *
 * The order of the checks is the derivation, and it matches the backend's:
 * feature roles decide FIRST, and whether Person A is present decides whether
 * they build someone new or edit someone who already exists. Character 2 does
 * not trigger refinement — Person B is a second person in a scene, not the
 * subject being constructed.
 */
export function derivePassIntent(slots: ReferenceSlots): PassIntent {
  const roles = slots.filter((s): s is NonNullable<typeof s> => s !== null).map((s) => s.role);
  if (roles.length === 0) {
    return { kind: 'empty', headline: 'Nothing selected yet', detail: '' };
  }

  // Deduped so three hair cards read as "hair", not "hair, hair and hair",
  // while still preserving the order the founder assembled them in.
  const features = roles.filter((r, i) => isFeatureRole(r) && roles.indexOf(r) === i);
  const hasPersonA = roles.includes('character_1');
  const hasPersonB = roles.includes('character_2');
  const hasPose = roles.includes('pose_composition');

  if (features.length > 0 && !hasPersonA) {
    return {
      kind: 'build',
      headline: 'Building a new face',
      detail: `Combining ${joinLabels(features)} into one new person.`,
    };
  }

  if (features.length > 0) {
    return {
      kind: 'refine',
      headline: 'Refining Person A',
      detail: `Changing ${joinLabels(features)} — the face and likeness stay the same.`,
    };
  }

  if (hasPersonA && hasPersonB) {
    return {
      kind: 'two_person',
      headline: 'Scene with two people',
      detail: 'Person A and Person B stay separate identities.',
    };
  }

  if (hasPersonA && hasPose) {
    return {
      kind: 'pose',
      headline: 'Posing Person A',
      detail: 'New angle or framing of the same person.',
    };
  }

  return {
    kind: 'scene',
    headline: 'Scene',
    detail: 'Generating from the references as supplied.',
  };
}
