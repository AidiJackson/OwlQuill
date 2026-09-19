// @vitest-environment jsdom
/**
 * Polish Phase 6.2 — the two retired ordinary-user doors stay shut, and what
 * replaced them is truthful.
 *
 * Quick Create (the roster's inline form with its FakeAI bio button) is
 * gone; the only way to make a character is the Creator, and a Wanderer is
 * shown the Writer path rather than a button that would only land on it.
 * /images/new redirects to the Image Library without ImageNew existing; the
 * post composer's attach modal opens the library on the posting character
 * and never promises the image will come back to the composer by itself.
 */
import { cleanup, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Character, User } from '@/lib/types';

const getCharacters = vi.fn();
const getMe = vi.fn();
const listMyCharacterImages = vi.fn();

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'getCharacters') return (...a: unknown[]) => getCharacters(...a);
        if (prop === 'getMe') return (...a: unknown[]) => getMe(...a);
        if (prop === 'listMyCharacterImages') return (...a: unknown[]) => listMyCharacterImages(...a);
        if (prop === 'hasToken') return () => true;
        return () => Promise.resolve([]);
      },
    },
  ),
}));

import Characters from '@/pages/Characters';
import AttachImageModal from '@/components/AttachImageModal';
import { useAuthStore } from '@/lib/store';
import charactersSource from '../Characters.tsx?raw';
import appSource from '../../App.tsx?raw';
import apiClientSource from '../../lib/apiClient.ts?raw';
import attachModalSource from '../../components/AttachImageModal.tsx?raw';

const base = { id: 7, email: 'me@test.invalid', username: 'me', created_at: '', updated_at: '' };
const WANDERER = { ...base, character_count: 0, is_admin: false, is_seeder: false, can_create_character: false } as unknown as User;
const WRITER = { ...base, character_count: 0, is_admin: false, is_seeder: false, writer_unlocked: true, can_create_character: true } as unknown as User;
const SEEDER = { ...base, character_count: 0, is_admin: false, is_seeder: true, can_create_character: true } as unknown as User;
const ADMIN = { ...base, character_count: 0, is_admin: true, is_seeder: false, can_create_character: true } as unknown as User;

const DRAFT = {
  id: 5, name: 'Sketchy', species: 'human', visibility: 'private', is_owner: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  visual_locked: false, has_identity_canon: false,
} as unknown as Character;

