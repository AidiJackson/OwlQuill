// @vitest-environment jsdom
/**
 * Phase 7.2B — opening a conversation marks its message notifications read.
 *
 * After the thread has loaded, it POSTs the read endpoint once, fire-and-
 * forget, and on success announces that unread state changed so the Messages
 * indicator and the Notifications badge refetch. A failed read never stands in
 * the way of the thread; a thread that failed to load marks nothing.
 */
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const messagingApi = vi.hoisted(() => ({
  listConversations: vi.fn(),
  listMessages: vi.fn(),
  markConversationRead: vi.fn(),
  sendMessage: vi.fn(),
}));
vi.mock('@/features/messaging/api', () => messagingApi);
vi.mock('@/lib/apiClient', () => ({
  apiClient: { getCharacters: () => Promise.resolve([{ id: 1, name: 'Angelo' }]) },
}));

import ConversationThread from '@/features/messaging/ConversationThread';
import { UNREAD_CHANGED_EVENT } from '@/lib/unreadEvents';

const CONVERSATION = {
  id: 12,
  character_a: { id: 1, name: 'Angelo', avatar_url: null },
  character_b: { id: 2, name: 'Mara', avatar_url: null },
  last_message: null,
  updated_at: new Date().toISOString(),
};
const MESSAGES = [
  { id: 100, sender_character_id: 2, body: 'Meet me at the lighthouse.', created_at: new Date().toISOString() },
];

function renderThread(id = '12') {
  return render(
    <MemoryRouter initialEntries={[`/messages/${id}`]}>
      <Routes>
        <Route path="/messages/:id" element={<ConversationThread />} />
      </Routes>
    </MemoryRouter>,
  );
}

const announced = vi.fn();

beforeEach(() => {
  for (const fn of Object.values(messagingApi)) fn.mockReset();
  messagingApi.listConversations.mockResolvedValue([CONVERSATION]);
  messagingApi.listMessages.mockResolvedValue(MESSAGES);
  messagingApi.markConversationRead.mockResolvedValue({ marked: 1 });
  announced.mockReset();
  window.addEventListener(UNREAD_CHANGED_EVENT, announced);
  // jsdom has no layout engine.
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  window.removeEventListener(UNREAD_CHANGED_EVENT, announced);
  cleanup();
});

describe('ConversationThread — mark read', () => {
  it('marks this conversation read once after loading, then announces the change', async () => {
    renderThread();
    expect(await screen.findByText('Meet me at the lighthouse.')).toBeTruthy();
    await waitFor(() => expect(announced).toHaveBeenCalledTimes(1));
    expect(messagingApi.markConversationRead).toHaveBeenCalledTimes(1);
    expect(messagingApi.markConversationRead).toHaveBeenCalledWith(12);
  });

  it('a failed read request does not break the thread and announces nothing', async () => {
    messagingApi.markConversationRead.mockRejectedValue(new Error('HTTP 500'));
    renderThread();
    expect(await screen.findByText('Meet me at the lighthouse.')).toBeTruthy();
    await waitFor(() => expect(messagingApi.markConversationRead).toHaveBeenCalledTimes(1));
    expect(announced).not.toHaveBeenCalled();
    expect(screen.queryByText(/Failed|not found/i)).toBeNull();
  });

  it('a conversation that fails to load is not marked read', async () => {
    messagingApi.listMessages.mockRejectedValue(new Error('Conversation not found.'));
    renderThread();
    expect(await screen.findByText('Conversation not found.')).toBeTruthy();
    expect(messagingApi.markConversationRead).not.toHaveBeenCalled();
  });

  it('a conversation absent from the caller\'s list is not marked read', async () => {
    messagingApi.listConversations.mockResolvedValue([]);
    renderThread('99');
    expect(await screen.findByText('Conversation not found')).toBeTruthy();
    expect(messagingApi.markConversationRead).not.toHaveBeenCalled();
  });
});
