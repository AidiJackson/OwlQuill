import { useState, useEffect } from 'react';
import { Search, UserPlus, UserCheck, Eye } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { User, Realm } from '@/lib/types';

type Tab = 'people' | 'realms';

export default function Discover() {
  const [activeTab, setActiveTab] = useState<Tab>('people');
  const [searchQuery, setSearchQuery] = useState('');
  const [users, setUsers] = useState<User[]>([]);
  const [realms, setRealms] = useState<Realm[]>([]);
  const [loading, setLoading] = useState(false);
  const [followingIds, setFollowingIds] = useState<Set<number>>(new Set());
  const navigate = useNavigate();

  const fetchUsers = async (search?: string) => {
    setLoading(true);
    try {
      const results = await apiClient.discoverUsers(search);
      setUsers(results);
    } catch (error) {
      console.error('Failed to fetch users:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchRealms = async (search?: string) => {
    setLoading(true);
    try {
      const results = await apiClient.discoverRealms(search);
      setRealms(results);
    } catch (error) {
      console.error('Failed to fetch realms:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchFollowing = async () => {
    try {
      const connections = await apiClient.getFollowing();
      setFollowingIds(new Set(connections.map(c => c.following_id)));
    } catch (error) {
      console.error('Failed to fetch following:', error);
    }
  };

  useEffect(() => {
    if (activeTab === 'people') {
      fetchUsers();
      fetchFollowing();
    } else {
      fetchRealms();
    }
  }, [activeTab]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (activeTab === 'people') {
      fetchUsers(searchQuery || undefined);
    } else {
      fetchRealms(searchQuery || undefined);
    }
  };

  const handleFollow = async (userId: number) => {
    try {
      await apiClient.followUser(userId);
      setFollowingIds(prev => new Set([...prev, userId]));
    } catch (error) {
      console.error('Failed to follow user:', error);
    }
  };

  const handleUnfollow = async (userId: number) => {
    try {
      await apiClient.unfollowUser(userId);
      setFollowingIds(prev => {
        const newSet = new Set(prev);
        newSet.delete(userId);
        return newSet;
      });
    } catch (error) {
      console.error('Failed to unfollow user:', error);
    }
  };

  const handleJoinRealm = async (realmId: number) => {
    try {
      await apiClient.joinRealm(realmId);
      navigate(`/realms/${realmId}`);
    } catch (error) {
      console.error('Failed to join realm:', error);
    }
  };

  return (
    <div className="container mx-auto max-w-6xl p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-4">Discover</h1>

        {/* Tabs */}
        <div className="flex gap-4 border-b border-gray-800 mb-6">
          <button
            onClick={() => setActiveTab('people')}
            className={`pb-3 px-4 font-medium transition-colors ${
              activeTab === 'people'
                ? 'border-b-2 border-owl-500 text-owl-500'
                : 'text-gray-400 hover:text-gray-300'
            }`}
          >
            People
          </button>
          <button
            onClick={() => setActiveTab('realms')}
            className={`pb-3 px-4 font-medium transition-colors ${
              activeTab === 'realms'
                ? 'border-b-2 border-owl-500 text-owl-500'
                : 'text-gray-400 hover:text-gray-300'
            }`}
          >
            Realms
          </button>
        </div>

        {/* Search */}
        <form onSubmit={handleSearch} className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={
              activeTab === 'people'
                ? 'Find writers and characters...'
                : 'Find realms and roleplay worlds...'
            }
            className="w-full pl-10 pr-4 py-3 bg-gray-900 border border-gray-800 rounded-lg focus:outline-none focus:border-owl-500"
          />
        </form>
      </div>

      {/* Content */}
      {loading ? (
        <div className="text-center py-12 text-gray-400">
          Loading...
        </div>
      ) : activeTab === 'people' ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {users.length === 0 ? (
            <div className="col-span-full text-center py-12 text-gray-400">
              No users found
            </div>
          ) : (
            users.map(user => {
              const isFollowing = followingIds.has(user.id);
              return (
                <div
                  key={user.id}
                  className="p-4 bg-gray-900 border border-gray-800 rounded-lg hover:border-gray-700 transition-colors"
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex-1">
                      <h3 className="font-semibold">
                        {user.display_name || user.username}
                      </h3>
                      <p className="text-sm text-gray-400">@{user.username}</p>
                    </div>
                  </div>

                  {user.bio && (
                    <p className="text-sm text-gray-400 mb-4 line-clamp-2">
                      {user.bio}
                    </p>
                  )}

                  <button
                    onClick={() => isFollowing ? handleUnfollow(user.id) : handleFollow(user.id)}
                    className={`w-full py-2 rounded-lg flex items-center justify-center gap-2 transition-colors ${
                      isFollowing
                        ? 'bg-gray-800 hover:bg-gray-700'
                        : 'bg-owl-500 hover:bg-owl-600'
                    }`}
                  >
                    {isFollowing ? (
                      <>
                        <UserCheck className="w-4 h-4" />
                        <span>Following</span>
                      </>
                    ) : (
                      <>
                        <UserPlus className="w-4 h-4" />
                        <span>Follow</span>
                      </>
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {realms.length === 0 ? (
            <div className="col-span-full text-center py-12 text-gray-400">
              No realms found
            </div>
          ) : (
            realms.map(realm => (
              <div
                key={realm.id}
                className="p-4 bg-gray-900 border border-gray-800 rounded-lg hover:border-gray-700 transition-colors"
              >
                <div className="mb-3">
                  <h3 className="font-semibold text-lg">{realm.name}</h3>
                  {realm.tagline && (
                    <p className="text-sm text-gray-400 italic">{realm.tagline}</p>
                  )}
                  {realm.genre && (
                    <span className="inline-block mt-2 px-2 py-1 text-xs bg-gray-800 rounded">
                      {realm.genre}
                    </span>
                  )}
                </div>

                {realm.description && (
                  <p className="text-sm text-gray-400 mb-4 line-clamp-3">
                    {realm.description}
                  </p>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={() => navigate(`/realms/${realm.id}`)}
                    className="flex-1 py-2 bg-gray-800 hover:bg-gray-700 rounded-lg flex items-center justify-center gap-2 transition-colors"
                  >
                    <Eye className="w-4 h-4" />
                    <span>View</span>
                  </button>
                  <button
                    onClick={() => handleJoinRealm(realm.id)}
                    className="flex-1 py-2 bg-owl-500 hover:bg-owl-600 rounded-lg transition-colors"
                  >
                    Join
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
