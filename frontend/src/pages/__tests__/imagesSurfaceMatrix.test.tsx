// @vitest-environment jsdom
/**
 * Polish Phase 6.4 — the Image Library, card by card, audience by audience.
 *
 * /images is where the internal tools hang their doors, so it is the surface
 * most likely to leak one. Every card, control and link on the page is
 * classified here and pinned to the audience it was decided for:
 *
 *   ordinary/creator product  back link · generator (no provider selector —
 *                             it always sends Canon) · weekly allowance ·
 *                             empty-state Create character
 *   founder capability        Admin Creator card (FounderRoute's audience) ·
 *                             Canon/OpenAI provider selector · upload +
 *                             reference picker · All Characters filter
 *   admin capability          "· Admin" label on OpenAI
 *
 * W-02: the 18+ Studio card and the Grok provider are no longer offered on
 * /images to anyone (admins included); the generator's adult-adjacent nudge is
 * gone too (pinned in sceneGeneratorAdultNudge). The Studio itself is still
 * reached by its AdminRoute deep link — pinned in privilegedRoutes.
 *
 * The user here is what GET /users/me returns — the page reads it from the
 * API, not from the store — so the fixtures are handed to getMe.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacters = vi.fn();
const getMe = vi.fn();
const getImageQuota = vi.fn();
const listMyCharacterImages = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacters: (...a: unknown[]) => getCharacters(...a),
    getMe: (...a: unknown[]) => getMe(...a),
    getImageQuota: (...a: unknown[]) => getImageQuota(...a),
    listMyCharacterImages: (...a: unknown[]) => listMyCharacterImages(...a),
    hasToken: () => true,
  },
}));
// Founder-only children make their own requests; sentinels are enough to
// prove who is offered them.
vi.mock('@/features/images/components/ReferencePicker', () => ({ default: () => <p>REFERENCE PICKER</p> }));
vi.mock('@/features/images/components/UploadImageButton', () => ({ default: () => <p>UPLOAD BUTTON</p> }));
vi.mock('@/features/images/useGenerationJob', () => ({
  useGenerationJob: () => ({
    phase: 'idle', job: null, image: null, error: '', busy: false,
    submit: vi.fn(), resume: vi.fn(), resumeJob: vi.fn(), reset: vi.fn(),
  }),
}));

import Images from '@/pages/Images';
import { useAuthStore } from '@/lib/store';

const base = { id: 7, email: 'me@test.invalid', username: 'me', created_at: '', updated_at: '' };
const CREATOR = { ...base, character_count: 1, is_admin: false, is_seeder: false, can_create_character: true } as unknown as User;
const CREATOR_NO_CHARS = { ...base, character_count: 0, is_admin: false, is_seeder: false, writer_unlocked: true, can_create_character: true } as unknown as User;
const SEEDER = { ...base, character_count: 1, is_admin: false, is_seeder: true, can_create_character: true } as unknown as User;
const ADMIN = { ...base, character_count: 1, is_admin: true, is_seeder: false, can_create_character: true } as unknown as User;
const ADMIN_SEEDER = { ...base, character_count: 1, is_admin: true, is_seeder: true, can_create_character: true } as unknown as User;

function char(id: number, name: string): Character {
  return {
    id, name, species: 'human', visibility: 'public', is_owner: true,
    visual_locked: true, has_identity_canon: true,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  } as unknown as Character;
}
const ONE = [char(42, 'Taylor')];
const TWO = [char(42, 'Taylor'), char(43, 'Morgan')];

async function renderLibrary(user: User, characters: Character[] = ONE) {
  getMe.mockResolvedValue(user);
  getCharacters.mockResolvedValue(characters);
  useAuthStore.setState({ user, status: 'authenticated' });
  const r = render(
    <MemoryRouter initialEntries={['/images']}>
      <Routes>
        <Route path="/images" element={<Images />} />
        <Route path="/admin-creator" element={<p>ADMIN CREATOR PAGE</p>} />
        <Route path="/studio/18-plus" element={<p>STUDIO PAGE</p>} />
        <Route path="/characters/new" element={<p>CREATOR PAGE</p>} />
      </Routes>
    </MemoryRouter>,
  );
  await waitFor(() => expect(getMe).toHaveBeenCalled());
  await waitFor(() => expect(listMyCharacterImages).toHaveBeenCalled());
  return r;
}

const adminCreatorCard = () => screen.queryByRole('link', { name: 'Open Admin Creator' });
const studioCard = () => screen.queryByRole('button', { name: 'Open 18+ Studio' });
const provider = (label: RegExp) => screen.queryByRole('button', { name: label });

beforeEach(() => {
  vi.clearAllMocks();
  getImageQuota.mockResolvedValue({ unlimited: false, used: 1, limit: 10, remaining: 9, reset_at: null });
  listMyCharacterImages.mockResolvedValue([]);
});
afterEach(cleanup);

describe('ordinary creator', () => {
  it('sees the product: generator without provider UI, allowance, no internal doors, no founder tools', async () => {
    await renderLibrary(CREATOR);
    expect(screen.getByText('Image Library')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Generate Image/ })).toBeTruthy();
    expect(provider(/Canon · Recommended/)).toBeNull();
    expect(screen.getByText(/9 of 10 images remaining/)).toBeTruthy();

    expect(adminCreatorCard()).toBeNull();
    expect(screen.queryByText('Admin Creator')).toBeNull();
    expect(studioCard()).toBeNull();
    expect(screen.queryByText('18+ Studio')).toBeNull();
    expect(provider(/OpenAI/)).toBeNull();
    expect(provider(/Grok/)).toBeNull();
    expect(screen.queryByText('UPLOAD BUTTON')).toBeNull();
    expect(screen.queryByText('REFERENCE PICKER')).toBeNull();
    expect(screen.queryByRole('option', { name: 'All Characters' })).toBeNull();
    expect(document.querySelector('a[href="/admin-creator"]')).toBeNull();
  });

  it('with several characters gets the All Characters filter — that is a roster fact, not a founder one', async () => {
    await renderLibrary(CREATOR, TWO);
    expect(screen.getByRole('option', { name: 'All Characters' })).toBeTruthy();
    expect(adminCreatorCard()).toBeNull();
    expect(studioCard()).toBeNull();
  });

  it('with no characters is pointed at the Creator (/characters/new), never a generator', async () => {
    await renderLibrary(CREATOR_NO_CHARS, []);
    expect(screen.getByRole('button', { name: 'Create character' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Go to Characters' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Generate Image/ })).toBeNull();
    expect(adminCreatorCard()).toBeNull();
    expect(studioCard()).toBeNull();
  });
});

describe('Seeder (founder-capable, not admin)', () => {
  it('gets the founder tools and the Admin Creator door, but not the admin ones', async () => {
    await renderLibrary(SEEDER);
    expect(adminCreatorCard()!.getAttribute('href')).toBe('/admin-creator');
    expect(screen.getByText(/Internal testing only/)).toBeTruthy();
    expect(provider(/Canon · Recommended/)).toBeTruthy();
    expect(provider(/^OpenAI$/)).toBeTruthy();       // founder label, no "· Admin"
    expect(screen.getByText('UPLOAD BUTTON')).toBeTruthy();
    expect(screen.getByText('REFERENCE PICKER')).toBeTruthy();
    expect(screen.getByRole('option', { name: 'All Characters' })).toBeTruthy();

    expect(studioCard()).toBeNull();
    expect(screen.queryByText('18+ Studio')).toBeNull();
    expect(provider(/Grok/)).toBeNull();
  });
});

describe('Admin', () => {
  it.each([['Admin', ADMIN], ['Admin+Seeder', ADMIN_SEEDER]] as [string, User][])(
    '%s gets Admin Creator, Canon + OpenAI · Admin and founder tools — but no 18+ Studio card and no Grok',
    async (_who, user) => {
      await renderLibrary(user);
      expect(adminCreatorCard()!.getAttribute('href')).toBe('/admin-creator');
      expect(provider(/Canon · Recommended/)).toBeTruthy();
      expect(provider(/OpenAI · Admin/)).toBeTruthy();
      expect(provider(/Grok/)).toBeNull();
      expect(studioCard()).toBeNull();
      expect(screen.queryByText('18+ Studio')).toBeNull();
      expect(document.querySelector('a[href^="/studio/18-plus"]')).toBeNull();
      expect(screen.getByText('UPLOAD BUTTON')).toBeTruthy();
      expect(screen.getByText('REFERENCE PICKER')).toBeTruthy();
      expect(screen.getByRole('option', { name: 'All Characters' })).toBeTruthy();
    },
  );
});

describe('the doors agree with their routes (one predicate each)', () => {
  it('Admin Creator card ⇔ isFounder (admin OR seeder); 18+ Studio card ⇔ nobody (W-02)', async () => {
    const seen: Record<string, [boolean, boolean]> = {};
    for (const [who, user] of [['creator', CREATOR], ['seeder', SEEDER], ['admin', ADMIN], ['admin+seeder', ADMIN_SEEDER]] as [string, User][]) {
      const r = await renderLibrary(user);
      seen[who] = [adminCreatorCard() !== null, studioCard() !== null];
      r.unmount();
    }
    expect(seen).toEqual({
      creator: [false, false],
      seeder: [true, false],
      admin: [true, false],
      'admin+seeder': [true, false],
    });
  });
});
