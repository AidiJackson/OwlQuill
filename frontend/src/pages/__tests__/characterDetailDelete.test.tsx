// @vitest-environment jsdom
/**
 * Character deletion from CharacterDetail — Polish Phase 5.3 (PD-8).
 *
 * Two things are pinned here. The confirmation copy must state what the
 * server actually does: images are KEPT in the account library (the old copy
 * said they were deleted), conversations are removed for both characters,
 * and the 24-hour cooldown is only claimed for accounts it applies to. And
 * after a successful DELETE the auth store — what the sidebar, Profile and
 * creator gating read — is refreshed from the server, while a failure of that
 * refresh is never presented as a failed deletion.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacter = vi.fn();
const getMe = vi.fn();
const deleteCharacter = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacter: (...a: unknown[]) => getCharacter(...a),
    getMe: (...a: unknown[]) => getMe(...a),
    deleteCharacter: (...a: unknown[]) => deleteCharacter(...a),
    listCharacterImages: () => Promise.resolve([]),
    getCharacterPosts: () => Promise.resolve([]),
    getCharacterMentions: () => Promise.resolve([]),
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
const FOUNDER: User = { ...ORDINARY, is_seeder: true } as User;

const CHARACTER: Character = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  is_owner: true,
} as Character;

function Landing() {
  return <h1>Roster page</h1>;
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/characters/${CHARACTER.id}`]}>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
        <Route path="/characters" element={<Landing />} />
      </Routes>
    </MemoryRouter>,
  );

/** Render, open Manage → Delete character → the dialog. Returns the dialog element. */
async function openDeleteDialog() {
  renderPage();
  await screen.findByRole('heading', { name: 'Taylor' });
  fireEvent.click(await screen.findByRole('button', { name: 'Manage' }));
  fireEvent.click(await screen.findByRole('button', { name: /Delete character/ }));
  return screen.getByRole('dialog');
}

function confirmButton(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === 'Delete character',
  ) as HTMLButtonElement;
}

function typeNameAndConfirm(dialog: HTMLElement) {
  fireEvent.change(screen.getByLabelText('Type Taylor to confirm'), { target: { value: 'Taylor' } });
  const button = confirmButton(dialog);
  expect(button.disabled).toBe(false);
  fireEvent.click(button);
}

beforeEach(() => {
  vi.clearAllMocks();
  getCharacter.mockResolvedValue(CHARACTER);
  getMe.mockResolvedValue(ORDINARY);
  deleteCharacter.mockResolvedValue(undefined);
  // The store starts stale on purpose: still pointing at the character.
  useAuthStore.setState({
    user: { ...ORDINARY, active_character: { id: 42, name: 'Taylor' } } as unknown as User,
    status: 'authenticated',
  });
});
afterEach(cleanup);

describe('CharacterDetail delete confirmation copy (PD-8)', () => {
  it('still requires the character name to be typed', async () => {
    const dialog = await openDeleteDialog();
    const button = confirmButton(dialog);
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Type Taylor to confirm'), { target: { value: 'taylor' } });
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Type Taylor to confirm'), { target: { value: 'Taylor' } });
    expect(button.disabled).toBe(false);
    expect(deleteCharacter).not.toHaveBeenCalled();
  });

  it('says generated images are kept in the image library and never that they are deleted', async () => {
    const dialog = await openDeleteDialog();
    const text = dialog.textContent ?? '';
    expect(text).toMatch(/Generated images are\s*not\s*deleted/);
    expect(text).toMatch(/stay in your image library/);
    expect(text).not.toMatch(/All generated images/);
    expect(text).not.toMatch(/everything that belongs to them/);
  });

  it('says conversations and messages are removed, for the other character too', async () => {
    const dialog = await openDeleteDialog();
    const text = dialog.textContent ?? '';
    expect(text).toMatch(/conversation .* is removed, with all its messages/);
    expect(text).toMatch(/for the other character too/);
  });

  it('says posts and comments stay up without the name — not that they are deleted', async () => {
    const dialog = await openDeleteDialog();
    const text = dialog.textContent ?? '';
    expect(text).toMatch(/Posts and comments Taylor wrote stay up, but no longer carry their name/);
  });

  it('does not expose database terminology', async () => {
    const dialog = await openDeleteDialog();
    expect(dialog.textContent).not.toMatch(/cascade|set null|foreign key/i);
  });
});

