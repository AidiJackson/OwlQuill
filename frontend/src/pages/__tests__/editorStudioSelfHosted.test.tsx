// @vitest-environment jsdom
/**
 * Phase 6.3B — Self Hosted Premium is offered only where it can run.
 *
 * The provider serves exactly one character. Admins keep the selector; the
 * self_hosted option is disabled, with a truthful hint, whenever any other
 * character is selected, and a held self_hosted choice falls back to
 * gpt-image the moment the character changes to an incompatible one, so the
 * page can never submit a request the server will refuse. Non-admins never
 * see the selector, exactly as before.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacters = vi.fn();
const editorJobLatest = vi.fn();
const editorJobStart = vi.fn();
const editorGenerate = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacters: (...a: unknown[]) => getCharacters(...a),
    editorJobLatest: (...a: unknown[]) => editorJobLatest(...a),
    editorJobStart: (...a: unknown[]) => editorJobStart(...a),
    editorGenerate: (...a: unknown[]) => editorGenerate(...a),
    editorJobGet: () => Promise.resolve(null),
    hasToken: () => true,
  },
}));

import EditorStudio from '@/pages/EditorStudio';
import { useAuthStore } from '@/lib/store';
import {
  SELF_HOSTED_EDITOR_CHARACTER_ID,
  SELF_HOSTED_UNAVAILABLE_HINT,
} from '@/features/editorStudio/editorGenerate';

const base = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 2, created_at: '', updated_at: '' };
const CREATOR = { ...base, is_admin: false, is_seeder: false, writer_unlocked: true } as unknown as User;
const SEEDER = { ...base, is_admin: false, is_seeder: true } as unknown as User;
const ADMIN = { ...base, is_admin: true, is_seeder: false } as unknown as User;

function char(id: number, name: string): Character {
  return {
    id, name, species: 'human', visibility: 'private', is_owner: true,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  } as unknown as Character;
}

const COMPATIBLE = char(SELF_HOSTED_EDITOR_CHARACTER_ID, 'Test Character');
const OTHER = char(11, 'Avery');

function renderStudio(user: User) {
  useAuthStore.setState({ user, status: 'authenticated' });
  return render(
    <MemoryRouter initialEntries={['/editor-studio']}>
      <EditorStudio />
    </MemoryRouter>,
  );
}

// Labels are not associated with their selects (deferred accessibility
// work), so the two selects are found by position: character first,
// provider second.
async function selects(): Promise<{ character: HTMLSelectElement; provider: HTMLSelectElement | null }> {
  const placeholder = await screen.findByRole('option', { name: 'Select a character…' });
  const character = placeholder.closest('select') as HTMLSelectElement;
  await waitFor(() => expect(character.value).not.toBe(''));
  const all = screen.getAllByRole('combobox') as HTMLSelectElement[];
  return { character, provider: all[1] ?? null };
}

function selfHostedOption(provider: HTMLSelectElement): HTMLOptionElement {
  return Array.from(provider.options).find((o) => o.value === 'self_hosted') as HTMLOptionElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  editorJobLatest.mockResolvedValue(null);
  try { window.localStorage.clear(); } catch { /* jsdom */ }
});
afterEach(cleanup);

describe('non-admins', () => {
  it.each([
    ['ordinary creator', CREATOR],
    ['Seeder', SEEDER],
  ] as [string, User][])('%s never sees a provider control, compatible character or not', async (_who, user) => {
    getCharacters.mockResolvedValue([COMPATIBLE, OTHER]);
    renderStudio(user);
    const { character, provider } = await selects();
    expect(character.value).toBe(String(SELF_HOSTED_EDITOR_CHARACTER_ID));
    expect(provider).toBeNull();
    expect(screen.queryByText(/Self Hosted/)).toBeNull();
  });
});

