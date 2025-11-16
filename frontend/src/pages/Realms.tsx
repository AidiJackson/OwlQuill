import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Realm } from '@/lib/types';

export default function Realms() {
  const [realms, setRealms] = useState<Realm[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
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
    try {
      await apiClient.joinRealm(realmId);
      alert('Joined realm successfully!');
    } catch (error) {
      console.error('Failed to join realm:', error);
    }
  };

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

      <div className="grid gap-4">
        {realms.map((realm) => (
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
                  className="btn btn-primary ml-4"
                >
                  Join
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
