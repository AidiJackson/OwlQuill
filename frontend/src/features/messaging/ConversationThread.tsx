import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Send, Feather } from 'lucide-react';
import { listConversations, listMessages, sendMessage } from './api';
import type { ConversationRead, MessageRead, CharacterSummary } from './types';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';

export default function ConversationThread() {
  const { id } = useParams<{ id: string }>();

  const [conversation, setConversation] = useState<ConversationRead | null>(null);
  const [messages, setMessages] = useState<MessageRead[]>([]);
  const [myCharacters, setMyCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [body, setBody] = useState('');
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!id) return;
    const convId = Number(id);
    Promise.all([
      listConversations(),
      listMessages(convId),
      apiClient.getCharacters(),
    ])
      .then(([convs, msgs, chars]) => {
        const conv = convs.find((c) => c.id === convId);
        if (!conv) throw new Error('Conversation not found');
        setConversation(conv);
        setMessages(msgs);
        setMyCharacters(chars);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        Loading…
      </div>
    );
  }

  if (error || !conversation) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-gray-400">{error || 'Conversation not found.'}</p>
        <Link to="/messages" className="btn btn-secondary text-sm">
          Back to messages
        </Link>
      </div>
    );
  }

  const myCharIds = new Set(myCharacters.map((c) => c.id));
  const other: CharacterSummary = myCharIds.has(conversation.character_a.id)
    ? conversation.character_b
    : conversation.character_a;

  // Determine which of my characters is part of this conversation
  const myParticipantId = myCharIds.has(conversation.character_a.id)
    ? conversation.character_a.id
    : conversation.character_b.id;

  const handleSend = async () => {
    if (!body.trim() || sending) return;
    setSending(true);
    try {
      const msg = await sendMessage(conversation.id, myParticipantId, body.trim());
      setMessages((prev) => [...prev, msg]);
      setBody('');
    } catch {
      // keep body so user can retry
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50 flex-shrink-0">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to="/messages"
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          {other.avatar_url ? (
            <img
              src={other.avatar_url}
              alt={other.name}
              className="w-7 h-7 rounded-full object-cover border border-gray-700"
            />
          ) : (
            <div className="w-7 h-7 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center">
              <Feather className="w-3.5 h-3.5 text-gray-600" />
            </div>
          )}
          <span className="text-sm font-medium text-gray-300 truncate">
            {other.name}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 py-4 space-y-3">
          {messages.length === 0 && (
            <p className="text-center text-xs text-gray-500 py-8">
              No messages yet. Say hello!
            </p>
          )}
          {messages.map((msg) => {
            const isMine = myCharIds.has(msg.sender_character_id);
            return (
              <div
                key={msg.id}
                className={`flex ${isMine ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[75%] rounded-lg px-3 py-2 ${
                    isMine
                      ? 'bg-owl-600/20 border border-owl-600/30 text-gray-200'
                      : 'bg-gray-800 border border-gray-700 text-gray-300'
                  }`}
                >
                  <p className="text-sm whitespace-pre-wrap break-words">{msg.body}</p>
                  <p className="text-[10px] text-gray-500 mt-1">
                    {new Date(msg.created_at).toLocaleTimeString([], {
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                </div>
              </div>
            );
          })}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Compose */}
      <div className="border-t border-gray-800 bg-gray-900/50 flex-shrink-0">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-end gap-2">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Write a message…"
            rows={1}
            className="flex-1 resize-none bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-owl-500"
          />
          <button
            onClick={handleSend}
            disabled={!body.trim() || sending}
            className="btn btn-primary p-2 flex-shrink-0"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
