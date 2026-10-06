// @vitest-environment jsdom
/**
 * W-07A — the author's post delete is reachable wherever they meet their post.
 *
 * Commons (Home) and Realm feeds already had PostMenu and must keep it; the
 * single post page and the Character Timeline / Tagged cards gain it. On
 * every surface a non-author gets no control. The anonymous Public Character
 * Home deliberately has none — it is a live projection and needs no code.
 *
 * Every page here is mounted with a permissive apiClient mock: any method not
 * named below resolves to an empty list, which is enough for the surrounding
 * page chrome to render around the post card under test.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Post, User } from '@/lib/types';

const overrides: Record<string, (...a: unknown[]) => unknown> = {};

vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, key: string) => {
        if (key === 'hasToken') return () => true;
        if (key === 'then') return undefined;
        return (...a: unknown[]) => (overrides[key] ? overrides[key](...a) : Promise.resolve([]));
      },
    },
  ),
}));

import PostDetail from '@/pages/PostDetail';
import CharacterDetail from '@/pages/CharacterDetail';
import Home from '@/pages/Home';
import RealmDetail from '@/pages/RealmDetail';
import { useAuthStore } from '@/lib/store';

const ME = { id: 7, email: 'me@test.invalid', username: 'me', character_count: 1 } as User;

const post = (over: Partial<Post> = {}): Post =>
  ({
    id: 55,
    realm_id: 3,
    author_user_id: ME.id,
    character_id: 42,
    character_name: 'Taylor',
    title: null,
    content: 'My words.',
    content_type: 'ic',
    post_kind: 'general',
    provenance: 'user_written',
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    mentions: [],
    comment_count: 3,
    ...over,
  }) as Post;

const REALM = {
  id: 3, name: 'Harbour', slug: 'harbour', is_public: true, is_commons: false,
  owner_id: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  is_member: true, member_count: 2,
};

const renderAt = (path: string, route: string, element: JSX.Element) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={route} element={element} />
      </Routes>
    </MemoryRouter>,
  );

const confirmDelete = async (scope: HTMLElement = document.body) => {
  fireEvent.click(within(scope).getByRole('button', { name: 'Post options' }));
  fireEvent.click(within(scope).getByRole('button', { name: 'Delete' }));
  const dialog = screen.getByRole('dialog');
  expect(
    within(dialog).getByText(
      "This permanently removes the post, its reactions and 3 comments. This can't be undone.",
    ),
  ).toBeTruthy();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
};

beforeEach(() => {
  for (const k of Object.keys(overrides)) delete overrides[k];
  overrides.getMe = () => Promise.resolve(ME);
  overrides.deletePost = () => Promise.resolve(undefined);
  useAuthStore.setState({ user: ME });
});

afterEach(() => {
  cleanup();
  useAuthStore.setState({ user: null });
});

// ── /posts/:postId ─────────────────────────────────────────────────────────

describe('PostDetail', () => {
  it('gives the author the delete menu and a clear deleted state', async () => {
    const deletePost = vi.fn().mockResolvedValue(undefined);
    overrides.getPost = () => Promise.resolve(post());
    overrides.getRealm = () => Promise.resolve(REALM);
    overrides.deletePost = deletePost;
    renderAt('/posts/55', '/posts/:postId', <PostDetail />);

    await screen.findByText('My words.');
    await confirmDelete();

    expect(await screen.findByText('Post deleted.')).toBeTruthy();
    expect(deletePost).toHaveBeenCalledWith(55);
    expect(screen.queryByText('My words.')).toBeNull();
  });

  it('gives a non-author no menu', async () => {
    overrides.getPost = () =>
      Promise.resolve(post({ author_user_id: undefined as unknown as number }));
    renderAt('/posts/55', '/posts/:postId', <PostDetail />);

    await screen.findByText('My words.');
    expect(screen.queryByRole('button', { name: 'Post options' })).toBeNull();
  });
});

// ── Character Timeline and Tagged ─────────────────────────────────────────

const CHARACTER = {
  id: 42, name: 'Taylor', species: 'human', visibility: 'public', is_owner: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
};

const item = (p: Post) => ({
  type: 'post' as const,
  created_at: p.created_at,
  realm_id: p.realm_id,
  realm_name: 'Harbour',
  payload: p as unknown as Record<string, unknown>,
});

describe('CharacterDetail timeline and mentions', () => {
  beforeEach(() => {
    overrides.getCharacter = () => Promise.resolve(CHARACTER);
  });

  it('lets the author delete from the timeline, removing only that entry', async () => {
    overrides.getCharacterPosts = () =>
      Promise.resolve([
        item(post({ id: 55, content: 'First.' })),
        item(post({ id: 56, content: 'Second.' })),
      ]);
    renderAt('/characters/42', '/characters/:id', <CharacterDetail />);

    const first = (await screen.findByText('First.')).closest('article') as HTMLElement;
    await confirmDelete(first);

    await waitFor(() => expect(screen.queryByText('First.')).toBeNull());
    expect(screen.getByText('Second.')).toBeTruthy();
  });

  it('gives a non-author no menu on the timeline', async () => {
    overrides.getCharacter = () => Promise.resolve({ ...CHARACTER, is_owner: false });
    overrides.getCharacterPosts = () =>
      Promise.resolve([item(post({ author_user_id: undefined as unknown as number }))]);
    renderAt('/characters/42', '/characters/:id', <CharacterDetail />);

    await screen.findByText('My words.');
    expect(screen.queryByRole('button', { name: 'Post options' })).toBeNull();
  });

  it('lets the author delete their own post from Tagged, and only their own', async () => {
    overrides.getCharacterMentions = () =>
      Promise.resolve([
        item(post({ id: 60, content: 'I mention you.' })),
        item(post({ id: 61, content: 'Someone else mentions you.', author_user_id: undefined as unknown as number })),
      ]);
    renderAt('/characters/42?tab=mentions', '/characters/:id', <CharacterDetail />);

    fireEvent.click(await screen.findByRole('button', { name: 'Tagged' }));
    const mine = (await screen.findByText('I mention you.')).closest('article') as HTMLElement;
    const theirs = screen.getByText('Someone else mentions you.').closest('article') as HTMLElement;
    expect(within(theirs).queryByRole('button', { name: 'Post options' })).toBeNull();

    await confirmDelete(mine);
    await waitFor(() => expect(screen.queryByText('I mention you.')).toBeNull());
    expect(screen.getByText('Someone else mentions you.')).toBeTruthy();
  });
});

// ── Commons and Realm feeds keep their menu ───────────────────────────────

describe('feeds keep PostMenu for the author only', () => {
  const feed = [
    post({ id: 55, content: 'Mine in the feed.' }),
    post({ id: 56, content: 'Theirs in the feed.', author_user_id: undefined as unknown as number }),
  ];

  const check = async () => {
    await screen.findByText('Mine in the feed.');
    await screen.findByText('Theirs in the feed.');
    expect(screen.getAllByRole('button', { name: 'Post options' })).toHaveLength(1);
  };

  it('Commons', async () => {
    overrides.getFeed = () => Promise.resolve(feed);
    overrides.getRealms = () => Promise.resolve([{ ...REALM, is_commons: true }]);
    renderAt('/', '/', <Home />);
    await check();
    await confirmDelete();
    await waitFor(() => expect(screen.queryByText('Mine in the feed.')).toBeNull());
    expect(screen.getByText('Theirs in the feed.')).toBeTruthy();
  });

  it('Realm', async () => {
    overrides.getRealm = () => Promise.resolve(REALM);
    overrides.getRealmPosts = () => Promise.resolve(feed);
    renderAt('/realms/3', '/realms/:realmId', <RealmDetail />);
    await check();
    await confirmDelete();
    await waitFor(() => expect(screen.queryByText('Mine in the feed.')).toBeNull());
    expect(screen.getByText('Theirs in the feed.')).toBeTruthy();
  });
});
