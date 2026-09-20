// @vitest-environment jsdom
/**
 * Polish Phase 6.3 — the character page's Media tab and lightbox present an
 * image kind in product language ("Scene"), not as the stored enum.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import type { Character, User } from '@/lib/types';

const listCharacterImages = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacter: () => Promise.resolve(OWNED),
    getMe: () => Promise.resolve(ORDINARY),
    getCharacterMentions: () => Promise.resolve([]),
    listCharacterImages: (...a: unknown[]) => listCharacterImages(...a),
    getCharacterPosts: () => Promise.resolve([]),
    listMyCharacterImages: () => Promise.resolve([]),
    getIdentityCanon: () => Promise.resolve(null),
    hasToken: () => true,
  },
}));

import CharacterDetail from '@/pages/CharacterDetail';
import { useAuthStore } from '@/lib/store';

const ORDINARY: User = {
  id: 7, email: 'me@test.invalid', username: 'me', character_count: 1,
  is_admin: false, is_seeder: false,
} as User;

const OWNED: Character = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public',
  short_bio: 'A detective.', avatar_url: '/a.png', cover_url: '/c.png',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  is_owner: true,
} as Character;

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/characters/42']}>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
});
afterEach(cleanup);

async function openMedia() {
  await screen.findByRole('heading', { name: 'Taylor' });
  fireEvent.click(screen.getByRole('button', { name: 'Media' }));
}

describe('CharacterDetail — image kind labels', () => {
  it('shows a scene_only image as "Scene" in the grid and the lightbox caption', async () => {
    listCharacterImages.mockResolvedValue([{ id: 9, url: '/nine.png', kind: 'scene_only' }]);
    renderPage();
    await openMedia();

    const thumb = await screen.findByRole('img', { name: 'Scene' });
    expect(screen.queryByRole('img', { name: /scene only/i })).toBeNull();

    fireEvent.click(thumb.closest('button') ?? thumb);
    const preview = await screen.findByRole('dialog', { name: 'Image preview' });
    expect(within(preview).getByRole('img', { name: 'Scene' })).toBeTruthy();
    expect(within(preview).getByText('Scene')).toBeTruthy();
    expect(within(preview).queryByText(/scene only/i)).toBeNull();
    expect(preview.textContent).not.toMatch(/scene_only/);
  });

  it('labels the other gallery kinds with their product names', async () => {
    listCharacterImages.mockResolvedValue([
      { id: 1, url: '/g.png', kind: 'generated' },
      { id: 2, url: '/c.png', kind: 'cover' },
    ]);
    renderPage();
    await openMedia();
    expect(await screen.findByRole('img', { name: 'Generated' })).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Cover' })).toBeTruthy();
  });

  it('gives an owner-visible working reference or future kind a readable label, never the enum', async () => {
    listCharacterImages.mockResolvedValue([
      { id: 3, url: '/ref.png', kind: 'identity_face_ref' },
      { id: 4, url: '/new.png', kind: 'some_future_kind' },
    ]);
    renderPage();
    await openMedia();
    const ref = await screen.findByRole('img', { name: 'Identity face ref' });
    expect(screen.getByRole('img', { name: 'Some future kind' })).toBeTruthy();
    expect(screen.queryByRole('img', { name: /_/ })).toBeNull();

    fireEvent.click(ref.closest('button') ?? ref);
    const preview = await screen.findByRole('dialog', { name: 'Image preview' });
    expect(within(preview).getByText('Identity face ref')).toBeTruthy();
    expect(preview.textContent).not.toMatch(/identity_face_ref/);
  });
});
