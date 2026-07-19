/**
 * Author attribution fallback (creator-profile restoration).
 *
 * Character-authored content links to the character profile; legacy
 * account-authored content with a known creator links to the creator profile
 * at /u/{username}; genuinely anonymous content renders as an unlinked
 * "Wanderer". Character-first attribution is unchanged — the backend still
 * omits account identity from character-attributed posts for non-authors, so
 * the creator branch can only ever fire for characterless content.
 */

export interface AuthoredContent {
  character_id?: number | null;
  character_name?: string | null;
  author_username?: string | null;
}

export interface AuthorLink {
  /** Route to navigate to, or null when there is no valid destination. */
  href: string | null;
  /** Display label for the author line. */
  label: string;
  kind: 'character' | 'creator' | 'anonymous';
}

/**
 * Sidebar "Profile" destination: always the CREATOR profile at /u/{username}.
 * Deliberately independent of the active character — the character profile is
 * a separate surface (Characters nav + the character switcher).
 */
export function creatorProfilePath(user: { username: string } | null | undefined): string {
  return user ? `/u/${encodeURIComponent(user.username)}` : '/profile';
}

export function authorLink(item: AuthoredContent): AuthorLink {
  if (item.character_id != null && item.character_name) {
    return {
      href: `/characters/${item.character_id}`,
      label: item.character_name,
      kind: 'character',
    };
  }
  if (item.author_username) {
    return {
      href: `/u/${encodeURIComponent(item.author_username)}`,
      label: `@${item.author_username}`,
      kind: 'creator',
    };
  }
  return { href: null, label: 'Wanderer', kind: 'anonymous' };
}
