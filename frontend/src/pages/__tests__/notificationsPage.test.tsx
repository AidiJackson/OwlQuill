// @vitest-environment jsdom
/**
 * The Notifications page and the post destination it leads to — Polish
 * Phase 7.1.
 *
 * The page renders each row from the typed contract (never a raw type
 * string), as real interactive markup (a link when there is somewhere to go,
 * a button otherwise), marks it read on activation without letting that
 * request stand in the way of navigation, and tells the truth about an empty
 * list versus a failed load. The post page shows exactly the post the server
 * returns, and a graceful notice — never a blank screen, never the cached
 * preview — when it does not.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Notification, Post, User } from '@/lib/types';

const api = {
  getNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
  getPost: vi.fn(),
  getRealm: vi.fn(),
  getCharacters: vi.fn(),
  getPostComments: vi.fn(),
  getPostReactions: vi.fn(),
};
vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'hasToken') return () => true;
        if (prop in api) return api[prop as keyof typeof api];
        return () => Promise.resolve([]);
      },
    },
  ),
}));

import Notifications from '@/pages/Notifications';
import PostDetail from '@/pages/PostDetail';
import { useAuthStore } from '@/lib/store';

const ME = {
  id: 7, email: 'me@test.invalid', username: 'me', created_at: '', updated_at: '',
  character_count: 1, is_admin: false, is_seeder: false,
} as unknown as User;

const NOW = new Date().toISOString();

function row(over: Partial<Notification> & { payload?: string }): Notification {
  return { id: 1, type: 'mention', is_read: false, created_at: NOW, ...over };
}

const V71 = JSON.stringify({
  post_id: 42, realm_id: 7, realm_name: 'The Glass Market',
  author_character_id: 3, author_character_name: 'Bram',
  mentioned_character_id: 9, mentioned_character_name: 'Elowen', mention_text: '@Elowen',
  post_preview: 'At the gate, Elowen turned and the market went quiet.',
});

function renderNotifications() {
  return render(
    <MemoryRouter initialEntries={['/notifications']}>
      <Routes>
        <Route path="/notifications" element={<Notifications />} />
        <Route path="/posts/:postId" element={<p>POST PAGE</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
  api.markNotificationRead.mockResolvedValue(undefined);
  api.markAllNotificationsRead.mockResolvedValue(undefined);
  api.getCharacters.mockResolvedValue([]);
  api.getPostComments.mockResolvedValue([]);
  api.getPostReactions.mockResolvedValue([]);
  useAuthStore.setState({ user: ME, status: 'authenticated' });
});
afterEach(cleanup);

describe('Notifications page — rendering', () => {
  it('character_tagged (W-10A) says who featured which character and goes to the exact post', async () => {
    const tagged = JSON.stringify({
      post_id: 77, realm_id: 7, realm_name: 'The Glass Market',
      author_character_id: 3, author_character_name: 'Bram',
      tagged_character_id: 9, tagged_character_name: 'Elowen',
      post_preview: 'Elowen watched the ships.',
    });
    api.getNotifications.mockResolvedValue([row({ type: 'character_tagged', payload: tagged })]);
    renderNotifications();
    const link = await screen.findByRole('link', { name: /Bram featured Elowen in a post in The Glass Market/ });
    expect(link.getAttribute('href')).toBe('/posts/77');
    fireEvent.click(link);
    expect(await screen.findByText('POST PAGE')).toBeTruthy();
    expect(api.markNotificationRead).toHaveBeenCalledWith(1);
  });

  it('mention renders character-first copy with the recipient character and realm', async () => {
    api.getNotifications.mockResolvedValue([row({ payload: V71 })]);
    renderNotifications();
    const link = await screen.findByRole('link', { name: /Bram mentioned Elowen in The Glass Market/ });
    expect(link.getAttribute('href')).toBe('/posts/42');
    expect(within(link).getByText('Bram')).toBeTruthy();
    expect(within(link).getByText(/the market went quiet/)).toBeTruthy();
    expect(within(link).getByText('Unread.')).toBeTruthy();
  });

  it('legacy Sprint 33 payload still renders, from the @handle', async () => {
    const legacy = JSON.stringify({ post_id: 11, author_character_name: 'Bram', mention_text: '@Elowen', post_preview: 'old', target_type: 'character' });
    api.getNotifications.mockResolvedValue([row({ payload: legacy })]);
    renderNotifications();
    const link = await screen.findByRole('link', { name: /Bram mentioned Elowen in a post/ });
    expect(link.getAttribute('href')).toBe('/posts/11');
  });

  it('pre-33 payload with an account username never shows it', async () => {
    api.getNotifications.mockResolvedValue([row({ payload: JSON.stringify({ post_id: 5, author_username: 'aidan_j', mention_text: '@Elowen' }) })]);
    renderNotifications();
    await screen.findByRole('link', { name: /Someone mentioned Elowen in a post/ });
    expect(screen.queryByText(/aidan_j/)).toBeNull();
  });

  it('malformed payload falls back to a truthful sentence and a non-navigating button', async () => {
    api.getNotifications.mockResolvedValue([row({ payload: '{not json' })]);
    renderNotifications();
    const button = await screen.findByRole('button', { name: /Someone mentioned one of your characters in a post/ });
    expect(button.tagName).toBe('BUTTON');
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('an unknown type never exposes the raw type string', async () => {
    api.getNotifications.mockResolvedValue([row({ type: 'story_space_invite', payload: JSON.stringify({ space_id: 3 }) })]);
    renderNotifications();
    await screen.findByRole('button', { name: /Something new happened around one of your characters/ });
    expect(screen.queryByText(/story_space_invite/i)).toBeNull();
    expect(screen.queryByText(/story space invite/i)).toBeNull();
  });

  it('empty state', async () => {
    api.getNotifications.mockResolvedValue([]);
    renderNotifications();
    expect(await screen.findByText('You have no notifications yet.')).toBeTruthy();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('loading state is announced', () => {
    api.getNotifications.mockReturnValue(new Promise(() => undefined));
    renderNotifications();
    expect(screen.getByRole('status', { name: /Loading notifications/ })).toBeTruthy();
  });

  it('a failed load is an error with a retry, not a fake empty list', async () => {
    api.getNotifications.mockRejectedValueOnce(new Error('HTTP 500')).mockResolvedValueOnce([row({ payload: V71 })]);
    renderNotifications();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/Couldn't load your notifications/);
    expect(screen.queryByText('You have no notifications yet.')).toBeNull();

    fireEvent.click(within(alert).getByRole('button', { name: 'Try again' }));
    await screen.findByRole('link', { name: /Bram mentioned Elowen/ });
    expect(api.getNotifications).toHaveBeenCalledTimes(2);
  });
});

describe('Notifications page — activation', () => {
  it('click marks read and navigates to the post destination', async () => {
    api.getNotifications.mockResolvedValue([row({ id: 77, payload: V71 })]);
    renderNotifications();
    const link = await screen.findByRole('link', { name: /Bram mentioned Elowen/ });
    fireEvent.click(link);
    expect(api.markNotificationRead).toHaveBeenCalledWith(77);
    expect(await screen.findByText('POST PAGE')).toBeTruthy();
  });

  it('a failed mark-read does not block reaching the content', async () => {
    api.markNotificationRead.mockRejectedValue(new Error('HTTP 500'));
    api.getNotifications.mockResolvedValue([row({ id: 78, payload: V71 })]);
    renderNotifications();
    fireEvent.click(await screen.findByRole('link', { name: /Bram mentioned Elowen/ }));
    expect(await screen.findByText('POST PAGE')).toBeTruthy();
  });

  it('an already-read row is not marked again', async () => {
    api.getNotifications.mockResolvedValue([row({ id: 79, is_read: true, payload: V71 })]);
    renderNotifications();
    fireEvent.click(await screen.findByRole('link', { name: /Bram mentioned Elowen/ }));
    expect(api.markNotificationRead).not.toHaveBeenCalled();
  });

  it('rows are keyboard-reachable interactive elements', async () => {
    api.getNotifications.mockResolvedValue([row({ id: 1, payload: V71 }), row({ id: 2, payload: '{}' })]);
    renderNotifications();
    const link = await screen.findByRole('link', { name: /Bram mentioned Elowen/ });
    const button = screen.getByRole('button', { name: /Someone mentioned one of your characters/ });
    link.focus();
    expect(document.activeElement).toBe(link);
    button.focus();
    expect(document.activeElement).toBe(button);
    // the old implementation: a div with onClick and nothing else
    expect(document.querySelectorAll('div[onclick]').length).toBe(0);
  });

  it('mark all read updates every row; a failure is reported', async () => {
    api.getNotifications.mockResolvedValue([row({ id: 1, payload: V71 }), row({ id: 2, payload: V71 })]);
    renderNotifications();
    await screen.findAllByRole('link');
    expect(screen.getAllByText('Unread.').length).toBe(2);
    fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    await waitFor(() => expect(screen.queryAllByText('Unread.').length).toBe(0));
    expect(screen.queryByRole('button', { name: 'Mark all read' })).toBeNull();

    cleanup();
    api.markAllNotificationsRead.mockRejectedValue(new Error('HTTP 500'));
    api.getNotifications.mockResolvedValue([row({ id: 3, payload: V71 })]);
    renderNotifications();
    await screen.findByRole('link');
    fireEvent.click(screen.getByRole('button', { name: 'Mark all read' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Couldn't mark everything read/);
    expect(screen.getAllByText('Unread.').length).toBe(1);
  });
});

// ── the destination ──────────────────────────────────────────────────────────

const POST: Post = {
  id: 42, realm_id: 7, author_user_id: 3, character_id: 3, character_name: 'Bram',
  content: 'At the gate, @Elowen turned and the market went quiet.', content_type: 'ic',
  post_kind: 'general', created_at: NOW, updated_at: NOW, mentions: [], comment_count: 0,
};

function renderPost(path = '/posts/42') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/posts/:postId" element={<PostDetail />} />
        <Route path="/notifications" element={<p>NOTIFICATIONS</p>} />
        <Route path="/" element={<p>COMMONS</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('/posts/:postId — the destination', () => {
  it('renders the post the server returns, with its realm and comments open', async () => {
    api.getPost.mockResolvedValue(POST);
    api.getRealm.mockResolvedValue({ id: 7, name: 'The Glass Market', is_public: true, owner_id: 1, slug: 'glass', created_at: NOW, updated_at: NOW });
    renderPost();
    expect(await screen.findByText(/the market went quiet/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Bram' })).toBeTruthy();
    expect((await screen.findAllByText('The Glass Market')).length).toBeGreaterThan(0);
    expect(api.getPost).toHaveBeenCalledWith(42);
    await waitFor(() => expect(api.getPostComments).toHaveBeenCalledWith(42));
  });

  it('a deleted or inaccessible post: graceful notice, ways back, no blank screen', async () => {
    api.getPost.mockRejectedValue(new Error('Post not found'));
    renderPost('/posts/999');
    const notice = await screen.findByRole('status');
    expect(notice.textContent).toMatch(/This post isn't available/);
    expect(notice.textContent).toMatch(/private Realm/);
    expect(screen.getByRole('link', { name: 'Back to notifications' }).getAttribute('href')).toBe('/notifications');
    expect(screen.getByRole('link', { name: 'Go to the Commons' }).getAttribute('href')).toBe('/');
    expect(screen.queryByRole('article')).toBeNull();
  });

  it('a non-404 failure is an error, not "not available"', async () => {
    api.getPost.mockRejectedValue(new Error('HTTP 500'));
    renderPost();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/Couldn't load this post/);
    expect(screen.getByRole('link', { name: 'Back to notifications' })).toBeTruthy();
  });

  it('a nonsense id never calls the server', async () => {
    renderPost('/posts/abc');
    expect((await screen.findByRole('status')).textContent).toMatch(/This post isn't available/);
    expect(api.getPost).not.toHaveBeenCalled();
  });

  it('the realm being unreachable does not hide the post', async () => {
    api.getPost.mockResolvedValue(POST);
    api.getRealm.mockRejectedValue(new Error('Realm not found'));
    renderPost();
    expect(await screen.findByText(/the market went quiet/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Commons' })).toBeTruthy();
  });
});
