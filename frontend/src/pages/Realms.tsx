import { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Realm } from '@/lib/types';

export default function Realms() {
  const navigate = useNavigate();
  const [realms, setRealms] = useState<Realm[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  // Genre filter state — null means "All".
  const [selectedGenre, setSelectedGenre] = useState<string | null>(null);

  // Join button state: which realm is currently joining, which have been joined, any inline errors.
  const [joiningId, setJoiningId] = useState<number | null>(null);
  const [joinedIds, setJoinedIds] = useState<Set<number>>(new Set());
  const [joinErrorById, setJoinErrorById] = useState<Record<number, string>>({});

  // Post-join nudge state — shows a "go post your intro" row for 6 s after joining.
  const [joinNudgeById, setJoinNudgeById] = useState<Record<number, boolean>>({});
  const nudgeTimersRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  // Clean up any pending nudge timers on unmount.
  useEffect(() => () => { Object.values(nudgeTimersRef.current).forEach(clearTimeout); }, []);

  const dismissNudge = (realmId: number) => {
    clearTimeout(nudgeTimersRef.current[realmId]);
    setJoinNudgeById((prev) => ({ ...prev, [realmId]: false }));
  };

  const [newRealm, setNewRealm] = useState({
    name: '',
    slug: '',
    tagline: '',
    description: '',
    genre: '',
    banner_url: '',
    is_public: true,
  });

  useEffect(() => {
    loadRealms();
  }, []);

  const loadRealms = async () => {
    try {
      const data = await apiClient.getRealms();
      setRealms(data);
    } catch (error) {
      console.error('Failed to load realms:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateRealm = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.createRealm(newRealm);
      setShowCreateForm(false);
      setNewRealm({ name: '', slug: '', tagline: '', description: '', genre: '', banner_url: '', is_public: true });
      await loadRealms();
    } catch (error) {
      console.error('Failed to create realm:', error);
      alert('Failed to create realm. Please try again.');
    }
  };

  const handleJoinRealm = async (realmId: number) => {
    if (joiningId !== null || joinedIds.has(realmId)) return;
    // Clear any previous error for this realm and mark as in-flight.
    setJoinErrorById((prev) => { const { [realmId]: _, ...rest } = prev; return rest; });
    setJoiningId(realmId);
    try {
      await apiClient.joinRealm(realmId);
      setJoinedIds((prev) => new Set(prev).add(realmId));
      // Show post-join nudge and auto-hide after 6 s.
      setJoinNudgeById((prev) => ({ ...prev, [realmId]: true }));
      nudgeTimersRef.current[realmId] = setTimeout(
        () => setJoinNudgeById((prev) => ({ ...prev, [realmId]: false })),
        6_000,
      );
    } catch {
      setJoinErrorById((prev) => ({ ...prev, [realmId]: 'Could not join. Please try again.' }));
    } finally {
      setJoiningId(null);
    }
  };

  // Unique genres derived from non-commons realms with a non-empty genre field.
  // Sorted alphabetically; case-normalized for deduplication but displayed as-stored.
  const visibleRealms = realms.filter((r) => !r.is_commons);
  const genres: string[] = Array.from(
    new Map(
      visibleRealms
        .map((r) => r.genre?.trim())
        .filter((g): g is string => !!g)
        .map((g) => [g.toLowerCase(), g])
    ).values()
  ).sort((a, b) => a.localeCompare(b));

  // Apply genre filter (case-insensitive). When null, show all.
  const filteredRealms = selectedGenre === null
    ? visibleRealms
    : visibleRealms.filter((r) => r.genre?.trim().toLowerCase() === selectedGenre.toLowerCase());

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">Realms</h1>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="btn btn-primary"
        >
          Create Realm
        </button>
      </div>

      {showCreateForm && (
        <div className="card mb-8">
          <h2 className="text-xl font-semibold mb-4">Create New Realm</h2>
          <form onSubmit={handleCreateRealm} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Name</label>
              <input
                type="text"
                value={newRealm.name}
                onChange={(e) => setNewRealm({ ...newRealm, name: e.target.value })}
                className="input"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Slug</label>
              <input
                type="text"
                value={newRealm.slug}
                onChange={(e) => setNewRealm({ ...newRealm, slug: e.target.value })}
                className="input"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Tagline</label>
              <input
                type="text"
                value={newRealm.tagline}
                onChange={(e) => setNewRealm({ ...newRealm, tagline: e.target.value })}
                className="input"
                placeholder="A short catchy description"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Description</label>
              <textarea
                value={newRealm.description}
                onChange={(e) => setNewRealm({ ...newRealm, description: e.target.value })}
                className="textarea"
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Banner URL</label>
              <input
                type="url"
                value={newRealm.banner_url}
                onChange={(e) => setNewRealm({ ...newRealm, banner_url: e.target.value })}
                className="input"
                placeholder="https://..."
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-2">Genre</label>
              <input
                type="text"
                value={newRealm.genre}
                onChange={(e) => setNewRealm({ ...newRealm, genre: e.target.value })}
                className="input"
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

      {/* Genre filter pills — only shown when there are genres to filter by */}
      {genres.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-4">
          <button
            onClick={() => setSelectedGenre(null)}
            className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
              selectedGenre === null
                ? 'bg-owl-700 border-owl-500 text-white'
                : 'bg-transparent border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200'
            }`}
          >
            All
          </button>
          {genres.map((genre) => (
            <button
              key={genre}
              onClick={() => setSelectedGenre(genre)}
              className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                selectedGenre?.toLowerCase() === genre.toLowerCase()
                  ? 'bg-owl-700 border-owl-500 text-white'
                  : 'bg-transparent border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200'
              }`}
            >
              {genre}
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-4">
        {filteredRealms.map((realm) => (
          <div key={realm.id} className="card overflow-hidden p-0">
            {realm.banner_url && (
              <div className="h-32 bg-gradient-to-r from-owl-900 to-owl-700">
                <img
                  src={realm.banner_url}
                  alt={realm.name}
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    e.currentTarget.style.display = 'none';
                  }}
                />
              </div>
            )}
            <div className="p-6">
              <div className="flex justify-between items-start">
                <Link to={`/realms/${realm.id}`} className="flex-1 group">
                  <h3 className="text-xl font-semibold group-hover:text-owl-300 transition-colors">
                    {realm.name}
                  </h3>
                  {realm.tagline && (
                    <p className="text-sm text-owl-400 italic mb-1">{realm.tagline}</p>
                  )}
                  <p className="text-xs text-gray-500 mb-2">
                    /{realm.slug} • {realm.is_public ? 'Public' : 'Private'}
                  </p>
                  {realm.description && (
                    <p className="text-gray-300 mb-2">{realm.description}</p>
                  )}
                  {realm.genre && (
                    <span className="inline-block px-2 py-1 bg-owl-900 text-owl-300 text-xs rounded">
                      {realm.genre}
                    </span>
                  )}
                </Link>
                <button
                  onClick={() => handleJoinRealm(realm.id)}
                  disabled={joiningId === realm.id || joinedIds.has(realm.id)}
                  className={`btn ml-4 flex-shrink-0 ${
                    joinedIds.has(realm.id)
                      ? 'btn-secondary text-emerald-400 border-emerald-800 cursor-default'
                      : 'btn-primary'
                  }`}
                >
                  {joiningId === realm.id ? 'Joining…' : joinedIds.has(realm.id) ? 'Joined ✓' : 'Join'}
                </button>
              </div>
              {joinErrorById[realm.id] && (
                <p className="mt-2 text-xs text-red-400">{joinErrorById[realm.id]}</p>
              )}
              {joinNudgeById[realm.id] && (
                <div className="mt-2 flex items-center justify-between gap-2">
                  <span className="text-xs text-emerald-400">You're in — go post your intro.</span>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => navigate(`/realms/${realm.id}`)}
                      className="text-xs text-owl-400 hover:text-owl-300 transition-colors"
                    >
                      Open realm
                    </button>
                    <button
                      type="button"
                      onClick={() => dismissNudge(realm.id)}
                      className="text-gray-600 hover:text-gray-400 transition-colors"
                      aria-label="Dismiss"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
