import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { UserProfile } from '@/lib/types';

export default function UserProfilePage() {
  const { username } = useParams<{ username: string }>();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadProfile = async () => {
      if (!username) return;

      try {
        setLoading(true);
        setError(null);
        const data = await apiClient.getUserProfile(username);
        setProfile(data);

        // Log analytics event
        apiClient.logEvent('profile_view', { username });
      } catch (err: any) {
        console.error('Failed to load profile:', err);
        setError(err.message || 'Failed to load profile');
      } finally {
        setLoading(false);
      }
    };

    loadProfile();
  }, [username]);

  if (loading) {
    return (
      <div className="p-4 md:p-8">
        <p className="text-gray-400">Loading profile...</p>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="p-4 md:p-8">
        <div className="card bg-red-900/20 border-red-700">
          <p className="text-red-400">{error || 'Profile not found'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-8">
      {/* Profile Header */}
      <div className="card mb-6">
        <div className="flex flex-col md:flex-row items-start md:items-center gap-4 md:gap-6">
          {/* Avatar */}
          <div className="w-20 h-20 md:w-24 md:h-24 rounded-full bg-gradient-to-br from-purple-600 to-pink-600 flex items-center justify-center text-white text-2xl md:text-3xl font-bold flex-shrink-0">
            {profile.avatar_url ? (
              <img src={profile.avatar_url} alt={profile.username} className="w-full h-full rounded-full object-cover" />
            ) : (
              profile.username.charAt(0).toUpperCase()
            )}
          </div>

          {/* Profile Info */}
          <div className="flex-1 w-full md:w-auto">
            <h1 className="text-2xl md:text-3xl font-bold mb-1">
              {profile.display_name || profile.username}
            </h1>
            <p className="text-gray-400 mb-2">@{profile.username}</p>
            {profile.bio && (
              <p className="text-gray-300 mb-4">{profile.bio}</p>
            )}

            {/* Stats */}
            <div className="flex flex-wrap gap-4 md:gap-6 text-sm">
              <div>
                <span className="font-semibold text-white">{profile.total_posts}</span>
                <span className="text-gray-400 ml-1">Posts</span>
              </div>
              <div>
                <span className="font-semibold text-white">{profile.joined_realms_count}</span>
                <span className="text-gray-400 ml-1">Realms</span>
              </div>
              <div>
                <span className="font-semibold text-white">{profile.follower_count}</span>
                <span className="text-gray-400 ml-1">Followers</span>
              </div>
              <div>
                <span className="font-semibold text-white">{profile.following_count}</span>
                <span className="text-gray-400 ml-1">Following</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Activity */}
      <div className="card">
        <h2 className="text-xl md:text-2xl font-bold mb-4">Recent Posts</h2>

        {profile.recent_posts.length === 0 ? (
          <p className="text-gray-400 text-center py-8">No posts yet</p>
        ) : (
          <div className="space-y-4">
            {profile.recent_posts.map((post) => (
              <div key={post.id} className="border border-gray-700 rounded-lg p-4 hover:border-gray-600 transition-colors">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 text-sm text-gray-400">
                    {post.realm && (
                      <Link to={`/realms/${post.realm.id}`} className="text-purple-400 hover:text-purple-300">
                        {post.realm.name}
                      </Link>
                    )}
                    {post.character && (
                      <span className="text-pink-400">as {post.character.name}</span>
                    )}
                  </div>
                  <span className="text-xs text-gray-500">
                    {new Date(post.created_at).toLocaleDateString()}
                  </span>
                </div>

                {post.title && (
                  <h3 className="font-semibold mb-2">{post.title}</h3>
                )}

                <p className="text-gray-300 text-sm line-clamp-3">{post.content}</p>

                <div className="mt-2">
                  <span className={`px-2 py-1 text-xs font-semibold rounded ${
                    post.content_type === 'ic' ? 'bg-purple-600 text-white' :
                    post.content_type === 'ooc' ? 'bg-blue-600 text-white' :
                    'bg-amber-600 text-white'
                  }`}>
                    {post.content_type.toUpperCase()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
