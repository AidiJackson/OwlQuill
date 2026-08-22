import { describe, it, expect } from 'vitest';
import { canUseCreatorTools, hasActingCharacter, isFounder } from '../entitlements';
import type { User } from '../types';

function makeUser(overrides: Partial<User>): User {
  return {
    id: 1,
    email: 'x@e.com',
    username: 'x',
    created_at: '',
    updated_at: '',
    ...overrides,
  };
}

describe('canUseCreatorTools', () => {
  it('is false for a plain Wanderer (no characters, no flags)', () => {
    expect(canUseCreatorTools(makeUser({ character_count: 0 }))).toBe(false);
    expect(canUseCreatorTools(null)).toBe(false);
    expect(canUseCreatorTools(undefined)).toBe(false);
  });

  it('is true once the account owns a character', () => {
    expect(canUseCreatorTools(makeUser({ character_count: 1 }))).toBe(true);
  });

  it('is true for admin or seeder even with no characters', () => {
    expect(canUseCreatorTools(makeUser({ character_count: 0, is_admin: true }))).toBe(true);
    expect(canUseCreatorTools(makeUser({ character_count: 0, is_seeder: true }))).toBe(true);
  });
});

describe('hasActingCharacter', () => {
  it('is false for a zero-character admin — distinct from canUseCreatorTools', () => {
    const zeroCharAdmin = makeUser({ character_count: 0, is_admin: true });
    expect(canUseCreatorTools(zeroCharAdmin)).toBe(true);
    expect(hasActingCharacter(zeroCharAdmin)).toBe(false);
  });

  it('is true only when a character exists', () => {
    expect(hasActingCharacter(makeUser({ character_count: 2 }))).toBe(true);
    expect(hasActingCharacter(makeUser({ character_count: 0 }))).toBe(false);
  });
});

describe('isFounder', () => {
  it('is true for an admin and for a dedicated seeder', () => {
    // Lauren's account is the seeder shape: is_seeder, no admin rights.
    expect(isFounder(makeUser({ is_admin: true }))).toBe(true);
    expect(isFounder(makeUser({ is_seeder: true }))).toBe(true);
  });

  it('is false for a Writer and for a Wanderer', () => {
    // The founder image workflow must not widen ordinary creator access.
    expect(isFounder(makeUser({ character_count: 3 }))).toBe(false);
    expect(isFounder(makeUser({ writer_unlocked: true }))).toBe(false);
    expect(isFounder(makeUser({ character_count: 0 }))).toBe(false);
  });

  it('is false when there is no user', () => {
    expect(isFounder(null)).toBe(false);
    expect(isFounder(undefined)).toBe(false);
  });
});
