import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, MessageSquare, Feather } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';
import { createOrGetConversation } from '@/features/messaging/api';

export default function MessageNew() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const characterId = searchParams.get('characterId');
  const fromParam = searchParams.get('from');

  const [myCharacters, setMyCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedFromId, setSelectedFromId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    apiClient
      .getCharacters()
      .then((chars) => {
        setMyCharacters(chars);
        // Auto-select if from param given or only one character
        if (fromParam) {
          const fid = Number(fromParam);
          if (chars.some((c) => c.id === fid)) setSelectedFromId(fid);
        } else if (chars.length === 1) {
          setSelectedFromId(chars[0].id);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [fromParam]);

  // Auto-start conversation when we have both IDs
  useEffect(() => {
    if (!characterId || !selectedFromId || creating) return;
    if (myCharacters.length === 1 || fromParam) {
      startConversation(selectedFromId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedFromId, characterId, myCharacters]);

  async function startConversation(fromId: number) {
    if (!characterId) return;
    setCreating(true);
    setError('');
    try {
      const conv = await createOrGetConversation(fromId, Number(characterId));
      navigate(`/messages/${conv.id}`, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start conversation');
      setCreating(false);
    }
  }

  if (loading || creating) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        {creating ? 'Opening conversation…' : 'Loading…'}
      </div>
    );
  }

  // No characterId — redirect to conversations list
  if (!characterId) {
    navigate('/messages', { replace: true });
    return null;
  }

  // User has no characters
  if (myCharacters.length === 0) {
    return (
      <div className="min-h-screen">
        <div className="border-b border-gray-800 bg-gray-900/50">
          <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
            <Link
              to={`/characters/${characterId}`}
              className="text-gray-400 hover:text-gray-200 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <span className="text-sm font-medium text-gray-300">New Message</span>
          </div>
        </div>
        <div className="max-w-2xl mx-auto px-4 py-16 flex flex-col items-center text-center space-y-4">
          <MessageSquare className="w-8 h-8 text-gray-500" />
          <p className="text-sm text-gray-400">
            You need at least one character to send messages.
          </p>
          <Link to="/characters/new" className="btn btn-primary text-sm">
            Create a character
          </Link>
        </div>
      </div>
    );
  }

  // Multiple characters — show chooser
  return (
    <div className="min-h-screen">
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to={`/characters/${characterId}`}
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300">Choose a character</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-4">
        <p className="text-sm text-gray-400">Message as which character?</p>

        {error && (
          <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
            {error}
          </p>
        )}

        <div className="space-y-2">
          {myCharacters.map((ch) => (
            <button
              key={ch.id}
              onClick={() => {
                setSelectedFromId(ch.id);
                startConversation(ch.id);
              }}
              className="w-full flex items-center gap-3 px-4 py-3 rounded-lg border border-gray-700 hover:border-owl-500/50 hover:bg-gray-800/50 transition-colors text-left"
            >
              {ch.avatar_url ? (
                <img
                  src={ch.avatar_url}
                  alt={ch.name}
                  className="w-10 h-10 rounded-full object-cover border border-gray-700 flex-shrink-0"
                />
              ) : (
                <div className="w-10 h-10 rounded-full bg-gray-800 border border-gray-700 flex items-center justify-center flex-shrink-0">
                  <Feather className="w-4 h-4 text-gray-600" />
                </div>
              )}
              <div className="min-w-0">
                <span className="text-sm font-medium text-gray-200 truncate block">
                  {ch.name}
                </span>
                {ch.species && (
                  <span className="text-xs text-gray-500">{ch.species}</span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
