import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Realm } from '@/lib/types';

export default function Realms() {
  const [myRealms, setMyRealms] = useState<Realm[]>([]);
  const [discoverRealms, setDiscoverRealms] = useState<Realm[]>([]);
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
      const [myRealmsData, allRealmsData] = await Promise.all([
        apiClient.getMyRealms(),
        apiClient.getRealms(),
      ]);
      setMyRealms(myRealmsData);

      // Filter out realms user is already a member of from discover list
      const myRealmIds = new Set(myRealmsData.map(r => r.id));
      setDiscoverRealms(allRealmsData.filter(r => !myRealmIds.has(r.id)));
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
      await loadRealms(); // Reload to update the lists
    } catch (error) {
      console.error('Failed to join realm:', error);
    }
  };

  const renderRealmCard = (realm: Realm, showJoinButton = false) => (
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
          {showJoinButton && (
            <button
              onClick={() => handleJoinRealm(realm.id)}
              className="btn btn-primary ml-4"
            >
              Join
            </button>
          )}
        </div>
      </div>
    </div>
  );

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

      {/* Your Realms Section */}
      <div className="mb-12">
        <h2 className="text-2xl font-bold mb-4">Your Realms</h2>
        {myRealms.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400 mb-2">You haven't joined any realms yet.</p>
            <p className="text-sm text-gray-500">
              Browse the Discover section below to find realms to join!
            </p>
          </div>
        ) : (
          <div className="grid gap-4">
            {myRealms.map((realm) => renderRealmCard(realm, false))}
          </div>
        )}
      </div>

      {/* Discover Realms Section */}
      <div>
        <h2 className="text-2xl font-bold mb-4">Discover Realms</h2>
        {discoverRealms.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400">No new realms to discover.</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {discoverRealms.map((realm) => renderRealmCard(realm, true))}
          </div>
        )}
      </div>
    </div>
  );
}
