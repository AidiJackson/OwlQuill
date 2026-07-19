import { describe, it, expect } from 'vitest';
import { authorLink, creatorProfilePath } from '../authorLink';

describe('creatorProfilePath (sidebar Profile destination)', () => {
  it('points the authenticated user at their creator profile /u/{username}', () => {
    expect(creatorProfilePath({ username: 'aidan' })).toBe('/u/aidan');
  });

  it('exists independently of any active character (character never changes the target)', () => {
    // The helper only ever consumes the account username — an active
    // character on the user object cannot redirect Profile to a character page.
    const userWithActiveCharacter = {
      username: 'aidan',
      active_character: { id: 42, name: 'Pan' },
    };
    expect(creatorProfilePath(userWithActiveCharacter)).toBe('/u/aidan');
    expect(creatorProfilePath(userWithActiveCharacter)).not.toContain('/characters/');
  });

  it('falls back to /profile when unauthenticated', () => {
    expect(creatorProfilePath(null)).toBe('/profile');
    expect(creatorProfilePath(undefined)).toBe('/profile');
  });

  it('URL-encodes unusual usernames', () => {
    expect(creatorProfilePath({ username: 'a b' })).toBe('/u/a%20b');
  });
});

describe('authorLink (content attribution fallback)', () => {
  it('character-authored content links to the character profile', () => {
    const link = authorLink({ character_id: 7, character_name: 'Summer', author_username: undefined });
    expect(link).toEqual({ href: '/characters/7', label: 'Summer', kind: 'character' });
  });

  it('character attribution wins even if account identity is somehow present', () => {
    const link = authorLink({ character_id: 7, character_name: 'Summer', author_username: 'owner' });
    expect(link.kind).toBe('character');
    expect(link.href).toBe('/characters/7');
  });

  it('legacy account-authored content links to the creator profile', () => {
    const link = authorLink({ character_id: null, character_name: null, author_username: 'aidan' });
    expect(link).toEqual({ href: '/u/aidan', label: '@aidan', kind: 'creator' });
  });

  it('URL-encodes creator usernames', () => {
    expect(authorLink({ author_username: 'a b' }).href).toBe('/u/a%20b');
  });

  it('unknown identity renders as an unlinked Wanderer', () => {
    const link = authorLink({ character_id: null, character_name: null, author_username: null });
    expect(link).toEqual({ href: null, label: 'Wanderer', kind: 'anonymous' });
  });
});