describe('CharacterDetail cooldown copy matches the server policy', () => {
  it('ordinary account: states the 24-hour wait', async () => {
    const dialog = await openDeleteDialog();
    expect(dialog.textContent).toMatch(/must wait\s*24 hours\s*before creating a new character/);
  });

  it('founder/seeder account: no cooldown claim at all', async () => {
    getMe.mockResolvedValue(FOUNDER);
    const dialog = await openDeleteDialog();
    expect(dialog.textContent).not.toMatch(/24 hours/);
    expect(dialog.textContent).not.toMatch(/cooldown/i);
  });

  it('account unknown (/me failed): hedged wording, no false promise either way', async () => {
    getMe.mockRejectedValue(new Error('offline'));
    const dialog = await openDeleteDialog();
    expect(dialog.textContent).toMatch(/Unless your account is exempt/);
    expect(dialog.textContent).not.toMatch(/must wait/);
  });
});

describe('CharacterDetail post-delete account state', () => {
  it('a successful DELETE refreshes the auth store from the server, then navigates', async () => {
    const refreshed = { ...ORDINARY, character_count: 0, active_character: null } as unknown as User;
    getMe.mockResolvedValueOnce(ORDINARY).mockResolvedValueOnce(refreshed);

    const dialog = await openDeleteDialog();
    typeNameAndConfirm(dialog);

    await screen.findByRole('heading', { name: 'Roster page' });
    expect(deleteCharacter).toHaveBeenCalledWith(42);
    // Two reads: the page load, then the post-delete refresh.
    expect(getMe).toHaveBeenCalledTimes(2);
    const user = useAuthStore.getState().user as unknown as { character_count: number; active_character: unknown };
    expect(user.character_count).toBe(0);
    expect(user.active_character).toBeNull();
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('the refresh runs after DELETE, never before it', async () => {
    const order: string[] = [];
    deleteCharacter.mockImplementation(async () => { order.push('delete'); });
    getMe.mockImplementation(async () => { order.push('me'); return ORDINARY; });

    const dialog = await openDeleteDialog();
    typeNameAndConfirm(dialog);
    await screen.findByRole('heading', { name: 'Roster page' });
    expect(order).toEqual(['me', 'delete', 'me']);
  });

  it('a failed DELETE is a deletion error: dialog stays, store untouched, no navigation', async () => {
    deleteCharacter.mockRejectedValue(new Error('Not authorized to delete this character'));
    const dialog = await openDeleteDialog();
    typeNameAndConfirm(dialog);

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('Not authorized to delete this character'),
    );
    expect(screen.queryByRole('heading', { name: 'Roster page' })).toBeNull();
    expect(getMe).toHaveBeenCalledTimes(1); // page load only — no refresh
    const user = useAuthStore.getState().user as unknown as { active_character: { id: number } };
    expect(user.active_character.id).toBe(42);
  });

  it('a failed post-delete refresh is NOT shown as a failed deletion and does not sign the user out', async () => {
    getMe.mockResolvedValueOnce(ORDINARY).mockRejectedValueOnce(new Error('offline'));
    const dialog = await openDeleteDialog();
    typeNameAndConfirm(dialog);

    // Deleted and moved on — no error, no retry offered.
    await screen.findByRole('heading', { name: 'Roster page' });
    expect(deleteCharacter).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    // The store is stale but the session is intact (this is why fetchUser is not used).
    expect(useAuthStore.getState().status).toBe('authenticated');
    expect(useAuthStore.getState().user).not.toBeNull();
  });
});
