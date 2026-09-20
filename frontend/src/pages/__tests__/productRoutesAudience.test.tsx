// @vitest-environment jsdom
/**
 * Polish Phase 6.4 — product routes by audience, with the real pages behind
 * the real guards.
 *
 * routeGuards.test pins what each guard does with a stub child;
 * privilegedRoutes.test pins the two internal tools. This closes the gap in
 * between: the creator workspaces and the Realm Scenes page, mounted at their
 * real paths, for the audiences the product distinguishes. A denied visitor
 * gets the intended destination and the page makes none of its requests.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { User } from '@/lib/types';

const calls: string[] = [];
vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'hasToken') return () => true;
        return (..._a: unknown[]) => {
          calls.push(String(prop));
          const name = String(prop);
          if (name === 'getImageQuota') return Promise.resolve({ unlimited: true, used: 0, limit: null, remaining: null });
          if (name === 'getMe') return Promise.resolve(useAuthStore.getState().user);
          if (name === 'getScene') return Promise.resolve({ id: 5, title: 'A scene', realm_id: 1, visibility: 'PUBLIC', post_count: 0 });
          return Promise.resolve(name.startsWith('list') || name.startsWith('get') ? [] : {});
        };
      },
    },
  ),
}));
vi.mock('@/features/images/components/ReferencePicker', () => ({ default: () => null }));
vi.mock('@/features/images/components/UploadImageButton', () => ({ default: () => null }));
vi.mock('@/features/images/useGenerationJob', () => ({
  useGenerationJob: () => ({
    phase: 'idle', job: null, image: null, error: '', busy: false,
    submit: vi.fn(), resume: vi.fn(), resumeJob: vi.fn(), reset: vi.fn(),
  }),
}));

import { CreatorRoute, WriterRoute } from '@/components/routeGuards';
import EditorStudio from '@/pages/EditorStudio';
import Images from '@/pages/Images';
import SceneDetail from '@/pages/SceneDetail';
import { useAuthStore } from '@/lib/store';

const base = { id: 7, email: 'me@test.invalid', username: 'me', created_at: '', updated_at: '' };
const WANDERER = { ...base, character_count: 0, is_admin: false, is_seeder: false, writer_unlocked: false, can_create_character: false } as unknown as User;
const WRITER_NO_CHARS = { ...base, character_count: 0, is_admin: false, is_seeder: false, writer_unlocked: true, can_create_character: true } as unknown as User;
const CREATOR = { ...base, character_count: 1, is_admin: false, is_seeder: false, can_create_character: true } as unknown as User;
const SEEDER = { ...base, character_count: 0, is_admin: false, is_seeder: true, can_create_character: true } as unknown as User;
const ADMIN = { ...base, character_count: 0, is_admin: true, is_seeder: false, can_create_character: true } as unknown as User;

function renderAt(entry: string, user: User | null) {
  useAuthStore.setState(user ? { user, status: 'authenticated' } : { user: null, status: 'unauthenticated' });
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/login" element={<p>LOGIN PAGE</p>} />
        <Route path="/realms" element={<p>REALMS PAGE</p>} />
        <Route path="/editor-studio" element={<CreatorRoute workspaceName="Editor Studio" description="d"><EditorStudio /></CreatorRoute>} />
        <Route path="/images" element={<CreatorRoute workspaceName="The Image Library" description="d"><Images /></CreatorRoute>} />
        <Route path="/characters/new" element={<WriterRoute><p>CREATION FLOW</p></WriterRoute>} />
        <Route path="/scenes/:sceneId" element={<SceneDetail />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => { calls.length = 0; });
afterEach(cleanup);

describe('Editor Studio (/editor-studio, CreatorRoute)', () => {
  it('Wanderer: the creator-workspace notice, and the page never mounts or loads characters', () => {
    renderAt('/editor-studio', WANDERER);
    expect(screen.getByText('Editor Studio is a creator workspace')).toBeTruthy();
    expect(screen.queryByRole('heading', { name: 'Editor Studio' })).toBeNull();
    expect(calls).toEqual([]);
  });

  it('unauthenticated: sent to login, nothing loaded', () => {
    renderAt('/editor-studio', null);
    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
    expect(calls).toEqual([]);
  });

  it.each([
    ['Writer with no characters', WRITER_NO_CHARS],
    ['creator', CREATOR],
    ['Seeder', SEEDER],
    ['Admin', ADMIN],
  ] as [string, User][])('%s: the page mounts and loads their characters', async (_who, user) => {
    renderAt('/editor-studio', user);
    expect(await screen.findByRole('heading', { name: 'Editor Studio' })).toBeTruthy();
    await waitFor(() => expect(calls).toContain('getCharacters'));
  });

  it('provider controls: absent for creator and Seeder, present for Admin (6.3/6.3B pinned in editorStudio* tests)', async () => {
    for (const [user, expectProvider] of [[CREATOR, false], [SEEDER, false], [ADMIN, true]] as [User, boolean][]) {
      const r = renderAt('/editor-studio', user);
      await screen.findByRole('heading', { name: 'Editor Studio' });
      expect(screen.queryByText(/Provider/) !== null).toBe(expectProvider);
      r.unmount();
    }
  });
});

describe('Image Library (/images, CreatorRoute)', () => {
  it('Wanderer: the notice, no requests', () => {
    renderAt('/images', WANDERER);
    expect(screen.getByText('The Image Library is a creator workspace')).toBeTruthy();
    expect(calls).toEqual([]);
  });

  it('creator: mounts', async () => {
    renderAt('/images', CREATOR);
    expect(await screen.findByText('Image Library')).toBeTruthy();
    await waitFor(() => expect(calls).toContain('getCharacters'));
  });
});

describe('Character creation (/characters/new, WriterRoute)', () => {
  it('Wanderer: the Writer path, not the flow', () => {
    renderAt('/characters/new', WANDERER);
    expect(screen.queryByText('CREATION FLOW')).toBeNull();
    expect(screen.getByText('What the Writer Unlock includes')).toBeTruthy();
  });

  it.each([
    ['Writer', WRITER_NO_CHARS],
    ['Seeder', SEEDER],
    ['Admin', ADMIN],
  ] as [string, User][])('%s: the flow', (_who, user) => {
    renderAt('/characters/new', user);
    expect(screen.getByText('CREATION FLOW')).toBeTruthy();
  });
});

describe('Realm Scenes (/scenes/:id) — founder-only for this programme', () => {
  it.each([
    ['Wanderer', WANDERER],
    ['creator', CREATOR],
  ] as [string, User][])('%s: redirected to the realms list', async (_who, user) => {
    renderAt('/scenes/5', user);
    expect(await screen.findByText('REALMS PAGE')).toBeTruthy();
  });

  it.each([
    ['Seeder', SEEDER],
    ['Admin', ADMIN],
  ] as [string, User][])('%s: the scene mounts', async (_who, user) => {
    renderAt('/scenes/5', user);
    expect(await screen.findByText('A scene')).toBeTruthy();
    expect(calls).toContain('getScene');
  });
});
