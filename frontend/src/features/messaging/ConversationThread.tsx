import { useEffect, useRef, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { ArrowLeft, Send, Feather } from 'lucide-react';
import { listConversations, listMessages, sendMessage } from './api';
import type { ConversationRead, MessageRead, CharacterSummary } from './types';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';

const CAP_PX = 160;

function adjustHeight(el: HTMLTextAreaElement) {
  el.style.height = 'auto';
  const natural = el.scrollHeight;
  el.style.height = Math.min(natural, CAP_PX) + 'px';
  el.style.overflowY = natural > CAP_PX ? 'auto' : 'hidden';
}

export default function ConversationThread() {
  const { id } = useParams<{ id: string }>();

  const [conversation, setConversation] = useState<ConversationRead | null>(null);
  const [messages, setMessages] = useState<MessageRead[]>([]);
  const [myCharacters, setMyCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [body, setBody] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const isFirstLoadRef = useRef(true);

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
    if (!bottomRef.current) return;

    if (isFirstLoadRef.current) {
      // First render: jump instantly to bottom
      bottomRef.current.scrollIntoView({ behavior: 'auto' });
      isFirstLoadRef.current = false;
    } else {
      // New messages: smooth scroll
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages]);

  useEffect(() => {
    if (textareaRef.current) adjustHeight(textareaRef.current);
  }, [body]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-ink-3">
        Loading…
      </div>
    );
  }

  if (error || !conversation) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-ink-2">{error || 'Conversation not found.'}</p>
        <Link to="/messages" className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors">
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
    setSendError('');
    try {
      const msg = await sendMessage(conversation.id, myParticipantId, body.trim());
      setMessages((prev) => [...prev, msg]);
      setBody('');
    } catch {
      setSendError('Message failed to send. Tap send to retry.');
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
      <div className="border-b border-edge bg-surface/60 flex-shrink-0">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to="/messages"
            className="text-ink-3 hover:text-ink transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <Link
            to={`/characters/${other.id}`}
            className="flex items-center gap-3 min-w-0 hover:opacity-80 transition-opacity"
          >
            {other.avatar_url ? (
              <img
                src={other.avatar_url}
                alt={other.name}
                className="w-10 h-10 rounded-full object-cover border border-edge-md flex-shrink-0"
              />
            ) : (
              <div className="w-10 h-10 rounded-full bg-surface-elevated border border-edge flex items-center justify-center flex-shrink-0">
                <Feather className="w-4 h-4 text-ink-3" />
              </div>
            )}
            <div className="min-w-0">
              <h1 className="text-sm font-semibold text-ink truncate">
                {other.name}
              </h1>
              <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3">Character</p>
            </div>
          </Link>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 py-4 space-y-3">
          {messages.length === 0 && (
            <p className="text-center text-xs text-ink-3 py-8">
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
                  className={`max-w-[75%] rounded-2xl px-3.5 py-2.5 ${
                    isMine
                      ? 'bg-gem-soft text-ink'
                      : 'bg-surface-elevated text-ink-2'
                  }`}
                >
                  <p className="text-sm whitespace-pre-wrap break-words">{msg.body}</p>
                  <p className="font-mono text-[10px] text-ink-3 mt-1">
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
      <div className="border-t border-edge bg-surface/60 flex-shrink-0">
        {sendError && (
          <div className="max-w-2xl mx-auto px-4 pt-2">
            <p className="text-xs text-red-400">{sendError}</p>
          </div>
        )}
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-end gap-2">
          <textarea
            ref={textareaRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Write a message…"
            rows={1}
            className="flex-1 resize-none overflow-y-hidden bg-surface-elevated border border-edge rounded-xl px-3.5 py-2.5 text-sm text-ink placeholder:text-ink-3 focus:outline-none focus:border-gem/50"
          />
          <button
            onClick={handleSend}
            disabled={!body.trim() || sending}
            className="p-2.5 rounded-xl bg-gem hover:bg-gem/90 text-gem-ink transition-colors disabled:opacity-40 flex-shrink-0"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
