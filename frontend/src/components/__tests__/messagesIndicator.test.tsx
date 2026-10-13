// @vitest-environment jsdom
/**
 * Phase 7.2B — the Messages indicator is server unread state, not a browser
 * flag.
 *
 * It used to be the localStorage key `ficshon.messages_seen`: lit until the
 * first visit to /messages, then dark forever, whatever arrived. It is now
 * "this account has unread `message_received` notifications", asked of the
 * server with the existing unread-count endpoint, refetched on navigation and
 * when the thread announces it marked a conversation read. No polling.
 */
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { User } from '@/lib/types';

const unread = { all: 0, messages: 0 };
const getUnreadCount = vi.fn((type?: string) =>
  Promise.resolve({ count: type === 'message_received' ? unread.messages : unread.all }),
);
vi.mock('@/lib/apiClient', () => ({
  apiClient: new Proxy(
    {},
    {
      get: (_t, prop) => {
        if (prop === 'hasToken') return () => true;
        if (prop === 'getUnreadCount') return getUnreadCount;
        return () => Promise.resolve([]);
      },
    },
  ),
}));

import Layout from '@/components/Layout';
import { useAuthStore } from '@/lib/store';
import { announceUnreadChanged } from '@/lib/unreadEvents';

const CREATOR = {
  id: 7, email: 'me@test.invalid', username: 'me', created_at: '', updated_at: '',
  character_count: 1, is_admin: false, is_seeder: false, can_create_character: true,
} as unknown as User;

let goTo: (path: string) => void = () => {};
function Navigator() {
  goTo = useNavigate();
  return <p>PAGE</p>;
}

function renderShell(at = '/') {
  useAuthStore.setState({ user: CREATOR, status: 'authenticated' });
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="*" element={<Navigator />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

/** The sidebar's Messages link announces unread state in text. The shell
 *  renders the sidebar twice (desktop and mobile drawer), so count all. */
const sidebarUnread = () => screen.queryAllByText('(unread messages)').length;
const findSidebarUnread = async () => (await screen.findAllByText('(unread messages)')).length;

beforeEach(() => {
  unread.all = 0;
  unread.messages = 0;
  getUnreadCount.mockClear();
  window.localStorage.clear();
});
afterEach(cleanup);

describe('Messages indicator', () => {
  it('asks the server for unread message notifications, by type', async () => {
    renderShell();
    await waitFor(() => expect(getUnreadCount).toHaveBeenCalledWith('message_received'));
    expect(getUnreadCount).toHaveBeenCalledWith();
  });

  it('appears when unread message notifications exist', async () => {
    unread.messages = 2;
    unread.all = 3;
    renderShell();
    expect(await findSidebarUnread()).toBeGreaterThan(0);
  });

  it('stays dark with none', async () => {
    unread.all = 4; // other notification types do not light Messages
    renderShell();
    await waitFor(() => expect(getUnreadCount).toHaveBeenCalledWith('message_received'));
    expect(sidebarUnread()).toBe(0);
  });

  it('is not controlled by localStorage in either direction', async () => {
    // The old "seen" flag set: unread messages still show.
    window.localStorage.setItem('ficshon.messages_seen', 'true');
    unread.messages = 1;
    renderShell();
    expect(await findSidebarUnread()).toBeGreaterThan(0);
    cleanup();

    // The old flag absent (a "never visited" browser): nothing unread, no dot.
    window.localStorage.clear();
    unread.messages = 0;
    renderShell();
    await waitFor(() => expect(getUnreadCount).toHaveBeenCalledWith('message_received'));
    expect(sidebarUnread()).toBe(0);
    // And Layout no longer writes the flag on a /messages visit.
    cleanup();
    renderShell('/messages');
    await waitFor(() => expect(getUnreadCount).toHaveBeenCalled());
    expect(window.localStorage.getItem('ficshon.messages_seen')).toBeNull();
  });

  it('clears when the thread announces the conversation was read, and returns on a new message', async () => {
    unread.messages = 1;
    renderShell();
    expect(await findSidebarUnread()).toBeGreaterThan(0);

    // The thread marked its conversation read.
    unread.messages = 0;
    act(() => announceUnreadChanged());
    await waitFor(() => expect(sidebarUnread()).toBe(0));

    // A new message arrives; the next navigation refetches.
    unread.messages = 1;
    act(() => goTo('/realms'));
    expect(await findSidebarUnread()).toBeGreaterThan(0);
  });

  it('the top-bar Messages icon carries the same state', async () => {
    unread.messages = 1;
    renderShell('/characters/5');
    expect((await screen.findAllByRole('link', { name: 'Messages (unread messages)' })).length).toBeGreaterThan(0);
    unread.messages = 0;
    act(() => announceUnreadChanged());
    await waitFor(() =>
      expect(screen.queryAllByRole('link', { name: 'Messages (unread messages)' })).toHaveLength(0),
    );
    expect(screen.getAllByRole('link', { name: 'Messages' }).length).toBeGreaterThan(0);
  });

  it('a failed count shows no indicator rather than breaking the shell', async () => {
    getUnreadCount.mockImplementation(() => Promise.reject(new Error('offline')));
    renderShell();
    await waitFor(() => expect(getUnreadCount).toHaveBeenCalled());
    expect(sidebarUnread()).toBe(0);
    expect(screen.getAllByText('PAGE').length).toBeGreaterThan(0);
    getUnreadCount.mockImplementation((type?: string) =>
      Promise.resolve({ count: type === 'message_received' ? unread.messages : unread.all }),
    );
  });
});
