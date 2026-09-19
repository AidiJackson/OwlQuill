// @vitest-environment jsdom
/**
 * Deep links to the two internal tools — Polish Phase 6.1.
 *
 * The real pages, behind the real guards, at the real paths. An unauthorised
 * visitor is redirected to the Image Library before the page mounts, so not
 * one of the page's requests is made (the apiClient proxy records every
 * call). An authorised visitor gets the page. App.tsx is pinned to use these
 * guards for these routes.
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
          return Promise.resolve(String(prop).startsWith('list') || String(prop).startsWith('get') ? [] : {});
        };
      },
    },
  ),
}));
// The Admin Creator's generation hook polls; keep it inert.
vi.mock('@/features/images/useGenerationJob', () => ({
  useGenerationJob: () => ({
    phase: 'idle', job: null, image: null, error: '', busy: false,
    submit: vi.fn(), resume: vi.fn(), resumeJob: vi.fn(), reset: vi.fn(),
  }),
}));

import { AdminRoute, FounderRoute } from '@/components/routeGuards';
import Studio18Plus from '@/pages/Studio18Plus';
import AdminCreator from '@/pages/AdminCreator';
import { useAuthStore } from '@/lib/store';
import appSource from '../../App.tsx?raw';
import studioSource from '../Studio18Plus.tsx?raw';

const base = { id: 7, email: 'me@test.invalid', username: 'me', created_at: '', updated_at: '' };
const ORDINARY = { ...base, character_count: 1, is_admin: false, is_seeder: false } as unknown as User;
const SEEDER = { ...base, character_count: 1, is_admin: false, is_seeder: true } as unknown as User;
const ADMIN = { ...base, character_count: 0, is_admin: true, is_seeder: false } as unknown as User;

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/login" element={<p>LOGIN PAGE</p>} />
        <Route path="/images" element={<p>IMAGE LIBRARY</p>} />
        <Route path="/studio/18-plus" element={<AdminRoute><Studio18Plus /></AdminRoute>} />
        <Route path="/admin-creator" element={<FounderRoute><AdminCreator /></FounderRoute>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => { calls.length = 0; });
afterEach(cleanup);

describe('/studio/18-plus deep link', () => {
  it('ordinary creator: lands on the Image Library; the studio never mounts and makes no request', async () => {
    useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
    renderAt('/studio/18-plus?characterId=42');
    expect(screen.getByText('IMAGE LIBRARY')).toBeTruthy();
    expect(screen.queryByText('18+ Studio')).toBeNull();
    await new Promise((r) => setTimeout(r, 0));
    expect(calls).toEqual([]);
  });

  it('seeder: denied the same way', async () => {
    useAuthStore.setState({ user: SEEDER, status: 'authenticated' });
    renderAt('/studio/18-plus');
    expect(screen.getByText('IMAGE LIBRARY')).toBeTruthy();
    await new Promise((r) => setTimeout(r, 0));
    expect(calls).toEqual([]);
  });

  it('unauthenticated: sent to login, no request', () => {
    useAuthStore.setState({ user: null, status: 'unauthenticated' });
    renderAt('/studio/18-plus');
    expect(screen.getByText('LOGIN PAGE')).toBeTruthy();
    expect(calls).toEqual([]);
  });

  it('admin: the studio mounts and loads its characters', async () => {
    useAuthStore.setState({ user: ADMIN, status: 'authenticated' });
    renderAt('/studio/18-plus');
    await screen.findByRole('heading', { name: '18+ Studio' });
    await waitFor(() => expect(calls).toContain('getCharacters'));
  });
});

describe('/admin-creator deep link', () => {
  it('ordinary creator: lands on the Image Library; the tool never mounts and makes no request', async () => {
    useAuthStore.setState({ user: ORDINARY, status: 'authenticated' });
    renderAt('/admin-creator');
    expect(screen.getByText('IMAGE LIBRARY')).toBeTruthy();
    expect(screen.queryByText('Not available')).toBeNull();
    expect(screen.queryByText('Admin Creator')).toBeNull();
    await new Promise((r) => setTimeout(r, 0));
    expect(calls).toEqual([]);
  });

  it('seeder: the tool mounts (founder capability)', async () => {
    useAuthStore.setState({ user: SEEDER, status: 'authenticated' });
    renderAt('/admin-creator');
    await screen.findByRole('heading', { name: 'Admin Creator' });
  });

  it('admin: the tool mounts', async () => {
    useAuthStore.setState({ user: ADMIN, status: 'authenticated' });
    renderAt('/admin-creator');
    await screen.findByRole('heading', { name: 'Admin Creator' });
  });
});

describe('App route table (source pins)', () => {
  it('/studio/18-plus is wrapped in AdminRoute and /admin-creator in FounderRoute', () => {
    expect(appSource).toMatch(/path="\/studio\/18-plus"[\s\S]{0,200}<AdminRoute>\s*<Studio18Plus \/>\s*<\/AdminRoute>/);
    expect(appSource).toMatch(/path="\/admin-creator"[\s\S]{0,200}<FounderRoute>\s*<AdminCreator \/>\s*<\/FounderRoute>/);
    // Neither is a CreatorRoute any more.
    expect(appSource).not.toMatch(/CreatorRoute workspaceName="The 18\+ Studio"/);
    expect(appSource).not.toMatch(/CreatorRoute workspaceName="Admin Creator"/);
  });

  it('Studio18Plus no longer carries its own redirect — the route owns access', () => {
    expect(studioSource).not.toMatch(/<Navigate/);
  });
});
