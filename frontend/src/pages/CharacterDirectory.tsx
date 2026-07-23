import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Search, Feather } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { CharacterSearchResult } from '@/lib/types';

/** Public character directory — the Wanderer browse surface.
 *  Lists public characters only; every card leads to a character profile.
 *  No accounts, no owners, no rosters. */
export default function CharacterDirectory() {
  const [characters, setCharacters] = useState<CharacterSearchResult[]>([]);
  const [loading, setLoading] = useState(true);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<CharacterSearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    apiClient.getCharacterDirectory()
      .then(setCharacters)
      .catch(() => setCharacters([]))
      .finally(() => setLoading(false));
  }, []);

  const runSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setSearchResults([]);
      setHasSearched(false);
      setSearchLoading(false);
      return;
    }
    setSearchLoading(true);
    try {
      const data = await apiClient.searchCharacters(q.trim());
      setSearchResults(data);
      setHasSearched(true);
    } catch {
      setSearchResults([]);
      setHasSearched(true);
    } finally {
      setSearchLoading(false);
    }
  }, []);

  const handleSearchInput = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (value.trim().length < 2) {
      setSearchResults([]);
      setHasSearched(false);
      return;
    }
    debounceRef.current = setTimeout(() => runSearch(value), 300);
  };

  const showingSearch = hasSearched && searchQuery.trim().length >= 2;
  const visible = showingSearch ? searchResults : characters;

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-8 py-8">
      <div className="mb-6">
        <h1 className="font-serif text-4xl font-medium tracking-[-0.02em] text-ink">Characters</h1>
        <p className="text-ink-2 text-sm mt-1">
          Discover the characters of Ficshon and follow their stories.
        </p>
      </div>

      {/* Search */}
      <div className="relative mb-8 max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-3 pointer-events-none" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => handleSearchInput(e.target.value)}
          placeholder="Search characters…"
          className="w-full bg-surface border border-edge focus:border-gem/50 rounded-xl pl-9 pr-4 py-2.5 text-sm text-ink placeholder:text-ink-3 outline-none transition-colors"
        />
      </div>

      {loading || searchLoading ? (
        <div className="flex justify-center py-16">
          <div className="w-8 h-8 border-4 border-gem/50 border-t-gem rounded-full animate-spin" />
        </div>
      ) : visible.length === 0 ? (
        <div className="rounded-2xl p-12 sm:p-16 text-center bg-surface border border-edge">
          <Feather className="w-12 h-12 text-ink-3 mx-auto mb-4" />
          <h3 className="text-ink text-lg font-semibold mb-1">
            {showingSearch ? 'No characters found' : 'No characters yet'}
          </h3>
          <p className="text-ink-3 text-sm">
            {showingSearch
              ? 'Try a different name or tag.'
              : 'Public characters will appear here as they arrive.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {visible.map((ch) => (
            <Link
              key={ch.id}
              to={`/characters/${ch.id}`}
              className="rounded-2xl overflow-hidden bg-surface border border-edge hover:border-gem/50 transition-all group"
            >
              {/* Card cover strip */}
              <div className="relative h-20 bg-gem-soft">
                {ch.cover_url && (
                  <img
                    src={ch.cover_url}
                    alt=""
                    className="absolute inset-0 w-full h-full object-cover opacity-80"
                    style={{ objectPosition: `${(ch.cover_position_x ?? 0.5) * 100}% ${(ch.cover_position_y ?? 0.5) * 100}%` }}
                    loading="lazy"
                    decoding="async"
                  />
                )}
                <div className="absolute inset-0 bg-gradient-to-t from-gray-900/90 to-transparent" />
              </div>
              <div className="px-4 pb-4 -mt-7 relative">
                <div className="flex items-end gap-3">
                  {ch.avatar_url ? (
                    <img
                      src={ch.avatar_url}
                      alt={ch.name}
                      className="w-14 h-14 rounded-xl object-cover border-2 border-surface bg-surface-elevated flex-shrink-0 group-hover:border-gem/50 transition-colors"
                      loading="lazy"
                      decoding="async"
                    />
                  ) : (
                    <div className="w-14 h-14 rounded-xl bg-surface-elevated border-2 border-surface flex items-center justify-center flex-shrink-0">
                      <span className="text-lg font-bold text-gem">{ch.name.charAt(0)}</span>
                    </div>
                  )}
                  <div className="min-w-0 flex-1 pb-0.5">
                    <h4 className="font-semibold text-ink truncate group-hover:text-gem transition-colors">
                      {ch.name}
                    </h4>
                    {ch.species && (
                      <p className="text-xs text-ink-3 truncate">{ch.species}</p>
                    )}
                  </div>
                </div>
                {ch.short_bio && (
                  <p className="text-sm text-ink-2 mt-2.5 line-clamp-2 leading-relaxed">
                    {ch.short_bio}
                  </p>
                )}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
