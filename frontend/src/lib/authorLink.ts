/**
 * Author attribution (identity-first, final product direction).
 *
 * Two account types, one public identity each:
 *
 *   • **Writer** — the character, and only the character. Character content
 *     links to the character profile; the private account username never
 *     appears on, or links from, a public surface.
 *   • **Wanderer** — the public Wanderer username, with the account sigil as
 *     its avatar. This is not a leak of a private name: for an account with no
 *     character, the Wanderer username *is* the public identity.
 *
 * The server enforces the same split — it omits `author_username` entirely
 * from character-attributed content — so a missing username here means "this
 * is a Writer's character content", not "we don't know who wrote it".
 */

export interface AuthoredContent {
  character_id?: number | null;
  character_name?: string | null;
  character_avatar_url?: string | null;
  author_username?: string | null;
  author_avatar_url?: string | null;
}

export interface AuthorLink {
  /** Route to navigate to, or null when there is no valid destination. */
  href: string | null;
  /** Display label for the author line. */
  label: string;
  /** Avatar to render beside the label: character portrait or account sigil. */
  avatarUrl: string | null;
  kind: 'character' | 'wanderer' | 'anonymous';
}

export function authorLink(item: AuthoredContent): AuthorLink {
  if (item.character_id != null && item.character_name) {
    return {
      href: `/characters/${item.character_id}`,
      label: item.character_name,
      avatarUrl: item.character_avatar_url ?? null,
      kind: 'character',
    };
  }
  if (item.author_username) {
    // A Wanderer: named publicly by their Wanderer username and account sigil.
    return {
      href: null,
      label: item.author_username,
      avatarUrl: item.author_avatar_url ?? null,
      kind: 'wanderer',
    };
  }
  // Nothing to attribute to — a deleted account, or content whose identity the
  // server withheld. Never invent an "Account" identity for it.
  return { href: null, label: 'Wanderer', avatarUrl: null, kind: 'anonymous' };
}
