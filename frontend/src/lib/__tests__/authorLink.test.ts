import { describe, it, expect } from 'vitest';
import { authorLink } from '../authorLink';

describe('authorLink (identity-first content attribution)', () => {
  it('character-authored content links to the character profile', () => {
    const link = authorLink({
      character_id: 7,
      character_name: 'Summer',
      character_avatar_url: '/summer.png',
      author_username: undefined,
    });
    expect(link).toEqual({
      href: '/characters/7',
      label: 'Summer',
      avatarUrl: '/summer.png',
      kind: 'character',
    });
  });

  it('character attribution wins even if account identity is somehow present', () => {
    const link = authorLink({
      character_id: 7,
      character_name: 'Summer',
      author_username: 'owner_acct',
      author_avatar_url: '/sigil.svg',
    });
    expect(link.kind).toBe('character');
    expect(link.href).toBe('/characters/7');
    expect(link.label).toBe('Summer');
    // A Writer's public output carries the character, never the account.
    expect(link.label).not.toContain('owner_acct');
    expect(link.avatarUrl).not.toBe('/sigil.svg');
  });

  it('a Wanderer is named by their Wanderer username and account sigil', () => {
    // For a characterless account the username IS the public identity — this is
    // not the account-username leak the Writer rule guards against.
    const link = authorLink({
      character_id: null,
      character_name: null,
      author_username: 'Riverwalker',
      author_avatar_url: '/sigil.svg',
    });
    expect(link).toEqual({
      href: null,
      label: 'Riverwalker',
      avatarUrl: '/sigil.svg',
      kind: 'wanderer',
    });
  });

  it('a Wanderer with no sigil still gets their username, not a placeholder', () => {
    const link = authorLink({ character_id: null, character_name: null, author_username: 'Riverwalker' });
    expect(link.label).toBe('Riverwalker');
    expect(link.avatarUrl).toBeNull();
    expect(link.kind).toBe('wanderer');
  });

  it('unattributable content falls back to an unlinked, generic Wanderer', () => {
    const link = authorLink({ character_id: null, character_name: null, author_username: null });
    expect(link).toEqual({ href: null, label: 'Wanderer', avatarUrl: null, kind: 'anonymous' });
  });
});
