import type { ConversationRead, MessageRead } from './types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('token');
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers as Record<string, string>) },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'An error occurred' }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export function createOrGetConversation(
  fromCharacterId: number,
  toCharacterId: number,
): Promise<ConversationRead> {
  return request('/messages/conversations', {
    method: 'POST',
    body: JSON.stringify({
      from_character_id: fromCharacterId,
      to_character_id: toCharacterId,
    }),
  });
}

export function listConversations(): Promise<ConversationRead[]> {
  return request('/messages/conversations');
}

export function listMessages(conversationId: number): Promise<MessageRead[]> {
  return request(`/messages/conversations/${conversationId}/messages`);
}

export function sendMessage(
  conversationId: number,
  senderCharacterId: number,
  body: string,
): Promise<MessageRead> {
  return request(`/messages/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ sender_character_id: senderCharacterId, body }),
  });
}
