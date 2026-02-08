import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Search } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character, CharacterSearchResult, User } from '@/lib/types';

export default function Characters() {
  const navigate = useNavigate();
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [generatingBio, setGeneratingBio] = useState(false);
  const [newCharacter, setNewCharacter] = useState({
    name: '',
    species: '',
    role: '',
    era: '',
    tags: '',
    short_bio: '',
    long_bio: '',
    portrait_url: '',
    visibility: 'public' as 'public' | 'friends' | 'private',
  });

  const [currentUser, setCurrentUser] = useState<User | null>(null);

  // ── Search state ──
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<CharacterSearchResult[]>([]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  useEffect(() => {
    loadCharacters();
  }, []);

  const loadCharacters = async () => {
    try {
      const [data, user] = await Promise.all([
        apiClient.getCharacters(),
        apiClient.getMe().catch(() => null),
      ]);
      setCharacters(data);
      setCurrentUser(user);
    } catch (error) {
      console.error('Failed to load characters:', error);
    } finally {
      setLoading(false);
    }
  };

  const activeCharacters = useMemo(
    () => characters.filter((c) => c.visual_locked === true),
    [characters],
  );
  const draftCharacters = useMemo(
    () => characters.filter((c) => !c.visual_locked),
    [characters],
  );
  const draftIds = useMemo(
    () => new Set(draftCharacters.map((c) => c.id)),
    [draftCharacters],
  );

  const cooldownInfo = useMemo(() => {
    if (!currentUser?.next_character_allowed_at) return null;
    const until = new Date(currentUser.next_character_allowed_at);
    const now = new Date();
    const diffMs = until.getTime() - now.getTime();
    if (diffMs <= 0) return null;
    const hours = Math.floor(diffMs / (1000 * 60 * 60));
    const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
    return { hours, minutes };
  }, [currentUser]);

  const handleDeleteDraft = async (id: number) => {
    if (!window.confirm('Delete this draft character? This cannot be undone.')) return;
    try {
      await apiClient.deleteCharacter(id);
      setCharacters((prev) => prev.filter((c) => c.id !== id));
    } catch {
      alert('Failed to delete draft.');
    }
  };

  const handleGenerateBio = async () => {
    if (!newCharacter.name) {
      alert('Please enter a character name first');
      return;
    }

    setGeneratingBio(true);
    try {
      const tags = newCharacter.tags ? newCharacter.tags.split(',').map((t) => t.trim()) : [];
      const result = await apiClient.generateCharacterBio(
        newCharacter.name,
        newCharacter.species,
        newCharacter.role,
        newCharacter.era,
        tags
      );
      setNewCharacter({
        ...newCharacter,
        short_bio: result.short_bio,
        long_bio: result.long_bio,
      });
    } catch (error) {
      console.error('Failed to generate bio:', error);
      alert('Failed to generate bio. Please try again.');
    } finally {
      setGeneratingBio(false);
    }
  };

  const handleCreateCharacter = async (e: React.FormEvent) => {
    e.preventDefault();
    if (cooldownInfo) {
      alert(`Character creation is on cooldown. You can create a new character in ${cooldownInfo.hours}h ${cooldownInfo.minutes}m.`);
      return;
    }
    try {
      await apiClient.createCharacter(newCharacter);
      setShowCreateForm(false);
      setNewCharacter({
        name: '',
        species: '',
        role: '',
        era: '',
        tags: '',
        short_bio: '',
        long_bio: '',
        portrait_url: '',
        visibility: 'public',
      });
      await loadCharacters();
    } catch (error) {
      console.error('Failed to create character:', error);
      alert(error instanceof Error ? error.message : 'Failed to create character. Please try again.');
    }
  };

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">My Characters</h1>
        {characters.length === 0 && cooldownInfo ? (
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500 bg-gray-800 px-3 py-1.5 rounded-full">
              Beta limit: 1 character per account
            </span>
            <span className="text-xs text-amber-400 bg-amber-400/10 px-3 py-1.5 rounded-full">
              New character in {cooldownInfo.hours}h {cooldownInfo.minutes}m
            </span>
          </div>
        ) : characters.length === 0 ? (
          <div className="flex gap-2">
            <button
              onClick={() => navigate('/characters/new')}
              className="btn btn-primary"
            >
              + New Character
            </button>
            <button
              onClick={() => setShowCreateForm(!showCreateForm)}
              className="btn btn-secondary text-sm"
            >
              Quick Create
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500 bg-gray-800 px-3 py-1.5 rounded-full">
              Beta limit: 1 character per account
            </span>
            {draftCharacters.length > 0 ? (
              <button
                className="btn btn-primary text-sm"
                onClick={() => navigate(`/characters/new?characterId=${draftCharacters[0].id}`)}
              >
                Continue setup
              </button>
            ) : (
              <button
                className="btn btn-primary text-sm"
                onClick={() => navigate(`/characters/${activeCharacters[0].id}`)}
              >
                View character
              </button>
            )}
          </div>
        )}
      </div>

      {/* Search */}
      <div className="mb-6 space-y-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            className="input pl-10"
            placeholder="Search characters..."
            value={searchQuery}
            onChange={(e) => handleSearchInput(e.target.value)}
          />
        </div>

        {searchLoading && (
          <p className="text-sm text-gray-500">Searching…</p>
        )}

        {!searchLoading && hasSearched && searchResults.length === 0 && (
          <p className="text-sm text-gray-500">No characters found.</p>
        )}

        {searchResults.length > 0 && (
          <div className="border border-gray-800 rounded-lg divide-y divide-gray-800 bg-gray-900">
            {searchResults.filter((r) => !draftIds.has(r.id)).map((r) => (
              <Link
                key={r.id}
                to={`/characters/${r.id}`}
                className="flex items-center gap-3 px-4 py-3 hover:bg-gray-800/60 transition-colors"
              >
                {r.avatar_url ? (
                  <img
                    src={r.avatar_url}
                    alt={r.name}
                    className="w-9 h-9 rounded-lg object-cover flex-shrink-0"
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                  />
                ) : (
                  <div className="w-9 h-9 rounded-lg bg-gray-800 flex-shrink-0" />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-100 truncate">{r.name}</p>
                  {(r.species || r.short_bio) && (
                    <p className="text-xs text-gray-500 truncate">
                      {r.species ? `${r.species} · ` : ''}{r.short_bio || ''}
                    </p>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>

      {showCreateForm && (
        <div className="card mb-8">
          <h2 className="text-xl font-semibold mb-4">Create New Character</h2>
          <form onSubmit={handleCreateCharacter} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2">Name *</label>
                <input
                  type="text"
                  value={newCharacter.name}
                  onChange={(e) => setNewCharacter({ ...newCharacter, name: e.target.value })}
                  className="input"
                  required
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Species</label>
                <input
                  type="text"
                  value={newCharacter.species}
                  onChange={(e) => setNewCharacter({ ...newCharacter, species: e.target.value })}
                  className="input"
                  placeholder="e.g., vampire, human, elf"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Role</label>
                <input
                  type="text"
                  value={newCharacter.role}
                  onChange={(e) => setNewCharacter({ ...newCharacter, role: e.target.value })}
                  className="input"
                  placeholder="e.g., assassin, healer, detective"
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-2">Era</label>
                <input
                  type="text"
                  value={newCharacter.era}
                  onChange={(e) => setNewCharacter({ ...newCharacter, era: e.target.value })}
                  className="input"
                  placeholder="e.g., modern, medieval, sci-fi"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Tags (comma-separated)</label>
              <input
                type="text"
                value={newCharacter.tags}
                onChange={(e) => setNewCharacter({ ...newCharacter, tags: e.target.value })}
                className="input"
                placeholder="e.g., gothic, mysterious, angst"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Portrait URL</label>
              <input
                type="url"
                value={newCharacter.portrait_url}
                onChange={(e) => setNewCharacter({ ...newCharacter, portrait_url: e.target.value })}
                className="input"
                placeholder="https://..."
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="block text-sm font-medium">Short Bio</label>
                <button
                  type="button"
                  onClick={handleGenerateBio}
                  disabled={generatingBio}
                  className="text-sm text-owl-500 hover:text-owl-400 disabled:opacity-50"
                >
                  {generatingBio ? 'Generating...' : '✨ AI Suggest Bio'}
                </button>
              </div>
              <textarea
                value={newCharacter.short_bio}
                onChange={(e) => setNewCharacter({ ...newCharacter, short_bio: e.target.value })}
                className="textarea"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Long Bio</label>
              <textarea
                value={newCharacter.long_bio}
                onChange={(e) => setNewCharacter({ ...newCharacter, long_bio: e.target.value })}
                className="textarea"
                rows={6}
              />
            </div>

            <div className="flex gap-4">
              <button type="submit" className="btn btn-primary">
                Create
              </button>
              <button
                type="button"
                onClick={() => setShowCreateForm(false)}
                className="btn btn-secondary"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="grid gap-4">
        {activeCharacters.map((character) => (
          <Link
            key={character.id}
            to={`/characters/${character.id}`}
            className="card flex gap-4 hover:border-gray-600 transition-colors no-underline text-inherit"
          >
            {character.portrait_url && (
              <div className="flex-shrink-0">
                <img
                  src={character.portrait_url}
                  alt={character.name}
                  className="w-24 h-24 rounded-lg object-cover"
                  onError={(e) => {
                    e.currentTarget.style.display = 'none';
                  }}
                />
              </div>
            )}
            <div className="flex-1">
              <h3 className="text-xl font-semibold">{character.name}</h3>
              {(character.species || character.role || character.era) && (
                <p className="text-sm text-gray-400">
                  {[character.species, character.role, character.era].filter(Boolean).join(' • ')}
                </p>
              )}
              {character.short_bio && (
                <p className="text-gray-300 mt-2">{character.short_bio}</p>
              )}
              {character.tags && (
                <div className="mt-2 flex flex-wrap gap-2">
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
          </Link>
        ))}
      </div>

      {draftCharacters.length > 0 && (
        <div className="mt-10">
          <h2 className="text-xl font-semibold mb-4 text-gray-300">Draft Characters</h2>
          <div className="grid gap-3">
            {draftCharacters.map((character) => (
              <div key={character.id} className="card flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-semibold truncate">{character.name}</h3>
                    <span className="px-2 py-0.5 bg-amber-500/20 text-amber-400 text-xs rounded-full font-medium">
                      Draft
                    </span>
                  </div>
                  {character.species && (
                    <p className="text-sm text-gray-400">{character.species}</p>
                  )}
                  <p className="text-xs text-gray-500 mt-1">Finish setup to unlock identity.</p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <button
                    className="btn btn-primary text-sm"
                    onClick={() => navigate(`/characters/new?characterId=${character.id}`)}
                  >
                    Continue
                  </button>
                  <button
                    className="btn btn-secondary text-sm"
                    onClick={() => handleDeleteDraft(character.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
