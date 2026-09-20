// @vitest-environment jsdom
/**
 * Polish Phase 6.4 — what each audience SEES in primary navigation.
 *
 * The sidebar (every route but /characters/:id) and the cinematic top bar
 * (/characters/:id) are the only product navigation Ficshon has. This pins
 * them by audience so a link cannot quietly appear for, or vanish from, an
 * audience it was not meant for. Privileged tools have no nav entry at all
 * and must stay that way: their doors are on the Image Library, behind the
 * same predicates their routes use.
 *
 * Audiences are the real entitlement helpers' inputs, not a parallel model:
 * Wanderer (no characters, no Writer unlock), creator (owns characters or
 * unlocked), Seeder, Admin, Admin+Seeder.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { User } from '@/lib/types';

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'hasToken') return () => true;
        if (prop === 'getUnreadCount') return () => Promise.resolve({ unread_count: 0 });
        return () => Promise.resolve([]);
      },
    },
  ),
}));

import Layout from '@/components/Layout';
import { useAuthStore } from '@/lib/store';

const base = { id: 7, email: 'me@test.invalid', username: 'me', created_at: '', updated_at: '' };
const WANDERER = { ...base, character_count: 0, is_admin: false, is_seeder: false, writer_unlocked: false, can_create_character: false } as unknown as User;
const WRITER_NO_CHARS = { ...base, character_count: 0, is_admin: false, is_seeder: false, writer_unlocked: true, can_create_character: true } as unknown as User;
const CREATOR = { ...base, character_count: 1, is_admin: false, is_seeder: false, can_create_character: true } as unknown as User;
const SEEDER = { ...base, character_count: 0, is_admin: false, is_seeder: true, can_create_character: true } as unknown as User;
const ADMIN = { ...base, character_count: 0, is_admin: true, is_seeder: false, can_create_character: true } as unknown as User;
const ADMIN_SEEDER = { ...base, character_count: 0, is_admin: true, is_seeder: true, can_create_character: true } as unknown as User;

const CREATOR_TIER: [string, User][] = [
  ['Writer with no characters', WRITER_NO_CHARS],
  ['creator', CREATOR],
  ['Seeder', SEEDER],
  ['Admin', ADMIN],
  ['Admin+Seeder', ADMIN_SEEDER],
];
const FOUNDER_TIER: [string, User][] = [['Seeder', SEEDER], ['Admin', ADMIN], ['Admin+Seeder', ADMIN_SEEDER]];

function renderShell(user: User, at = '/') {
  useAuthStore.setState({ user, status: 'authenticated' });
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="*" element={<p>PAGE</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

/** Every href the shell offers, de-duplicated (desktop and mobile drawers repeat). */
function hrefs(container: HTMLElement): string[] {
  return Array.from(new Set(Array.from(container.querySelectorAll('a[href]')).map((a) => a.getAttribute('href')!)));
}

const PRODUCT_CREATE_LINKS = ['/spaces', '/workspace', '/storylab', '/rp-stories', '/images', '/editor-studio'];
const NEVER_IN_NAV = ['/studio/18-plus', '/admin-creator', '/images/new', '/characters/new'];

beforeEach(() => { vi.clearAllMocks(); });
afterEach(cleanup);

describe('sidebar — Wanderer', () => {
  it('browses: Commons, Realms, Browse Characters, Notifications, My Account — and no creator tools', () => {
    const { container } = renderShell(WANDERER);
    const links = hrefs(container);
    expect(links).toEqual(expect.arrayContaining(['/', '/realms', '/characters', '/notifications', '/profile']));
    expect(screen.getAllByText('Browse Characters').length).toBeGreaterThan(0);
    expect(screen.getAllByText('My Account').length).toBeGreaterThan(0);
    expect(screen.queryByText('Create')).toBeNull();
    for (const href of [...PRODUCT_CREATE_LINKS, '/messages', ...NEVER_IN_NAV]) {
      expect(links).not.toContain(href);
    }
    expect(screen.queryByText('Choose character')).toBeNull(); // founder switcher
  });
});

describe('sidebar — creator tier', () => {
  it.each(CREATOR_TIER)('%s gets the Create section, Messages, Profile — and nothing privileged', (_who, user) => {
    const { container } = renderShell(user);
    const links = hrefs(container);
    expect(links).toEqual(expect.arrayContaining(['/', '/realms', '/characters', '/notifications', '/messages', ...PRODUCT_CREATE_LINKS]));
    expect(screen.getAllByText('Characters').length).toBeGreaterThan(0);
    expect(screen.queryByText('Browse Characters')).toBeNull();
    for (const label of ['Story Spaces', 'WriteSpace', 'StoryLab', 'RP Stories', 'Images', 'Editor Studio', 'Messages', 'Profile']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    for (const href of NEVER_IN_NAV) expect(links).not.toContain(href);
    expect(links.some((h) => h.startsWith('/c/'))).toBe(false);
    expect(screen.queryByText(/18\+ Studio|Admin Creator/)).toBeNull();
  });

  it('only the founder tier gets the character switcher', () => {
    for (const [, user] of [['creator', CREATOR], ['Writer', WRITER_NO_CHARS]] as [string, User][]) {
      const r = renderShell(user);
      expect(screen.queryByText('Choose character')).toBeNull();
      r.unmount();
    }
    for (const [, user] of FOUNDER_TIER) {
      const r = renderShell(user);
      expect(screen.getAllByText('Choose character').length).toBeGreaterThan(0);
      r.unmount();
    }
  });
});

describe('cinematic top bar on /characters/:id', () => {
  it('creator: the Create menu holds exactly the product workspaces', () => {
    renderShell(CREATOR, '/characters/42');
    fireEvent.click(screen.getByRole('button', { name: /Create/ }));
    const menuLinks = PRODUCT_CREATE_LINKS.map((href) =>
      Array.from(document.querySelectorAll(`a[href="${href}"]`)).length > 0,
    );
    expect(menuLinks.every(Boolean)).toBe(true);
    for (const href of NEVER_IN_NAV) {
      expect(document.querySelector(`a[href="${href}"]`)).toBeNull();
    }
  });

  it('Wanderer: no Create menu, Browse Characters label', () => {
    renderShell(WANDERER, '/characters/42');
    expect(screen.queryByRole('button', { name: /Create/ })).toBeNull();
    expect(screen.getAllByText('Browse Characters').length).toBeGreaterThan(0);
  });

  it('the account menu never carries a privileged route', () => {
    renderShell(ADMIN_SEEDER, '/characters/42');
    fireEvent.click(screen.getByRole('button', { name: 'Account' }));
    const menu = screen.getByRole('button', { name: 'Account' }).parentElement as HTMLElement;
    for (const a of within(menu).queryAllByRole('link')) {
      expect(NEVER_IN_NAV).not.toContain(a.getAttribute('href'));
      expect(a.getAttribute('href')!.startsWith('/c/')).toBe(false);
    }
  });
});
