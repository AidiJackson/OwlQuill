// Interview rules — pure data decisions the creator makes, kept out of React
// so they can be pinned by tests (the same split sessionGuard.ts uses).
//
// Polish Phase 1. Three things live here:
//   * which Interview fields are REQUIRED and what "complete" means (C11, C2);
//   * the hair-length rule that stops "shaved short cut wavy hair" reaching a
//     prompt (C9);
//   * how the Interview's answers become the Character row's display fields,
//     so the row and the DNA can never disagree (C8).
import type { IdentitySpec, Species } from './types';
import { SPECIES_OPTIONS } from './types';

/** Hair length value that makes style and texture meaningless. */
export const SHAVED = 'Shaved';

/** The opening group's required answers. Everything else is optional. */
export const REQUIRED_FIELDS = ['gender', 'age_band'] as const;

/** True when a stored spec is a finished Interview the wizard may resume past. */
export function isInterviewComplete(spec: Partial<IdentitySpec> | null | undefined): boolean {
  if (!spec) return false;
  return REQUIRED_FIELDS.every((f) => typeof spec[f] === 'string' && (spec[f] as string).trim() !== '');
}

/** Does the current spec allow hair style / texture to be asked at all? */
export function hairDetailApplies(spec: Partial<IdentitySpec>): boolean {
  return spec.identity?.hair_length !== SHAVED;
}

/**
 * Set hair length, clearing style and texture when the new length is Shaved.
 *
 * Clearing — not merely hiding — is the point: a hidden control with a stale
 * value would still be sent to the DNA and compiled into the sketch and pack
 * prompts ("shaved slicked back wavy Auburn hair"). Any other length leaves
 * style and texture untouched, so switching Shaved → Long does not throw away
 * answers the user never asked to lose (they were already cleared on the way
 * in, so there is nothing to restore).
 */
export function withHairLength(spec: IdentitySpec, length: string): IdentitySpec {
  const next: IdentitySpec = {
    ...spec,
    identity: { ...spec.identity, hair_length: length },
  };
  if (length === SHAVED) {
    next.hair_style = undefined;
    next.hair_texture = undefined;
  }
  return next;
}

/**
 * The Character row's display fields, derived from the Interview.
 *
 * ``species`` is stored as its label ("Vampire") because the row's species is
 * free display text shown on cards and directories; the DNA keeps the enum
 * value ("vampire"). ``age`` is the age band verbatim — it is the only age the
 * product asks for.
 */
export function characterFieldsFromSpec(spec: IdentitySpec): { species?: string; age?: string } {
  const label = SPECIES_OPTIONS.find((o) => o.value === (spec.species as Species))?.label;
  return {
    species: label ?? (spec.species ? String(spec.species) : undefined),
    age: spec.age_band || undefined,
  };
}
