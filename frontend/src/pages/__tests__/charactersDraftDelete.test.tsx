// @vitest-environment jsdom
/**
 * Draft deletion from the roster — Polish Phase 5.3.
 *
 * The draft dialog keeps its lighter confirmation (no typed name: a draft has
 * no locked identity or public surface). What changed: the server sets the
 * 24-hour cooldown on a draft delete exactly as on a full delete, so the
 * dialog now says so — only for accounts it applies to — and a successful
 * delete re-reads the account into the auth store and the page (the roster's
 * cooldown timer reads it), while a failed re-read is never shown as a
 * failed delete.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacters = vi.fn();
const getMe = vi.fn();
const deleteCharacter = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'getCharacters') return (...a: unknown[]) => getCharacters(...a);
        if (prop === 'getMe') return (...a: unknown[]) => getMe(...a);
        if (prop === 'deleteCharacter') return (...a: unknown[]) => deleteCharacter(...a);
        if (prop === 'hasToken') return () => true;
        return () => Promise.resolve([]);
      },
    },
  ),
}));

import Characters from '@/pages/Characters';
import { useAuthStore } from '@/lib/store';

const ORDINARY = {
  id: 7, email: 'me@test.invalid', username: 'me', character_count: 1,
  is_admin: false, is_seeder: false, writer_unlocked: true,
} as unknown as User;
const FOUNDER = { ...ORDINARY, is_seeder: true } as unknown as User;

const DRAFT = {
  id: 5, name: 'Sketchy', species: 'human', visibility: 'private',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  visual_locked: false, has_identity_canon: false, is_owner: true,
} as unknown as Character;

const renderPage = () =>
  render(
    <MemoryRouter>
      <Characters />
    </MemoryRouter>,
  );

async function openDraftDialog() {
  renderPage();
  await screen.findByRole('heading', { name: 'In progress' });
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  return screen.getByRole('dialog');
}

function confirmButton(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === 'Delete draft',
  ) as HTMLButtonElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  getCharacters.mockResolvedValue([DRAFT]);
  getMe.mockResolvedValue(ORDINARY);
  deleteCharacter.mockResolvedValue(undefined);
  useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
});
afterEach(cleanup);

describe('Roster draft delete — copy', () => {
  it('keeps the lighter confirmation (no typed name) and its truthful consequence line', async () => {
    const dialog = await openDraftDialog();
    expect(screen.queryByLabelText(/to confirm/)).toBeNull();
    expect(dialog.textContent).toMatch(/Their interview answers go with them/);
    expect(dialog.textContent).not.toMatch(/images/i); // claims nothing about images
    expect(confirmButton(dialog).disabled).toBe(false);
  });

  it('ordinary account: states the 24-hour cooldown the server will set', async () => {
    const dialog = await openDraftDialog();
    expect(dialog.textContent).toMatch(/must wait\s*24 hours/);
  });

  it('founder/seeder account: no cooldown claim', async () => {
    getMe.mockResolvedValue(FOUNDER);
    useAuthStore.setState({ user: FOUNDER, status: 'authenticated' });
    const dialog = await openDraftDialog();
    expect(dialog.textContent).not.toMatch(/24 hours/);
  });
});

describe('Roster draft delete — account state', () => {
  it('a successful delete removes the draft and re-reads the account into the store', async () => {
    const refreshed = {
      ...ORDINARY, character_count: 0,
      next_character_allowed_at: new Date(Date.now() + 23.5 * 3600 * 1000).toISOString(),
    } as unknown as User;
    getMe.mockResolvedValueOnce(ORDINARY).mockResolvedValueOnce(refreshed);

    const dialog = await openDraftDialog();
    fireEvent.click(confirmButton(dialog));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(deleteCharacter).toHaveBeenCalledWith(5);
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect((useAuthStore.getState().user as unknown as { character_count: number }).character_count).toBe(0),
    );
    expect(useAuthStore.getState().status).toBe('authenticated');
    expect(screen.queryByText('Sketchy')).toBeNull();
    // The page's own copy was refreshed too: the cooldown timer now shows.
    await screen.findByText(/New character in 23h/);
  });

  it('a failed delete stays in the dialog with the error and does not touch the store', async () => {
    deleteCharacter.mockRejectedValue(new Error('Not authorized to delete this character'));
    const dialog = await openDraftDialog();
    fireEvent.click(confirmButton(dialog));

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('Not authorized to delete this character'),
    );
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(getMe).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('heading', { name: 'Sketchy' })).toBeTruthy(); // still on the roster
  });

  it('a failed post-delete re-read is not shown as a failed delete and keeps the session', async () => {
    getMe.mockResolvedValueOnce(ORDINARY).mockRejectedValueOnce(new Error('offline'));
    const dialog = await openDraftDialog();
    fireEvent.click(confirmButton(dialog));

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(getMe).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText('Sketchy')).toBeNull();
    expect(useAuthStore.getState().status).toBe('authenticated');
    expect(useAuthStore.getState().user).not.toBeNull();
  });
});
