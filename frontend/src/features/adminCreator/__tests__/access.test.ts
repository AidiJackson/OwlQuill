import { describe, it, expect } from 'vitest';
import type { User } from '@/lib/types';
import { canUseAdminCreator } from '../access';

function makeUser(overrides: Partial<User>): User {
  return {
    id: 1,
    email: 'x@e.com',
    username: 'x',
    created_at: '',
    updated_at: '',
    ...overrides,
  } as User;
}

describe('Admin Creator access', () => {
  it('is closed to Wanderers', () => {
    expect(canUseAdminCreator(makeUser({ character_count: 0 }))).toBe(false);
  });

  it('is closed to ordinary creators, even with characters', () => {
    // The distinction that matters: owning a character grants the Image
    // Generator, NOT this experiment. If this ever returns true, an internal
    // tool has silently shipped to every creator.
    expect(canUseAdminCreator(makeUser({ character_count: 1 }))).toBe(false);
    expect(canUseAdminCreator(makeUser({ character_count: 12 }))).toBe(false);
  });

  it('is closed to signed-out visitors', () => {
    expect(canUseAdminCreator(null)).toBe(false);
    expect(canUseAdminCreator(undefined)).toBe(false);
  });

  it('is open to admin', () => {
    expect(canUseAdminCreator(makeUser({ is_admin: true }))).toBe(true);
  });

  it('is open to the seeder', () => {
    expect(canUseAdminCreator(makeUser({ is_seeder: true }))).toBe(true);
  });

  it('does not depend on owning a character', () => {
    // A zero-character admin still gets in; the page then asks them to pick a
    // character before anything can be generated.
    expect(canUseAdminCreator(makeUser({ character_count: 0, is_admin: true }))).toBe(true);
  });

  it('is not widened by any other creator-ish flag', () => {
    // Fails loudly if a future flag is added to the founder rule without a
    // deliberate decision about this tool.
    for (const flag of ['is_writer', 'is_verified', 'is_premium'] as const) {
      expect(canUseAdminCreator(makeUser({ [flag]: true } as Partial<User>))).toBe(false);
    }
  });
});
