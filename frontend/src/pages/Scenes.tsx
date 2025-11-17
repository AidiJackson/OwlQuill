import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Scene, Realm } from '@/lib/types';

export default function Scenes() {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [realms, setRealms] = useState<Realm[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newScene, setNewScene] = useState({
    title: '',
    summary: '',
    realm_id: undefined as number | undefined,
    tags: '',
    visibility: 'public' as 'public' | 'friends' | 'private',
    is_nsfw: false,
    has_violence: false,
  });

  useEffect(() => {
    loadScenes();
    loadRealms();
  }, []);

  const loadScenes = async () => {
    try {
      const data = await apiClient.getScenes();
      setScenes(data);
      setError(null);
    } catch (error) {
      console.error('Failed to load scenes:', error);
      setError('Failed to load scenes. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const loadRealms = async () => {
    try {
      const data = await apiClient.getRealms();
      setRealms(data);
    } catch (error) {
      console.error('Failed to load realms:', error);
    }
  };

  const handleCreateScene = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newScene.title.trim()) {
      alert('Please enter a scene title');
      return;
    }

    try {
      const created = await apiClient.createScene(newScene);
      setShowCreateForm(false);
      setNewScene({
        title: '',
        summary: '',
        realm_id: undefined,
        tags: '',
        visibility: 'public',
        is_nsfw: false,
        has_violence: false,
      });
      setScenes([created, ...scenes]);
    } catch (error) {
      console.error('Failed to create scene:', error);
      alert('Failed to create scene. Please try again.');
    }
  };

  const getRealmName = (realmId?: number): string | null => {
    if (!realmId) return null;
    const realm = realms.find((r) => r.id === realmId);
    return realm?.name || null;
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 60) {
      return `${diffMins}m ago`;
    } else if (diffHours < 24) {
      return `${diffHours}h ago`;
    } else if (diffDays < 7) {
      return `${diffDays}d ago`;
    } else {
      return date.toLocaleDateString();
    }
  };

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-3xl font-bold">Scenes</h1>
          <p className="text-gray-400 mt-2">
            Collaborative storytelling threads with your characters
          </p>
        </div>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="btn btn-primary"
        >
          Create Scene
        </button>
      </div>

      {error && (
        <div className="card mb-6 bg-red-900/20 border-red-500">
          <p className="text-red-400">{error}</p>
        </div>
      )}

      {showCreateForm && (
        <div className="card mb-8">
          <h2 className="text-xl font-semibold mb-4">Create New Scene</h2>
          <form onSubmit={handleCreateScene} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Title *</label>
              <input
                type="text"
                value={newScene.title}
                onChange={(e) => setNewScene({ ...newScene, title: e.target.value })}
                className="input"
                placeholder="A mysterious encounter in the tavern..."
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Summary</label>
              <textarea
                value={newScene.summary}
                onChange={(e) => setNewScene({ ...newScene, summary: e.target.value })}
                className="textarea"
                rows={3}
                placeholder="Brief description of the scene setup..."
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Realm (optional)</label>
              <select
                value={newScene.realm_id || ''}
                onChange={(e) =>
                  setNewScene({
                    ...newScene,
                    realm_id: e.target.value ? Number(e.target.value) : undefined,
                  })
                }
                className="input"
              >
                <option value="">No realm</option>
                {realms.map((realm) => (
                  <option key={realm.id} value={realm.id}>
                    {realm.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Tags (comma-separated)</label>
              <input
                type="text"
                value={newScene.tags}
                onChange={(e) => setNewScene({ ...newScene, tags: e.target.value })}
                className="input"
                placeholder="fantasy, adventure, mystery"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium mb-2">Visibility</label>
                <select
                  value={newScene.visibility}
                  onChange={(e) =>
                    setNewScene({
                      ...newScene,
                      visibility: e.target.value as 'public' | 'friends' | 'private',
                    })
                  }
                  className="input"
                >
                  <option value="public">Public</option>
                  <option value="friends">Friends Only</option>
                  <option value="private">Private</option>
                </select>
              </div>

              <div className="space-y-2">
                <label className="block text-sm font-medium mb-2">Content Warnings</label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={newScene.is_nsfw}
                    onChange={(e) => setNewScene({ ...newScene, is_nsfw: e.target.checked })}
                    className="rounded"
                  />
                  <span className="text-sm">NSFW / 18+</span>
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={newScene.has_violence}
                    onChange={(e) =>
                      setNewScene({ ...newScene, has_violence: e.target.checked })
                    }
                    className="rounded"
                  />
                  <span className="text-sm">Violence</span>
                </label>
              </div>
            </div>

            <div className="flex gap-4">
              <button type="submit" className="btn btn-primary">
                Create Scene
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
        {scenes.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400 mb-2">No scenes yet</p>
            <p className="text-sm text-gray-500">
              Create your first scene to start collaborative storytelling!
            </p>
          </div>
        ) : (
          scenes.map((scene) => {
            const realmName = getRealmName(scene.realm_id);
            const tags = scene.tags ? scene.tags.split(',').map((t) => t.trim()) : [];

            return (
              <Link
                key={scene.id}
                to={`/scenes/${scene.id}`}
                className="card hover:bg-gray-800/50 transition-colors"
              >
                <div className="flex items-start justify-between mb-2">
                  <h3 className="text-xl font-semibold">{scene.title}</h3>
                  <div className="flex gap-2">
                    {scene.is_nsfw && (
                      <span className="px-2 py-1 text-xs font-semibold rounded bg-red-600 text-white">
                        18+
                      </span>
                    )}
                    {scene.has_violence && (
                      <span className="px-2 py-1 text-xs font-semibold rounded bg-orange-600 text-white">
                        Violence
                      </span>
                    )}
                  </div>
                </div>

                {scene.summary && (
                  <p className="text-gray-300 mb-3 line-clamp-2">{scene.summary}</p>
                )}

                <div className="flex items-center gap-4 text-sm text-gray-500">
                  {realmName && (
                    <span className="text-owl-400">
                      Realm: {realmName}
                    </span>
                  )}
                  <span className={`px-2 py-1 rounded text-xs ${
                    scene.visibility === 'public'
                      ? 'bg-green-600/20 text-green-400'
                      : scene.visibility === 'friends'
                      ? 'bg-blue-600/20 text-blue-400'
                      : 'bg-gray-600/20 text-gray-400'
                  }`}>
                    {scene.visibility}
                  </span>
                  {scene.last_activity_at && (
                    <span>Last activity: {formatDate(scene.last_activity_at)}</span>
                  )}
                  {!scene.last_activity_at && (
                    <span>Created: {formatDate(scene.created_at)}</span>
                  )}
                </div>

                {tags.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {tags.map((tag, i) => (
                      <span
                        key={i}
                        className="px-2 py-1 bg-owl-900 text-owl-300 text-xs rounded"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </Link>
            );
          })
        )}
      </div>
    </div>
  );
}
