// @vitest-environment jsdom
/**
 * CharacterDetail trusts the SERVER's `is_owner` and nothing else (Polish
 * Phase 5.1).
 *
 * The page used to decide ownership by comparing `character.owner_id` with
 * the signed-in user's id. The detail read no longer carries `owner_id` for a
 * non-owner — a public character must not be traceable to the account behind
 * it — so that comparison would have quietly demoted every owner to a
 * visitor. `is_owner` is the one signal, and this pins that the page reads
 * it and does not fall back to `owner_id`, in either direction.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character } from '@/lib/types';

const getCharacter = vi.fn();
const getMe = vi.fn();
const listCharacterImages = vi.fn();
const getCharacterPosts = vi.fn();
const getCharacterMentions = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacter: (...a: unknown[]) => getCharacter(...a),
    getMe: (...a: unknown[]) => getMe(...a),
    listCharacterImages: (...a: unknown[]) => listCharacterImages(...a),
    getCharacterPosts: (...a: unknown[]) => getCharacterPosts(...a),
    getCharacterMentions: (...a: unknown[]) => getCharacterMentions(...a),
    listMyCharacterImages: () => Promise.resolve([]),
    hasToken: () => true,
  },
}));

import CharacterDetail from '@/pages/CharacterDetail';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 1 };

const BASE: Omit<Character, 'is_owner' | 'owner_id'> = {
  id: 42,
  name: 'Taylor',
  species: 'human',
  visibility: 'public',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/characters/${BASE.id}`]}>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
      </Routes>
    </MemoryRouter>,
  );

const ownerOnly = () => ({
  manageTab: screen.queryByRole('button', { name: 'Manage' }),
  addCover: screen.queryByRole('button', { name: /add cover|change cover/i }),
});

beforeEach(() => {
  vi.clearAllMocks();
  getMe.mockResolvedValue(ME);
  listCharacterImages.mockResolvedValue([]);
  getCharacterPosts.mockResolvedValue([]);
  getCharacterMentions.mockResolvedValue([]);
});

afterEach(cleanup);

describe('CharacterDetail ownership comes from is_owner', () => {
  it('shows the owner surface when is_owner is true and owner_id is absent', async () => {
    // The server's owner response — owner_id present in reality, but the page
    // must not need it: null here proves it is not consulted.
    getCharacter.mockResolvedValue({ ...BASE, is_owner: true, owner_id: null });
    renderPage();
    await screen.findByRole('heading', { name: 'Taylor' });
    await waitFor(() => expect(ownerOnly().manageTab).not.toBeNull());
    expect(ownerOnly().addCover).not.toBeNull();
    expect(screen.queryByRole('button', { name: 'Message' })).toBeNull();
  });

  it('shows the visitor surface when is_owner is false, even if owner_id happens to match', async () => {
    // A spoofed or stale owner_id equal to the viewer's id must not promote
    // a visitor: only the server's verdict counts.
    getCharacter.mockResolvedValue({ ...BASE, is_owner: false, owner_id: ME.id });
    renderPage();
    await screen.findByRole('heading', { name: 'Taylor' });
    await screen.findByRole('button', { name: 'Message' });
    expect(ownerOnly().manageTab).toBeNull();
    expect(ownerOnly().addCover).toBeNull();
    expect(screen.queryByText('Danger Zone')).toBeNull();
  });

  it('treats a response without is_owner as a visitor', async () => {
    // Defensive: an older or partial payload never grants management.
    getCharacter.mockResolvedValue({ ...BASE } as Character);
    renderPage();
    await screen.findByRole('heading', { name: 'Taylor' });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Message' })).not.toBeNull());
    expect(ownerOnly().manageTab).toBeNull();
  });
});
