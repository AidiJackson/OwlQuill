// @vitest-environment jsdom
/**
 * Edit Details + visibility on CharacterDetail — Polish Phase 5.4.
 *
 * PD-1: only name, alias, role, era, short bio, long bio and tags are
 * editable; no identity field is exposed. PD-2: Public and Private only, and
 * the Private copy does not claim already-shared posts disappear. The form
 * saves through the existing PATCH with only the changed fields and adopts
 * the server's response; failures stay visible; nothing double-submits; and
 * no non-owner path — fresh or stale — can reach the form.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacter = vi.fn();
const getMe = vi.fn();
const updateCharacter = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    getCharacter: (...a: unknown[]) => getCharacter(...a),
    getMe: (...a: unknown[]) => getMe(...a),
    updateCharacter: (...a: unknown[]) => updateCharacter(...a),
    listCharacterImages: () => Promise.resolve([]),
    getCharacterPosts: () => Promise.resolve([]),
    getCharacterMentions: () => Promise.resolve([]),
    listMyCharacterImages: () => Promise.resolve([]),
    hasToken: () => true,
  },
}));

import CharacterDetail from '@/pages/CharacterDetail';
import { useAuthStore } from '@/lib/store';
// Source text, for the ownership pin (the same device writerWaitlist.test uses).
import characterDetailSource from '../CharacterDetail.tsx?raw';
import editDetailsSource from '../../components/CharacterEditDetails.tsx?raw';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 1 } as unknown as User;

const OWNED: Character = {
  id: 42, name: 'Taylor', alias: 'Tay', role: 'detective', era: '1920s',
  short_bio: 'Short.', long_bio: 'Much longer.', tags: 'noir, rain',
  species: 'human', age: '34', visibility: 'public',
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  is_owner: true, owner_id: 7,
} as Character;

const SOMEONE_ELSES: Character = {
  ...OWNED, id: 43, name: 'Morgan', is_owner: false, owner_id: null,
} as Character;

function renderPage(id = 42) {
  return render(
    <MemoryRouter initialEntries={[`/characters/${id}`]}>
      {/* A way to change the :id without remounting the page element. */}
      <Link to="/characters/43">go to 43</Link>
      <Routes>
        <Route path="/characters/:id" element={<CharacterDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

async function openManage() {
  await screen.findByRole('heading', { name: OWNED.name });
  fireEvent.click(await screen.findByRole('button', { name: 'Manage' }));
}

async function openForm() {
  await openManage();
  fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
}

/** The Name label carries a visual "*" — match on the leading word. */
const field = (label: string) =>
  screen.getByLabelText(label === 'Name' ? /^Name\b/ : label) as HTMLInputElement;
const queryName = () => screen.queryByLabelText(/^Name\b/);
const saveButton = () => screen.getByRole('button', { name: /Save changes|Saving…/ }) as HTMLButtonElement;

beforeEach(() => {
  vi.clearAllMocks();
  getCharacter.mockImplementation((id: number) =>
    Promise.resolve(id === 43 ? SOMEONE_ELSES : OWNED),
  );
  getMe.mockResolvedValue(ME);
  useAuthStore.setState({ user: { ...ME, active_character: { id: 42, name: 'Taylor' } } as unknown as User, status: 'authenticated' });
});
afterEach(cleanup);

describe('Edit Details — who sees it', () => {
  it('owner sees Edit details in Manage', async () => {
    renderPage();
    await openManage();
    expect(screen.getByRole('button', { name: 'Edit details' })).toBeTruthy();
    expect(screen.getByTestId('visibility-state').textContent).toBe('Public');
  });

  it('non-owner has no Manage tab and no Edit details', async () => {
    renderPage(43);
    await screen.findByRole('heading', { name: 'Morgan' });
    await screen.findByRole('button', { name: 'Message' });
    expect(screen.queryByRole('button', { name: 'Manage' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit details' })).toBeNull();
    expect(queryName()).toBeNull();
  });

  it('a stale Manage selection cannot expose the form on a character the viewer does not own', async () => {
    renderPage();
    await openManage();
    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
    expect(field('Name').value).toBe('Taylor');

    // Same page element, new :id → activeTab is still "manage" in state.
    fireEvent.click(screen.getByText('go to 43'));
    await screen.findByRole('heading', { name: 'Morgan' });
    await screen.findByRole('button', { name: 'Message' });
    expect(screen.queryByRole('button', { name: 'Manage' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Edit details' })).toBeNull();
    expect(queryName()).toBeNull();
    expect(screen.queryByRole('region', { name: 'Delete character' })).toBeNull();
  });

  it('ownership is never decided by comparing owner_id (source-level pin)', () => {
    for (const [file, src] of [
      ['CharacterDetail.tsx', characterDetailSource],
      ['CharacterEditDetails.tsx', editDetailsSource],
    ] as const) {
      expect(src, file).not.toMatch(/owner_id\s*[=!]==?/);
      expect(src, file).not.toMatch(/[=!]==?\s*[\w.]*owner_id/);
    }
  });
});

describe('Edit Details — the form', () => {
  it('populates existing values', async () => {
    renderPage();
    await openForm();
    expect(field('Name').value).toBe('Taylor');
    expect(field('Alias').value).toBe('Tay');
    expect(field('Role').value).toBe('detective');
    expect(field('Era').value).toBe('1920s');
    expect(field('Short bio').value).toBe('Short.');
    expect(field('Long bio').value).toBe('Much longer.');
    expect(field('Tags').value).toBe('noir, rain');
    expect((screen.getByLabelText('Public') as HTMLInputElement).checked).toBe(true);
  });

  it('exposes only the approved fields — no identity fields', async () => {
    renderPage();
    await openForm();
    for (const label of ['Name', 'Alias', 'Role', 'Era', 'Short bio', 'Long bio', 'Tags']) {
      expect(field(label), label).toBeTruthy();
    }
    // Scoped to the form: the Manage tab around it now carries a labelled
    // "Identity Canon" section (Phase 5.6), which is a region, not a field.
    const form = field('Name').closest('form') as HTMLFormElement;
    for (const label of [/^age$/i, /species/i, /gender/i, /personality/i, /dna/i, /canon/i, /eye/i, /nose/i, /lips/i, /hair/i, /skin/i, /geometry/i]) {
      expect(within(form).queryByLabelText(label), String(label)).toBeNull();
    }
    // Nothing in the form even mentions the identity values it must not touch.
    expect(within(form).queryByDisplayValue('human')).toBeNull();
    expect(within(form).queryByDisplayValue('34')).toBeNull();
  });

  it('offers Public and Private only — never Friends', async () => {
    renderPage();
    await openForm();
    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(radios.map((r) => r.value).sort()).toEqual(['private', 'public']);
    expect(screen.queryByLabelText(/friends/i)).toBeNull();
    expect(screen.queryByText(/friends/i)).toBeNull();
  });

  it('Private explains that already-shared posts and comments are not removed', async () => {
    renderPage();
    await openForm();
    expect(screen.queryByTestId('private-note')).toBeNull();
    fireEvent.click(screen.getByLabelText('Private'));
    expect((screen.getByLabelText('Private') as HTMLInputElement).checked).toBe(true);
    expect(screen.getByTestId('private-note').textContent).toMatch(
      /does not remove posts or comments they already shared/,
    );
    // And it does not claim the opposite anywhere.
    expect(screen.queryByText(/everything .* becomes private/i)).toBeNull();
  });

  it('cancel discards unsaved edits', async () => {
    renderPage();
    await openForm();
    fireEvent.change(field('Name'), { target: { value: 'Changed' } });
    fireEvent.change(field('Tags'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(updateCharacter).not.toHaveBeenCalled();
    expect(queryName()).toBeNull();
    // Reopen: the original values are back.
    fireEvent.click(screen.getByRole('button', { name: 'Edit details' }));
    expect(field('Name').value).toBe('Taylor');
    expect(field('Tags').value).toBe('noir, rain');
  });
});

describe('Edit Details — saving', () => {
  it('sends only the changed fields, trimmed, with null for cleared values and normalised tags', async () => {
    updateCharacter.mockImplementation((_id: number, patch: Record<string, unknown>) =>
      Promise.resolve({ ...OWNED, ...patch, alias: undefined, tags: 'noir, rain, fog' }),
    );
    renderPage();
    await openForm();
    fireEvent.change(field('Name'), { target: { value: '  Taylor Reed  ' } });
    fireEvent.change(field('Alias'), { target: { value: '   ' } });          // cleared → null
    fireEvent.change(field('Tags'), { target: { value: ' noir ,rain,, fog ' } }); // normalised
    fireEvent.click(saveButton());

    await waitFor(() => expect(updateCharacter).toHaveBeenCalledTimes(1));
    expect(updateCharacter).toHaveBeenCalledWith(42, {
      name: 'Taylor Reed',
      alias: null,
      tags: 'noir, rain, fog',
    });
  });

  it('adopts the server response immediately and refreshes the account after a rename', async () => {
    updateCharacter.mockResolvedValue({ ...OWNED, name: 'Taylor Reed', role: 'inspector' });
    getMe.mockResolvedValueOnce(ME).mockResolvedValueOnce({
      ...ME, active_character: { id: 42, name: 'Taylor Reed' },
    });
    renderPage();
    await openForm();
    fireEvent.change(field('Name'), { target: { value: 'Taylor Reed' } });
    fireEvent.click(saveButton());

    await screen.findByRole('heading', { name: 'Taylor Reed' });
    expect(queryName()).toBeNull(); // form closed
    expect(screen.getByRole('status').textContent).toBe('Saved.');
    // Sidebar source of truth follows the rename.
    await waitFor(() =>
      expect((useAuthStore.getState().user as unknown as { active_character: { name: string } }).active_character.name).toBe('Taylor Reed'),
    );
    expect(useAuthStore.getState().status).toBe('authenticated');
  });

  it('does not touch the account when the name did not change', async () => {
    updateCharacter.mockResolvedValue({ ...OWNED, role: 'inspector' });
    renderPage();
    await openForm();
    fireEvent.change(field('Role'), { target: { value: 'inspector' } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(updateCharacter).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByLabelText('Role')).toBeNull());
    expect(getMe).toHaveBeenCalledTimes(1); // page load only
  });

  it('changing visibility updates the displayed management state', async () => {
    updateCharacter.mockResolvedValue({ ...OWNED, visibility: 'private' });
    renderPage();
    await openForm();
    fireEvent.click(screen.getByLabelText('Private'));
    fireEvent.click(saveButton());

    await waitFor(() => expect(updateCharacter).toHaveBeenCalledWith(42, { visibility: 'private' }));
    await waitFor(() => expect(screen.getByTestId('visibility-state').textContent).toBe('Private'));
  });

  it('a failed save stays open with the server message visible', async () => {
    updateCharacter.mockRejectedValue(new Error('Not authorized to update this character'));
    renderPage();
    await openForm();
    fireEvent.change(field('Role'), { target: { value: 'x' } });
    fireEvent.click(saveButton());

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toContain('Not authorized to update this character'),
    );
    expect(field('Role').value).toBe('x'); // edits are kept for the retry
    expect(saveButton().disabled).toBe(false);
    expect(screen.getByRole('heading', { name: 'Taylor' })).toBeTruthy(); // page unchanged
  });

  it('client validation mirrors the server: an empty name is refused before any request', async () => {
    renderPage();
    await openForm();
    fireEvent.change(field('Name'), { target: { value: '   ' } });
    fireEvent.click(saveButton());
    expect(screen.getByRole('alert').textContent).toMatch(/needs a name/);
    expect(field('Name').getAttribute('aria-invalid')).toBe('true');
    expect(updateCharacter).not.toHaveBeenCalled();
  });

  it('prevents duplicate submission while a save is in flight', async () => {
    let release: (v: Character) => void = () => {};
    updateCharacter.mockImplementation(() => new Promise<Character>((r) => { release = r; }));
    renderPage();
    await openForm();
    fireEvent.change(field('Role'), { target: { value: 'inspector' } });

    fireEvent.click(saveButton());
    await waitFor(() => expect(saveButton().disabled).toBe(true));
    fireEvent.click(saveButton());
    fireEvent.submit(saveButton().closest('form') as HTMLFormElement);
    expect(updateCharacter).toHaveBeenCalledTimes(1);
    // Inputs and Cancel are frozen too.
    expect(field('Role').matches(':disabled')).toBe(true); // via <fieldset disabled>
    expect((screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement).disabled).toBe(true);

    release({ ...OWNED, role: 'inspector' });
    await waitFor(() => expect(screen.queryByLabelText('Role')).toBeNull());
  });
});
