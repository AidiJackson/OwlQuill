import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, MessageSquare, Feather } from 'lucide-react';
import { listConversations } from './api';
import type { ConversationRead } from './types';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';

export default function ConversationsList() {
  const [conversations, setConversations] = useState<ConversationRead[]>([]);
  const [myCharacters, setMyCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([listConversations(), apiClient.getCharacters()])
      .then(([convs, chars]) => {
        setConversations(convs);
        setMyCharacters(chars);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, []);

  const myCharIds = new Set(myCharacters.map((c) => c.id));

  function otherCharacter(conv: ConversationRead) {
    return myCharIds.has(conv.character_a.id) ? conv.character_b : conv.character_a;
  }

  function formatTime(iso: string) {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60_000) return 'now';
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
    return d.toLocaleDateString();
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to="/" className="text-gray-400 hover:text-gray-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300">Messages</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6">
        {error && (
          <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 mb-4">
            {error}
          </p>
        )}

        {conversations.length === 0 ? (
          <div className="flex flex-col items-center text-center py-16 space-y-4">
            <div className="w-14 h-14 rounded-full bg-owl-900/40 border border-owl-600/20 flex items-center justify-center">
              <MessageSquare className="w-7 h-7 text-owl-400" />
            </div>
            <h2 className="text-lg font-semibold text-gray-200">No conversations yet</h2>
            <p className="text-sm text-gray-400">
              Start by finding a character to message.
            </p>
            <Link
              to="/characters"
              className="mt-2 px-5 py-2 bg-owl-600 hover:bg-owl-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              Find characters
            </Link>
            <p className="text-xs text-gray-500 mt-2">
              You'll need at least one other user's character to start a conversation.
            </p>
          </div>
        ) : (
          <div className="space-y-1">
            {conversations.map((conv) => {
              const other = otherCharacter(conv);
              return (
                <Link
                  key={conv.id}
                  to={`/messages/${conv.id}`}
                  className="flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-gray-800/50 transition-colors"
                >
                  {other.avatar_url ? (
                    <img
                      src={other.avatar_url}
                      alt={other.name}
                      className="w-10 h-10 rounded-full object-cover border border-gray-700 flex-shrink-0"
                    />
                  ) : (
                    <div className="w-10 h-10 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center flex-shrink-0">
                      <Feather className="w-4 h-4 text-gray-600" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium text-gray-200 truncate">
                        {other.name}
                      </span>
                      <span className="text-xs text-gray-500 flex-shrink-0">
                        {formatTime(conv.updated_at)}
                      </span>
                    </div>
                    {conv.last_message && (
                      <p className="text-xs text-gray-400 truncate mt-0.5">
                        {conv.last_message.body}
                      </p>
                    )}
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
