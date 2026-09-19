// @vitest-environment jsdom
/**
 * Characters roster — lifecycle classification and CTAs (Polish Phase 5.8).
 *
 * The roster reads the same "established" signal every other surface reads
 * (visual_locked). Anything not established is "In progress" with Continue
 * setup — the Creator resumes with whatever reference images exist and never
 * remakes a finished one — plus Open when a reference set already exists,
 * since the character page can Establish a complete one. A pre-canon legacy
 * character stays on the roster but is marked Needs attention, never shown
 * as normally ready.
 */
import { cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacters = vi.fn();
const getMe = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'getCharacters') return (...a: unknown[]) => getCharacters(...a);
        if (prop === 'getMe') return (...a: unknown[]) => getMe(...a);
        if (prop === 'hasToken') return () => true;
        return () => Promise.resolve([]);
      },
    },
  ),
}));

import Characters from '@/pages/Characters';
import { useAuthStore } from '@/lib/store';

const FOUNDER = {
  id: 7, email: 'me@test.invalid', username: 'me', character_count: 4,
  is_admin: false, is_seeder: true, writer_unlocked: true,
} as unknown as User;

const base = (id: number, name: string) => ({
  id, name, species: 'human', visibility: 'private', is_owner: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
});
// A/B: no canon, not established.
const DRAFT = { ...base(1, 'Draft Dan'), visual_locked: false, has_identity_canon: false } as unknown as Character;
// C/D: reference images generated (fully or partly), not established.
const UNESTABLISHED = { ...base(2, 'Ready Rae'), visual_locked: false, has_identity_canon: true } as unknown as Character;
// E: established v2.
const ESTABLISHED = { ...base(3, 'Est Eve'), visual_locked: true, has_identity_canon: true } as unknown as Character;
// F: legacy pre-canon.
const LEGACY = { ...base(4, 'Legacy Lou'), visual_locked: true, has_identity_canon: false } as unknown as Character;

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/characters']}>
      <Routes>
        <Route path="/characters" element={<Characters />} />
        <Route path="/characters/new" element={<p>CREATOR</p>} />
        <Route path="/characters/:id" element={<p>DETAIL</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

const cardFor = (name: string) =>
  screen.getByRole('heading', { name }).closest('.card') as HTMLElement;

beforeEach(() => {
  vi.clearAllMocks();
  getMe.mockResolvedValue(FOUNDER);
  getCharacters.mockResolvedValue([DRAFT, UNESTABLISHED, ESTABLISHED, LEGACY]);
  useAuthStore.setState({ user: FOUNDER, status: 'authenticated' });
});
afterEach(cleanup);

describe('Characters roster lifecycle', () => {
  it('files only established characters on the roster; everything else is In progress', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'In progress' });
    const inProgress = screen.getByRole('heading', { name: 'In progress' }).parentElement as HTMLElement;
    expect(within(inProgress).getByRole('heading', { name: 'Draft Dan' })).toBeTruthy();
    expect(within(inProgress).getByRole('heading', { name: 'Ready Rae' })).toBeTruthy();
    expect(within(inProgress).queryByRole('heading', { name: 'Est Eve' })).toBeNull();
    expect(within(inProgress).queryByRole('heading', { name: 'Legacy Lou' })).toBeNull();
    // The old label is gone.
    expect(screen.queryByText('Draft')).toBeNull();
    expect(screen.queryByText(/unlock identity/)).toBeNull();
  });

  it('A/B — a true draft gets Continue setup and no Open', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Draft Dan' });
    const card = cardFor('Draft Dan');
    expect(within(card).getByText('In progress')).toBeTruthy();
    expect(within(card).getByText('Finish setup to establish their Character Canon.')).toBeTruthy();
    expect(within(card).getByRole('button', { name: 'Continue setup' })).toBeTruthy();
    expect(within(card).queryByRole('button', { name: 'Open' })).toBeNull();
    expect(within(card).getByRole('button', { name: 'Delete' })).toBeTruthy();
  });

  it('C/D — a generated-but-unestablished character gets Continue setup and Open', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Ready Rae' });
    const card = cardFor('Ready Rae');
    expect(within(card).getByText('In progress')).toBeTruthy();
    expect(within(card).getByText(/Reference images made — finish setup to establish/)).toBeTruthy();
    expect(within(card).getByRole('button', { name: 'Continue setup' })).toBeTruthy();
    expect(within(card).getByRole('button', { name: 'Open' })).toBeTruthy();
  });

  it('Continue setup resumes the Creator on that character; Open goes to its page', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Ready Rae' });
    within(cardFor('Ready Rae')).getByRole('button', { name: 'Open' }).click();
    await screen.findByText('DETAIL');
    cleanup();
    renderPage();
    await screen.findByRole('heading', { name: 'Ready Rae' });
    within(cardFor('Ready Rae')).getByRole('button', { name: 'Continue setup' }).click();
    await screen.findByText('CREATOR');
  });

  it('E — an established character is a plain roster card with no status badge', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Est Eve' });
    const card = screen.getByRole('heading', { name: 'Est Eve' }).closest('a') as HTMLElement;
    expect(card.getAttribute('href')).toBe('/characters/3');
    expect(within(card).queryByText('Needs attention')).toBeNull();
    expect(within(card).queryByText('In progress')).toBeNull();
  });

  it('F — a legacy pre-canon character stays on the roster but is marked Needs attention', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Legacy Lou' });
    const card = screen.getByRole('heading', { name: 'Legacy Lou' }).closest('a') as HTMLElement;
    expect(within(card).getByText('Needs attention')).toBeTruthy();
    expect(card.getAttribute('href')).toBe('/characters/4');
  });
});
