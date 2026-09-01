// What each Admin Creator reference card REPRESENTS.
//
// Deliberately separate from features/images/referenceKinds::REFERENCE_ROLES.
// That list is the Image Generator's vocabulary and is frozen: adding a role
// there would put it in the /images picker and change a live surface. The
// backend enum is the union of both, so these values are all valid on the wire.
//
// The selector — not the card's position — decides a reference's authority.
// Card order still decides payload order, but a Clothing card in slot 1 is
// clothing authority, not identity authority.
//
// Why the two identity buckets exist
// ----------------------------------
// Every card marked "Character 1" is the SAME person; every card marked
// "Character 2" is the same second person. That grouping is the point: two
// photos of one face must read as one identity seen twice, not as two people,
// and two DIFFERENT faces must not be averaged into one. They are manual
// buckets — they are not inferred from position and they do not have to
// correspond to any Ficshon character record.
//
// Mirror of app/services/manual_references.py::ReferenceRole. The server
// re-validates every role; this module decides only what is OFFERED.

/** Values in the order the selector shows them. */
export const ADMIN_CREATOR_ROLES = [
  { value: 'unspecified', label: 'Unspecified' },
  { value: 'character_1', label: 'Character 1' },
  { value: 'character_2', label: 'Character 2' },
  { value: 'eyes', label: 'Eyes' },
  { value: 'nose', label: 'Nose' },
  { value: 'mouth_lips', label: 'Mouth / Lips' },
  // Face Shape / Jaw and Facial Hair are deliberately NOT offered. Both roles
  // still exist on the wire and in the compiler, but neither has an isolation
  // transform yet, and offering one would put a single un-isolated donor face
  // into a board the founder believes is isolated. The server refuses them
  // too. See reference_isolation::UNSUPPORTED_FEATURE_ROLES.
  { value: 'eyebrows', label: 'Eyebrows' },
  { value: 'hair', label: 'Hair' },
  { value: 'skin_complexion', label: 'Skin / Complexion' },
  { value: 'clothing', label: 'Clothing' },
  { value: 'environment', label: 'Environment / Scene' },
  { value: 'tattoo_mark', label: 'Tattoo / Permanent Mark' },
  { value: 'pose_composition', label: 'Pose / Composition' },
  { value: 'other', label: 'Other' },
] as const;

/**
 * How the selector groups the roles, as `<optgroup>` labels.
 *
 * Sixteen flat options is a scroll and a guess; four labelled groups is a
 * choice. The grouping is presentation only — the server sees the value, and
 * `ADMIN_CREATOR_ROLES` above remains the single list everything else reads.
 */
export const ROLE_GROUPS: readonly { label: string; roles: readonly AdminCreatorRole[] }[] = [
  { label: 'Identity', roles: ['character_1', 'character_2'] },
  {
    label: 'Facial features',
    roles: [
      'eyes',
      'nose',
      'mouth_lips',
      'eyebrows',
      'hair',
      'skin_complexion',
    ],
  },
  { label: 'Scene', roles: ['clothing', 'environment', 'tattoo_mark', 'pose_composition'] },
  { label: 'Neither', roles: ['unspecified', 'other'] },
];

export type AdminCreatorRole = (typeof ADMIN_CREATOR_ROLES)[number]['value'];

export const ADMIN_CREATOR_ROLE_VALUES: readonly AdminCreatorRole[] =
  ADMIN_CREATOR_ROLES.map((r) => r.value);

/** The role a card carries until the founder says otherwise. */
export const DEFAULT_ROLE: AdminCreatorRole = 'unspecified';

export function isAdminCreatorRole(value: string): value is AdminCreatorRole {
  return (ADMIN_CREATOR_ROLE_VALUES as readonly string[]).includes(value);
}

export function roleLabel(role: AdminCreatorRole): string {
  return ADMIN_CREATOR_ROLES.find((r) => r.value === role)?.label ?? 'Unspecified';
}

/** The two manual identity buckets. */
export const IDENTITY_ROLES: readonly AdminCreatorRole[] = ['character_1', 'character_2'];

export function isIdentityRole(role: AdminCreatorRole): boolean {
  return IDENTITY_ROLES.includes(role);
}

/**
 * The attribute-authority roles — evidence for one named feature, never for
 * identity.
 *
 * Mirror of manual_references::_FEATURE_ROLES. Membership is what the pass
 * derivation reads; no count, position or board size is involved anywhere, so
 * a larger reference budget later changes nothing in this module.
 */
export const FEATURE_ROLES: readonly AdminCreatorRole[] = [
  'eyes',
  'nose',
  'mouth_lips',
  'eyebrows',
  'hair',
  'skin_complexion',
];

export function isFeatureRole(role: AdminCreatorRole): boolean {
  return FEATURE_ROLES.includes(role);
}

/**
 * Short reminder shown under a populated card.
 *
 * Each says what the card IS authority for and, where it has bitten us, what it
 * is not: a rolled-sleeve appearance photo was the only evidence about Davies'
 * forearms on 2026-08-22 and the model dressed him accordingly.
 */
export const ROLE_HINTS: Record<AdminCreatorRole, string> = {
  unspecified: 'Sent with no explanation of what it is for.',
  character_1: 'This person. All Character 1 cards are the same individual.',
  character_2: 'A second, different person. Never blended with Character 1.',
  clothing: 'The outfit to reproduce, including sleeve and hem length. Not identity.',
  environment: 'Setting, atmosphere and lighting. Not identity.',
  tattoo_mark: 'Mark design and placement. Does not force a covered mark to show.',
  pose_composition: 'Pose and framing only. Anyone shown in it is not a character.',
  other: 'Extra visual evidence, no specific authority.',
  // Attribute roles. Each states the feature, then denies the rest of the
  // person, because "Eyes" on its own reads to a founder as "this face".
  eyes: 'Only the eyes — shape, colour, spacing. Not this person’s identity.',
  nose: 'Only the nose — bridge, width, tip. Not this person’s identity.',
  mouth_lips: 'Only the mouth and lips — shape and fullness. Not this person’s identity.',
  eyebrows: 'Only the eyebrows — shape, thickness, arch. Not this person’s identity.',
  hair: 'Only the hair — style, length, colour, texture. Not this person’s face.',
  skin_complexion: 'Only skin tone, texture and freckles. Not this person’s face.',
};
