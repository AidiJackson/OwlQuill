import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';

export default function Characters() {
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

  useEffect(() => {
    loadCharacters();
  }, []);

  const loadCharacters = async () => {
    try {
      const data = await apiClient.getCharacters();
      setCharacters(data);
    } catch (error) {
      console.error('Failed to load characters:', error);
    } finally {
      setLoading(false);
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
      alert('Failed to create character. Please try again.');
    }
  };

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">My Characters</h1>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="btn btn-primary"
        >
          Create Character
        </button>
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
        {characters.map((character) => (
          <div key={character.id} className="card flex gap-4">
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
          </div>
        ))}
      </div>
    </div>
  );
}
