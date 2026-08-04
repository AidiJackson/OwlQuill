import { describe, it, expect } from 'vitest';
// Sources are pulled in with Vite's `?raw` rather than node:fs so the file
// typechecks without @types/node, which this project does not depend on.
import homeSource from '../../pages/Home.tsx?raw';
import appSource from '../../App.tsx?raw';
import becomeAWriterSource from '../../pages/BecomeAWriter.tsx?raw';
import { canCreateCharacter, canUseCreatorTools, isWanderer } from '../entitlements';
import type { User } from '../types';

function makeUser(overrides: Partial<User>): User {
  return {
    id: 1,
    email: 'x@e.com',
    username: 'wanderer_one',
    created_at: '',
    updated_at: '',
    ...overrides,
  };
}

describe('canCreateCharacter (the Writer Unlock)', () => {
  it('is false for a Wanderer — creating a character needs the paid unlock', () => {
    expect(canCreateCharacter(makeUser({ character_count: 0 }))).toBe(false);
    expect(canCreateCharacter(null)).toBe(false);
  });

  it('is true once the account holds the Writer Unlock', () => {
    expect(canCreateCharacter(makeUser({ writer_unlocked: true }))).toBe(true);
  });

  it('is true for founder/admin/seeder accounts, which are exempt', () => {
    expect(canCreateCharacter(makeUser({ is_admin: true }))).toBe(true);
    expect(canCreateCharacter(makeUser({ is_seeder: true }))).toBe(true);
  });

  it('defers to the server flag when present — the server is the authority', () => {
    expect(canCreateCharacter(makeUser({ can_create_character: true }))).toBe(true);
    expect(
      canCreateCharacter(makeUser({ can_create_character: false, writer_unlocked: true })),
    ).toBe(false);
  });

  it('owning a character does not by itself grant creation of another', () => {
    // The one-character rule lives on the server; the client must not infer an
    // entitlement from ownership, which would re-open the circular loophole.
    expect(canCreateCharacter(makeUser({ character_count: 1 }))).toBe(false);
  });
});

describe('isWanderer', () => {
  it('is true for a characterless, unlocked-nothing account', () => {
    expect(isWanderer(makeUser({ character_count: 0 }))).toBe(true);
  });

  it('is false for writers, unlocked accounts and founders', () => {
    expect(isWanderer(makeUser({ character_count: 1 }))).toBe(false);
    expect(isWanderer(makeUser({ writer_unlocked: true }))).toBe(false);
    expect(isWanderer(makeUser({ is_admin: true }))).toBe(false);
  });
});

describe('canUseCreatorTools includes the unlock', () => {
  it('is true for an unlocked account that has not made its character yet', () => {
    expect(canUseCreatorTools(makeUser({ character_count: 0, writer_unlocked: true }))).toBe(true);
  });
});

// The Commons and the creation route are checked at the source level: there is
// no DOM test environment in this project (vitest runs in `node`), and these
// two facts are exactly what regressed — a prompt or a raw route creeping back
// in is the failure mode worth catching.
describe('the Commons shows no direct character-creation prompt', () => {
  const home = homeSource;

  it('has no navigation into the character creation flow', () => {
    const code = home.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    expect(code).not.toContain('/characters/new');
  });

  it('has no "create your character" copy', () => {
    const code = home.replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '');
    expect(code.toLowerCase()).not.toContain('create your character');
    expect(code.toLowerCase()).not.toContain('create character');
    expect(code.toLowerCase()).not.toContain('welcome to ficshon');
  });
});

describe('/characters/new is gated on the Writer entitlement', () => {
  const app = appSource;

  it('routes the creation flow through WriterRoute, not bare ProtectedRoute', () => {
    const route = app.slice(app.indexOf('path="/characters/new"'));
    const element = route.slice(0, route.indexOf('/>'));
    expect(element).toContain('<WriterRoute>');
    expect(element).not.toContain('<ProtectedRoute>');
  });

  it('WriterRoute renders the upgrade gate when the entitlement is missing', () => {
    expect(app).toContain('if (!canCreateCharacter(user))');
    expect(app).toContain('<BecomeAWriter />');
  });
});

describe('the upgrade gate is truthful about availability', () => {
  const page = becomeAWriterSource;

  it('states the unlock is not available yet rather than faking one', () => {
    expect(page).toContain("Writer Unlock isn't available during the closed beta.");
    expect(page.toLowerCase()).not.toContain('unlock successful');
  });

  it('says nothing about how the unlock will be obtained', () => {
    // Positioned as coming soon: the commercial model is not settled, and
    // naming it here would raise questions the product cannot answer yet.
    const lower = page.toLowerCase();
    for (const term of ['purchas', 'payment', 'charged', 'pricing', 'checkout']) {
      expect(lower).not.toContain(term);
    }
  });

  it('offers the creation flow only to an already-entitled account', () => {
    const gated = page.slice(page.indexOf('{entitled ?'), page.indexOf(') : ('));
    expect(gated).toContain("navigate('/characters/new')");
    // ...and the locked branch offers no route into creation at all.
    const locked = page.slice(page.indexOf(') : ('));
    expect(locked).not.toContain('/characters/new');
  });
});
