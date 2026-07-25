// Entitlements — the single source of truth for "what may this account do".
//
// These conditions are deliberately NOT written inline at call sites. Ficshon's
// creator entitlement is currently derived from character ownership, but the
// Writer unlock will replace that rule. When it lands, it is changed here and
// nowhere else — every caller keeps working unmodified.
//
// If you find yourself writing `character_count > 0` in a component, the check
// belongs in this file instead.

import type { User } from './types';

type MaybeUser = User | null | undefined;

/**
 * May this account use the creator workspaces — image library, StoryLab,
 * Editor Studio, RP Stories, Workspace, publishing?
 *
 * Wanderers are a complete, first-class role, not incomplete creators. A false
 * result means "this surface isn't part of your experience", never "you haven't
 * finished setting up".
 *
 * NOTE: the `character_count > 0` term is an implementation detail of the
 * current rule. Replace it with the Writer entitlement here when that ships.
 */
export function canUseCreatorTools(user: MaybeUser): boolean {
  return !!(
    user?.is_admin ||
    user?.is_seeder ||
    (user?.character_count ?? 0) > 0
  );
}

/**
 * Does this account have a character it can *act as*?
 *
 * Distinct from `canUseCreatorTools`, and deliberately so. Messaging, posting
 * and realm-joining are character-to-character: they need an actual character
 * behind them, so admin and seeder flags are irrelevant here. A founder with
 * zero characters genuinely cannot send a character-to-character message.
 *
 * Do not merge this with `canUseCreatorTools` — doing so would grant actions
 * that have no character to perform them.
 */
export function hasActingCharacter(user: MaybeUser): boolean {
  return (user?.character_count ?? 0) > 0;
}