function renderRoster() {
  return render(
    <MemoryRouter initialEntries={['/characters']}>
      <Routes>
        <Route path="/characters" element={<Characters />} />
        <Route path="/characters/new" element={<p>CREATOR</p>} />
        <Route path="/become-a-writer" element={<p>BECOME A WRITER</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  getCharacters.mockResolvedValue([]);
  listMyCharacterImages.mockResolvedValue([]);
});
afterEach(cleanup);

describe('Characters — Quick Create is retired', () => {
  it('renders no Quick Create, no inline form, no AI bio button, for any audience', async () => {
    for (const user of [WANDERER, WRITER, SEEDER, ADMIN]) {
      getMe.mockResolvedValue(user);
      useAuthStore.setState({ user, status: 'authenticated' });
      renderRoster();
      // Owners get "My Characters"; a Wanderer gets the public directory.
      await screen.findByRole('heading', { name: user === WANDERER ? 'Characters' : 'My Characters' });
      expect(screen.queryByText('Quick Create')).toBeNull();
      expect(screen.queryByText(/AI Suggest Bio/)).toBeNull();
      expect(screen.queryByLabelText(/Short Bio/)).toBeNull();
      cleanup();
    }
    // And the source no longer carries the flow or its native alerts.
    expect(charactersSource).not.toMatch(/Quick Create|handleGenerateBio|handleCreateCharacter|generateCharacterBio|showCreateForm/);
    // No native dialog CALLS remain (a Phase 5.3 comment still names the
    // pair it replaced; comments are not calls).
    const codeLines = charactersSource.split('\n').filter((l) => !l.trim().startsWith('//'));
    expect(codeLines.join('\n')).not.toMatch(/\b(window\.)?(alert|confirm|prompt)\(/);
  });

  it('a Writer with no characters is offered the Creator (header and empty state)', async () => {
    getMe.mockResolvedValue(WRITER);
    useAuthStore.setState({ user: WRITER, status: 'authenticated' });
    renderRoster();
    await screen.findByRole('heading', { name: 'My Characters' });
    expect(screen.getByRole('button', { name: '+ New Character' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Create character' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Become a Writer' })).toBeNull();
    screen.getByRole('button', { name: '+ New Character' }).click();
    await screen.findByText('CREATOR');
  });

  it('a Wanderer gets the public directory — no create button, no retired shortcut', async () => {
    // Wanderers never reach the management surface at all (canUseCreatorTools
    // false → CharacterDirectory), so the retired form was the only creation
    // control they could ever have seen here. The Writer path is the nav's
    // Become a Writer / the WriterRoute gate on /characters/new.
    getMe.mockResolvedValue(WANDERER);
    useAuthStore.setState({ user: WANDERER, status: 'authenticated' });
    renderRoster();
    await screen.findByRole('heading', { name: 'Characters' });
    expect(screen.queryByRole('button', { name: /New Character|Create character|Quick Create/ })).toBeNull();
    expect(screen.queryByRole('form')).toBeNull();
  });

  it('a creator whose account may not create (server says so) is shown the Writer path, not a Creator button', async () => {
    // Defensive branch on the management surface: the server's
    // can_create_character is authoritative, so a writer-tools account it
    // refuses gets the existing Writer path rather than a WriterRoute bounce.
    const REFUSED = { ...WRITER, can_create_character: false } as unknown as User;
    getMe.mockResolvedValue(REFUSED);
    useAuthStore.setState({ user: REFUSED, status: 'authenticated' });
    renderRoster();
    await screen.findByRole('heading', { name: 'My Characters' });
    expect(screen.queryByRole('button', { name: '+ New Character' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Create character' })).toBeNull();
    const cta = screen.getAllByRole('button', { name: 'Become a Writer' });
    expect(cta.length).toBeGreaterThan(0);
    cta[0].click();
    await screen.findByText('BECOME A WRITER');
  });

  it('seeder and admin keep the unlimited create action', async () => {
    for (const user of [SEEDER, ADMIN]) {
      getMe.mockResolvedValue(user);
      useAuthStore.setState({ user, status: 'authenticated' });
      renderRoster();
      await screen.findByRole('heading', { name: 'My Characters' });
      expect(screen.getByRole('button', { name: '+ New Character' })).toBeTruthy();
      expect(screen.queryByText(/Beta limit/)).toBeNull();
      cleanup();
    }
  });

  it('a character the old form created (no canon, no DNA) is still an In progress row with Continue setup', async () => {
    getMe.mockResolvedValue(WRITER);
    getCharacters.mockResolvedValue([DRAFT]);
    useAuthStore.setState({ user: WRITER, status: 'authenticated' });
    renderRoster();
    await screen.findByRole('heading', { name: 'In progress' });
    const card = screen.getByRole('heading', { name: 'Sketchy' }).closest('.card') as HTMLElement;
    expect(within(card).getByRole('button', { name: 'Continue setup' })).toBeTruthy();
    expect(within(card).getByRole('button', { name: 'Delete' })).toBeTruthy();
  });
});

describe('/images/new is retired', () => {
  it('the route is a replace-redirect to /images and ImageNew no longer exists', () => {
    expect(appSource).toMatch(/path="\/images\/new" element=\{<Navigate to="\/images" replace \/>\}/);
    expect(appSource).not.toMatch(/ImageNew/);
    // The file is gone, not merely unreferenced.
    const pages = import.meta.glob('../*.tsx');
    expect(Object.keys(pages).some((k) => k.endsWith('/ImageNew.tsx'))).toBe(false);
  });

  it('the client no longer carries the retired endpoints', () => {
    expect(apiClientSource).not.toMatch(/generateLibraryImage|generateCharacterBio|generateScene\(|\/images\/generate|\/ai\//);
  });
});

describe('AttachImageModal after retirement', () => {
  function renderModal(characterId: number | null) {
    return render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<AttachImageModal open onClose={() => {}} onSelect={() => {}} characterId={characterId} />} />
          <Route path="/images" element={<p>IMAGE LIBRARY</p>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it('with no images: opens the library on the posting character and says to come back', async () => {
    renderModal(42);
    const link = await screen.findByRole('link', { name: 'Open Image Library' });
    expect(link.getAttribute('href')).toBe('/images?characterId=42');
    expect(screen.getByText(/Make one in the Image Library, then come back and attach it here/)).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Generate an image|Generate new/);
    expect(document.body.innerHTML).not.toMatch(/images\/new/);
  });

  it('with images: the footer link also opens the library on the posting character', async () => {
    listMyCharacterImages.mockResolvedValue([{ id: 1, url: '/a.png', kind: 'scene_only', prompt_summary: 'a' }]);
    renderModal(42);
    const link = await screen.findByRole('link', { name: 'Open Image Library' });
    expect(link.getAttribute('href')).toBe('/images?characterId=42');
  });

  it('with no posting character: asks the user to choose one and links nowhere', () => {
    renderModal(null);
    expect(screen.getByText(/Choose which character you.re posting as first/)).toBeTruthy();
    expect(screen.queryByRole('link')).toBeNull();
    expect(attachModalSource).not.toMatch(/images\/new/);
  });
});
