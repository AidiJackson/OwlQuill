// @vitest-environment jsdom
/**
 * Polish Phase 6.3 — Editor Studio has no hidden favourite character.
 *
 * It used to pick, for admins only, whichever character was named "Summer…"
 * as the initial selection — a test convenience living in the real product
 * surface. Now every audience gets the same neutral rule: the first
 * character in roster order, changeable only through the visible select.
 *
 * Studio18Plus's SUMMER_CHARACTER_ID is a separate internal experiment and
 * is deliberately not covered here.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacters = vi.fn();
const editorJobLatest = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacters: (...a: unknown[]) => getCharacters(...a),
    editorJobLatest: (...a: unknown[]) => editorJobLatest(...a),
    editorJobGet: () => Promise.resolve(null),
    hasToken: () => true,
  },
}));

import EditorStudio from '@/pages/EditorStudio';
import { useAuthStore } from '@/lib/store';
import { EDITOR_PROVIDER_LABELS } from '@/features/editorStudio/editorGenerate';
import editorStudioSource from '../EditorStudio.tsx?raw';

const base = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 2, created_at: '', updated_at: '' };
const CREATOR = { ...base, is_admin: false, is_seeder: false, writer_unlocked: true } as unknown as User;
const SEEDER = { ...base, is_admin: false, is_seeder: true } as unknown as User;
const ADMIN = { ...base, is_admin: true, is_seeder: false } as unknown as User;
const FOUNDER_ADMIN = { ...base, is_admin: true, is_seeder: true } as unknown as User;

const AUDIENCES: [string, User][] = [
  ['ordinary creator', CREATOR],
  ['Seeder', SEEDER],
  ['Admin', ADMIN],
  ['Founder/admin', FOUNDER_ADMIN],
];

function char(id: number, name: string): Character {
  return {
    id, name, species: 'human', visibility: 'private', is_owner: true,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  } as unknown as Character;
}

// Roster order as the server returns it: Summer is present but NOT first.
const ROSTER = [char(11, 'Avery'), char(60, 'Summer'), char(12, 'Blake')];

function renderStudio(user: User) {
  useAuthStore.setState({ user, status: 'authenticated' });
  return render(
    <MemoryRouter initialEntries={['/editor-studio']}>
      <EditorStudio />
    </MemoryRouter>,
  );
}

// The character <select> is reached through its placeholder option: its
// visible label is not programmatically associated, and wiring that up is
// accessibility work outside this slice.
async function findCharacterSelect(): Promise<HTMLSelectElement> {
  const placeholder = await screen.findByRole('option', { name: 'Select a character…' });
  return placeholder.closest('select') as HTMLSelectElement;
}

async function characterSelect(): Promise<HTMLSelectElement> {
  const select = await findCharacterSelect();
  await waitFor(() => expect(select.value).not.toBe(''));
  return select;
}

beforeEach(() => {
  vi.clearAllMocks();
  getCharacters.mockResolvedValue(ROSTER);
  editorJobLatest.mockResolvedValue(null);
});
afterEach(cleanup);

describe('Editor Studio — initial character selection', () => {
  it.each(AUDIENCES)('%s starts on the first character in roster order, not Summer', async (_who, user) => {
    renderStudio(user);
    const select = await characterSelect();
    expect(select.value).toBe('11');
    expect(select.selectedOptions[0].textContent).toBe('Avery');
  });

  it('keeps Summer selectable like any other character, just never privileged', async () => {
    renderStudio(ADMIN);
    const select = await characterSelect();
    fireEvent.change(select, { target: { value: '60' } });
    expect(select.value).toBe('60');
    expect(select.selectedOptions[0].textContent).toBe('Summer');
  });

  it('is the same rule for every audience when Summer is the first character', async () => {
    // A character called Summer that happens to be first is chosen because
    // it is first, for a creator as much as for an admin.
    getCharacters.mockResolvedValue([char(60, 'Summer'), char(11, 'Avery')]);
    for (const [, user] of AUDIENCES) {
      const { unmount } = renderStudio(user);
      const select = await characterSelect();
      expect(select.value).toBe('60');
      unmount();
    }
  });

  it('prompts for a selection when the account has no characters', async () => {
    getCharacters.mockResolvedValue([]);
    renderStudio(CREATOR);
    const select = await findCharacterSelect();
    await waitFor(() => expect(getCharacters).toHaveBeenCalled());
    expect(select.value).toBe('');
    expect(select.options).toHaveLength(1);
  });

  it('does not privilege a character by name (source-level pin)', () => {
    expect(editorStudioSource).not.toMatch(/summer/i);
    expect(editorStudioSource).not.toMatch(/startsWith\(/);
  });
});

describe('Editor Studio — provider controls are unchanged by the cleanup', () => {
  it.each([
    ['ordinary creator', CREATOR],
    ['Seeder', SEEDER],
  ] as [string, User][])('%s gets no provider selector', async (_who, user) => {
    renderStudio(user);
    await characterSelect();
    expect(screen.getAllByRole('combobox')).toHaveLength(1);
    expect(screen.queryByText(/Provider/)).toBeNull();
    expect(editorJobLatest).not.toHaveBeenCalled();
  });

  it.each([
    ['Admin', ADMIN],
    ['Founder/admin', FOUNDER_ADMIN],
  ] as [string, User][])('%s keeps the provider selector with every editor provider', async (_who, user) => {
    renderStudio(user);
    await characterSelect();
    expect(screen.getByText(/Provider/)).toBeTruthy();
    const provider = screen.getAllByRole('combobox')[1] as HTMLSelectElement;
    const labels = Array.from(provider.options).map((o) => o.textContent);
    expect(labels).toEqual(Object.values(EDITOR_PROVIDER_LABELS));
    expect(provider.value).toBe('gpt-image');
    // The self-hosted job resume still follows the selected character.
    await waitFor(() => expect(editorJobLatest).toHaveBeenCalledWith(11));
  });
});
