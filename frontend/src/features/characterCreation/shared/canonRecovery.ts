/**
 * S24AQ — v2 pack timeout recovery.
 *
 * A full v2 canon generation runs 13 sequential, grounded image generations and
 * can take several minutes. The backend commits each slot as it generates, so
 * even when an edge/proxy timeout severs the HTTP response, the canon ends up
 * fully populated. These pure helpers let the UI re-read the canon and, if every
 * slot is present, reconstruct the pack instead of showing a false failure —
 * with no further provider calls or spend.
 */

import type {
  CharacterCanonRead,
  FaceCanonData,
  BodyCanonData,
  V2PackCard,
  V2PackResponse,
} from './types';

/** The 13 v2 canon slots, in review-grid order, mapped to their canon fields. */
export const V2_RECOVERY_SLOTS: {
  slot: string;
  section: 'face' | 'body';
  field: string;
}[] = [
  { slot: 'face_front', section: 'face', field: 'face_front_image_url' },
  { slot: 'face_left_3q', section: 'face', field: 'face_left_3q_image_url' },
  { slot: 'face_right_3q', section: 'face', field: 'face_right_3q_image_url' },
  { slot: 'face_profile', section: 'face', field: 'face_profile_image_url' },
  { slot: 'face_expression', section: 'face', field: 'face_expression_image_url' },
  { slot: 'body_front', section: 'body', field: 'body_front_image_url' },
  { slot: 'body_left', section: 'body', field: 'body_left_image_url' },
  { slot: 'body_right', section: 'body', field: 'body_right_image_url' },
  { slot: 'body_back', section: 'body', field: 'body_back_image_url' },
  { slot: 'torso_front', section: 'body', field: 'torso_front_image_url' },
  { slot: 'torso_side', section: 'body', field: 'torso_side_image_url' },
  { slot: 'standing_relaxed', section: 'body', field: 'standing_relaxed_image_url' },
  { slot: 'seated_relaxed', section: 'body', field: 'seated_relaxed_image_url' },
];

function slotUrl(
  canon: CharacterCanonRead | null | undefined,
  section: 'face' | 'body',
  field: string,
): string | null {
  if (!canon) return null;
  const source: FaceCanonData | BodyCanonData | null | undefined =
    section === 'face' ? canon.face_canon : canon.body_canon;
  const value = source ? source[field] : null;
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

/** True only when all 13 v2 canon slots hold a non-empty image URL. */
export function isV2PackComplete(
  canon: CharacterCanonRead | null | undefined,
): boolean {
  return V2_RECOVERY_SLOTS.every((s) => slotUrl(canon, s.section, s.field) !== null);
}

/**
 * Reconstruct a V2PackResponse from a fully-populated canon, or return null if
 * any slot is still missing. The synthetic pack carries no spend (recovery is
 * read-only) and is marked clean since every slot resolved.
 */
export function buildPackFromCanon(
  canon: CharacterCanonRead | null | undefined,
): V2PackResponse | null {
  if (!isV2PackComplete(canon)) return null;

  const cards: V2PackCard[] = V2_RECOVERY_SLOTS.map((s) => ({
    slot: s.slot,
    section: s.section,
    role: s.slot,
    url: slotUrl(canon, s.section, s.field),
    status: 'generated',
  }));

  return {
    pack_id: `recovered-canon-${canon?.character_id ?? 'unknown'}`,
    dry_run: false,
    cards,
    marks: [],
    total_spend: 0,
    image_count: cards.length,
    regenerations: [],
    openai_fallback: [],
    gate_failed: [],
    errors: [],
    clean_pass: true,
  };
}
