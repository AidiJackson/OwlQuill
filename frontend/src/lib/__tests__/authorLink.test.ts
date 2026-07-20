import { describe, it, expect } from 'vitest';
import { authorLink } from '../authorLink';

describe('authorLink (identity-first content attribution)', () => {
  it('character-authored content links to the character profile', () => {
    const link = authorLink({ character_id: 7, character_name: 'Summer', author_username: undefined });
    expect(link).toEqual({ href: '/characters/7', label: 'Summer', kind: 'character' });
  });

  it('character attribution wins even if account identity is somehow present', () => {
    const link = authorLink({ character_id: 7, character_name: 'Summer', author_username: 'owner' });
    expect(link.kind).toBe('character');
    expect(link.href).toBe('/characters/7');
  });

  it('legacy account-authored content renders as an unlinked Wanderer — accounts are never public identities', () => {
    const link = authorLink({ character_id: null, character_name: null, author_username: 'aidan' });
    expect(link).toEqual({ href: null, label: 'Wanderer', kind: 'anonymous' });
  });

  it('never emits an account username in label or href', () => {
    const link = authorLink({ character_id: null, character_name: null, author_username: 'admin' });
    expect(link.label).not.toContain('admin');
    expect(link.href).toBeNull();
  });

  it('unknown identity renders as an unlinked Wanderer', () => {
    const link = authorLink({ character_id: null, character_name: null, author_username: null });
    expect(link).toEqual({ href: null, label: 'Wanderer', kind: 'anonymous' });
  });
});
