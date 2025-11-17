import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Realm, Scene } from '@/lib/types';

export default function RealmDetail() {
  const { realmId } = useParams<{ realmId: string }>();
  const navigate = useNavigate();
  const [realm, setRealm] = useState<Realm | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [loading, setLoading] = useState(true);
  const [showSceneForm, setShowSceneForm] = useState(false);
  const [newScene, setNewScene] = useState({
    title: '',
    description: '',
  });

  useEffect(() => {
    const loadData = async () => {
      if (!realmId) return;

      try {
        const [realmData, scenesData] = await Promise.all([
          apiClient.getRealm(Number(realmId)),
          apiClient.getRealmScenes(Number(realmId)),
        ]);
        setRealm(realmData);
        setScenes(scenesData);
      } catch (error) {
        console.error('Failed to load realm:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [realmId]);

  const handleJoinRealm = async () => {
    if (!realmId) return;

    try {
      await apiClient.joinRealm(Number(realmId));
      alert('Successfully joined realm!');
    } catch (error) {
      console.error('Failed to join realm:', error);
      alert('Failed to join realm. You may already be a member.');
    }
  };

  const handleCreateScene = async () => {
    if (!realmId || !newScene.title.trim()) return;

    try {
      const createdScene = await apiClient.createScene(Number(realmId), newScene);
      setScenes([createdScene, ...scenes]);
      setNewScene({
        title: '',
        description: '',
      });
      setShowSceneForm(false);
    } catch (error) {
      console.error('Failed to create scene:', error);
      alert('Failed to create scene. Make sure you are a member of this realm.');
    }
  };

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  if (!realm) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Realm not found</p>
        <button onClick={() => navigate('/realms')} className="btn btn-secondary mt-4">
          Back to Realms
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      {/* Realm header with banner */}
      <div className="card overflow-hidden mb-6">
        {realm.banner_url && (
          <div className="h-48 w-full overflow-hidden">
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
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-3xl font-bold">{realm.name}</h1>
              {realm.tagline && <p className="text-owl-400 italic mt-1">{realm.tagline}</p>}
            </div>
            <div className="flex items-center gap-4">
              <span className={`px-3 py-1 text-sm rounded ${realm.is_public ? 'bg-green-600' : 'bg-gray-600'}`}>
                {realm.is_public ? 'Public' : 'Private'}
              </span>
              <button onClick={handleJoinRealm} className="btn btn-primary">
                Join Realm
              </button>
            </div>
          </div>

          {realm.description && (
            <p className="text-gray-300 mb-4 whitespace-pre-wrap">{realm.description}</p>
          )}

          {realm.genre && (
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">Genre:</span>
              <span className="text-sm text-owl-300">{realm.genre}</span>
            </div>
          )}
        </div>
      </div>

      {/* Create scene section */}
      <div className="mb-6">
        {!showSceneForm ? (
          <button onClick={() => setShowSceneForm(true)} className="btn btn-primary w-full">
            + New Scene
          </button>
        ) : (
          <div className="card">
            <h3 className="text-xl font-semibold mb-4">Create New Scene</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">Title *</label>
                <input
                  type="text"
                  value={newScene.title}
                  onChange={(e) => setNewScene({ ...newScene, title: e.target.value })}
                  className="input"
                  placeholder="The Dark Forest, The Grand Ball, etc."
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Description</label>
                <textarea
                  value={newScene.description}
                  onChange={(e) => setNewScene({ ...newScene, description: e.target.value })}
                  className="textarea"
                  placeholder="Describe the setting and context for this scene..."
                  rows={4}
                />
              </div>

              <div className="flex gap-4">
                <button onClick={handleCreateScene} className="btn btn-primary">
                  Create Scene
                </button>
                <button
                  onClick={() => {
                    setShowSceneForm(false);
                    setNewScene({
                      title: '',
                      description: '',
                    });
                  }}
                  className="btn btn-secondary"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Scenes list */}
      <div>
        <h2 className="text-2xl font-bold mb-4">Scenes</h2>
        {scenes.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400">No scenes yet in this realm.</p>
            <p className="text-sm text-gray-500 mt-2">Create the first scene to start roleplaying!</p>
          </div>
        ) : (
          <div className="space-y-4">
            {scenes.map((scene) => (
              <Link
                key={scene.id}
                to={`/scenes/${scene.id}`}
                className="card block hover:border-owl-500 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <h3 className="text-xl font-semibold text-owl-300 group-hover:text-owl-200 mb-2">
                      {scene.title}
                    </h3>
                    {scene.description && (
                      <p className="text-gray-300 text-sm mb-2">{scene.description}</p>
                    )}
                    <span className="text-xs text-gray-500">
                      Created {new Date(scene.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="ml-4">
                    <span className="text-owl-400 text-sm">→</span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
