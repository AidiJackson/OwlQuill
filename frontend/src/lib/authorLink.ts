/**
 * Author attribution (identity-first, final product direction).
 *
 * Characters are the ONLY public identities on Ficshon. Character-authored
 * content links to the character profile; everything else — legacy
 * account-authored content included — renders as an unlinked "Wanderer".
 * Account usernames are private infrastructure and never appear on, or link
 * from, a public surface.
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
  kind: 'character' | 'anonymous';
}

export function authorLink(item: AuthoredContent): AuthorLink {
  if (item.character_id != null && item.character_name) {
    return {
      href: `/characters/${item.character_id}`,
      label: item.character_name,
      kind: 'character',
    };
  }
  // No character — never fall back to the account. Wanderer, unlinked.
  return { href: null, label: 'Wanderer', kind: 'anonymous' };
}
