import { useState, useEffect } from 'react';
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, Globe, Users, Lock, Feather } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';

const VISIBILITY_ICONS = {
  public: Globe,
  friends: Users,
  private: Lock,
} as const;

export default function CharacterDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [character, setCharacter] = useState<Character | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const justCreated = searchParams.get('created') === '1';

  useEffect(() => {
    if (!id) return;
    apiClient
      .getCharacter(Number(id))
      .then(setCharacter)
      .catch((err) => setError(err instanceof Error ? err.message : 'Character not found'))
      .finally(() => setLoading(false));
  }, [id]);

  const dismissBanner = () => {
    searchParams.delete('created');
    setSearchParams(searchParams, { replace: true });
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        Loading…
      </div>
    );
  }

  if (error || !character) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-gray-400">{error || 'Character not found.'}</p>
        <button className="btn btn-secondary" onClick={() => navigate('/characters')}>
          Back to Characters
        </button>
      </div>
    );
  }

  const VisIcon = VISIBILITY_ICONS[character.visibility] || Globe;

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to="/characters"
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300 truncate">
            {character.name}
          </span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
        {/* Arrival banner */}
        {justCreated && (
          <div className="flex items-center justify-between gap-3 bg-owl-600/10 border border-owl-600/20 rounded-lg px-4 py-3">
            <div className="flex items-center gap-2">
              <Feather className="w-4 h-4 text-owl-400 flex-shrink-0" />
              <span className="text-sm text-owl-300">
                Your character now lives on OwlQuill.
              </span>
            </div>
            <button
              onClick={dismissBanner}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors flex-shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Header */}
        <div className="flex gap-5 items-start">
          {character.avatar_url ? (
            <img
              src={character.avatar_url}
              alt={character.name}
              className="w-28 h-28 rounded-lg object-cover border border-gray-800 flex-shrink-0"
            />
          ) : (
            <div className="w-28 h-28 rounded-lg bg-gray-800 border border-gray-700 flex items-center justify-center flex-shrink-0">
              <Feather className="w-8 h-8 text-gray-600" />
            </div>
          )}
          <div className="min-w-0 space-y-1.5">
            <h1 className="text-2xl font-bold text-gray-100 truncate">{character.name}</h1>
            {(character.species || character.role || character.era) && (
              <p className="text-sm text-gray-400">
                {[character.species, character.role, character.era].filter(Boolean).join(' · ')}
              </p>
            )}
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <VisIcon className="w-3.5 h-3.5" />
              <span className="capitalize">{character.visibility}</span>
            </div>
          </div>
        </div>

        {/* Bio */}
        {character.short_bio && (
          <p className="text-gray-300">{character.short_bio}</p>
        )}
        {character.long_bio && (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{character.long_bio}</p>
          </div>
        )}

        {/* Tags */}
        {character.tags && (
          <div className="flex flex-wrap gap-2">
            {character.tags.split(',').map((tag, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-owl-900 text-owl-300 text-xs rounded"
              >
                {tag.trim()}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