describe('admin', () => {
  it('can select Self Hosted Premium when the compatible character is selected', async () => {
    getCharacters.mockResolvedValue([COMPATIBLE, OTHER]);
    renderStudio(ADMIN);
    const { provider } = await selects();
    expect(provider).not.toBeNull();
    expect(selfHostedOption(provider!).disabled).toBe(false);
    fireEvent.change(provider!, { target: { value: 'self_hosted' } });
    expect(provider!.value).toBe('self_hosted');
    expect(screen.getByText(/unrestricted outfit/i)).toBeTruthy();
    expect(screen.queryByText(SELF_HOSTED_UNAVAILABLE_HINT, { exact: false })).toBeNull();
  });

  it('cannot select Self Hosted Premium for any other character, and is told why', async () => {
    getCharacters.mockResolvedValue([OTHER, COMPATIBLE]);
    renderStudio(ADMIN);
    const { character, provider } = await selects();
    expect(character.value).toBe('11');
    const option = selfHostedOption(provider!);
    expect(option.disabled).toBe(true);
    expect(option.textContent).toBe('Self Hosted Premium');
    const hint = screen.getByText(SELF_HOSTED_UNAVAILABLE_HINT, { exact: false });
    expect(hint.textContent).not.toMatch(/summer|lora|\b60\b/i);
    // The other providers are exactly as before.
    expect(Array.from(provider!.options).map((o) => [o.value, o.disabled])).toEqual([
      ['gpt-image', false], ['grok', false], ['self_hosted', true],
    ]);
  });

  it('resets a held self_hosted choice to gpt-image when the character changes to an incompatible one', async () => {
    getCharacters.mockResolvedValue([COMPATIBLE, OTHER]);
    renderStudio(ADMIN);
    const { character, provider } = await selects();
    fireEvent.change(provider!, { target: { value: 'self_hosted' } });
    expect(provider!.value).toBe('self_hosted');

    fireEvent.change(character, { target: { value: '11' } });
    await waitFor(() => expect(provider!.value).toBe('gpt-image'));
    expect(selfHostedOption(provider!).disabled).toBe(true);
    expect(screen.getByText(SELF_HOSTED_UNAVAILABLE_HINT, { exact: false })).toBeTruthy();

    // Back to the compatible character: available again, but the choice is
    // the admin's to make — nothing silently re-selects self_hosted.
    fireEvent.change(character, { target: { value: String(SELF_HOSTED_EDITOR_CHARACTER_ID) } });
    await waitFor(() => expect(selfHostedOption(provider!).disabled).toBe(false));
    expect(provider!.value).toBe('gpt-image');
  });

  it('applies the same rule to a persisted self_hosted preference on load', async () => {
    try { window.localStorage.setItem('ficshon.editor_studio.provider', 'self_hosted'); } catch { /* jsdom */ }
    getCharacters.mockResolvedValue([OTHER, COMPATIBLE]);
    renderStudio(ADMIN);
    const { provider } = await selects();
    await waitFor(() => expect(provider!.value).toBe('gpt-image'));
  });

  it('never submits self_hosted for an incompatible character even if state were forced', async () => {
    // Belt and braces: the form validator is the last line before the
    // request, independent of the effect that resets the selector.
    getCharacters.mockResolvedValue([COMPATIBLE, OTHER]);
    renderStudio(ADMIN);
    const { character, provider } = await selects();
    fireEvent.change(provider!, { target: { value: 'self_hosted' } });
    fireEvent.change(character, { target: { value: '11' } });
    await waitFor(() => expect(provider!.value).toBe('gpt-image'));
    fireEvent.click(screen.getByRole('button', { name: /Generate edit/ }));
    // No sources yet, so the ordinary validation speaks first — and no
    // request of either kind was made.
    expect(editorJobStart).not.toHaveBeenCalled();
    expect(editorGenerate).not.toHaveBeenCalled();
  });

  it('leaves grok and gpt-image selection unchanged by a character change', async () => {
    getCharacters.mockResolvedValue([COMPATIBLE, OTHER]);
    renderStudio(ADMIN);
    const { character, provider } = await selects();
    fireEvent.change(provider!, { target: { value: 'grok' } });
    fireEvent.change(character, { target: { value: '11' } });
    await waitFor(() => expect(character.value).toBe('11'));
    expect(provider!.value).toBe('grok');
  });
});
