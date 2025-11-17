import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Scene } from '@/lib/types';

export default function Scenes() {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newScene, setNewScene] = useState({
    title: '',
    description: '',
    visibility: 'public' as 'public' | 'unlisted' | 'private',
  });

  useEffect(() => {
    loadScenes();
  }, []);

  const loadScenes = async () => {
    try {
      const data = await apiClient.getScenes();
      setScenes(data);
    } catch (error) {
      console.error('Failed to load scenes:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateScene = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.createScene(newScene);
      setShowCreateForm(false);
      setNewScene({ title: '', description: '', visibility: 'public' });
      await loadScenes();
    } catch (error) {
      console.error('Failed to create scene:', error);
      alert('Failed to create scene. Please try again.');
    }
  };

  if (loading) {
    return <div className="p-8">Loading...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold">Roleplay Scenes</h1>
        <button
          onClick={() => setShowCreateForm(!showCreateForm)}
          className="btn btn-primary"
        >
          Create Scene
        </button>
      </div>

      {showCreateForm && (
        <div className="card mb-8">
          <h2 className="text-xl font-semibold mb-4">Create New Scene</h2>
          <form onSubmit={handleCreateScene} className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">
                Title <span className="text-red-400">*</span>
              </label>
              <input
                type="text"
                value={newScene.title}
                onChange={(e) => setNewScene({ ...newScene, title: e.target.value })}
                className="input"
                required
                placeholder="The Adventure Begins..."
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Description</label>
              <textarea
                value={newScene.description}
                onChange={(e) => setNewScene({ ...newScene, description: e.target.value })}
                className="textarea"
                rows={4}
                placeholder="Set the stage for your roleplay scene..."
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Visibility</label>
              <select
                value={newScene.visibility}
                onChange={(e) =>
                  setNewScene({
                    ...newScene,
                    visibility: e.target.value as 'public' | 'unlisted' | 'private',
                  })
                }
                className="input"
              >
                <option value="public">Public - Anyone can find and join</option>
                <option value="unlisted">Unlisted - Only with link</option>
                <option value="private">Private - Only you can access</option>
              </select>
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

      {scenes.length === 0 ? (
        <div className="card text-center">
          <p className="text-gray-400 mb-4">No scenes yet!</p>
          <p className="text-sm text-gray-500">
            Create the first roleplay scene to get started.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {scenes.map((scene) => (
            <Link key={scene.id} to={`/scenes/${scene.id}`} className="block">
              <div className="card hover:border-owl-500 transition-colors">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h3 className="text-xl font-semibold mb-2">{scene.title}</h3>
                    {scene.description && (
                      <p className="text-gray-300 mb-3 line-clamp-2">
                        {scene.description}
                      </p>
                    )}
                    <div className="flex items-center gap-4 text-sm text-gray-500">
                      <span>{new Date(scene.created_at).toLocaleDateString()}</span>
                      <span className="capitalize">{scene.visibility}</span>
                    </div>
                  </div>
                  <div className="ml-4">
                    <span className="text-sm text-owl-400">→</span>
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
