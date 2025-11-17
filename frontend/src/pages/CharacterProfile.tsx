import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { CharacterProfile } from '@/lib/types';

export default function CharacterProfilePage() {
  const { characterId } = useParams<{ characterId: string }>();
  const [profile, setProfile] = useState<CharacterProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadProfile = async () => {
      if (!characterId) return;

      try {
        setLoading(true);
        setError(null);
        const data = await apiClient.getCharacterProfile(parseInt(characterId));
        setProfile(data);

        // Log analytics event
        apiClient.logEvent('character_view', { characterId: parseInt(characterId) });
      } catch (err: any) {
        console.error('Failed to load character profile:', err);
        setError(err.message || 'Failed to load character profile');
      } finally {
        setLoading(false);
      }
    };

    loadProfile();
  }, [characterId]);

  if (loading) {
    return (
      <div className="p-4 md:p-8">
        <p className="text-gray-400">Loading character...</p>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="p-4 md:p-8">
        <div className="card bg-red-900/20 border-red-700">
          <p className="text-red-400">{error || 'Character not found'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-8">
      {/* Character Header */}
      <div className="card mb-6">
        <div className="flex flex-col md:flex-row items-start md:items-center gap-4 md:gap-6">
          {/* Avatar/Portrait */}
          <div className="w-20 h-20 md:w-24 md:h-24 rounded-full bg-gradient-to-br from-pink-600 to-purple-600 flex items-center justify-center text-white text-2xl md:text-3xl font-bold flex-shrink-0">
            {profile.avatar_url ? (
              <img src={profile.avatar_url} alt={profile.name} className="w-full h-full rounded-full object-cover" />
            ) : (
              profile.name.charAt(0).toUpperCase()
            )}
          </div>

          {/* Character Info */}
          <div className="flex-1 w-full md:w-auto">
            <h1 className="text-2xl md:text-3xl font-bold mb-1">
              {profile.name}
              {profile.alias && <span className="text-gray-400 text-xl ml-2">"{profile.alias}"</span>}
            </h1>

            <p className="text-gray-400 mb-3">
              Played by{' '}
              <Link to={`/u/${profile.owner.username}`} className="text-purple-400 hover:text-purple-300">
                @{profile.owner.username}
              </Link>
            </p>

            {/* Character Details */}
            <div className="flex flex-wrap gap-3 md:gap-4 text-sm mb-3">
              {profile.species && (
                <span className="px-2 py-1 bg-gray-700 rounded text-gray-300">
                  {profile.species}
                </span>
              )}
              {profile.role && (
                <span className="px-2 py-1 bg-gray-700 rounded text-gray-300">
                  {profile.role}
                </span>
              )}
              {profile.era && (
                <span className="px-2 py-1 bg-gray-700 rounded text-gray-300">
                  {profile.era}
                </span>
              )}
              {profile.age && (
                <span className="px-2 py-1 bg-gray-700 rounded text-gray-300">
                  Age: {profile.age}
                </span>
              )}
            </div>

            {/* Bio */}
            {profile.short_bio && (
              <p className="text-gray-300 mb-3">{profile.short_bio}</p>
            )}

            {/* Stats */}
            <div className="flex flex-wrap gap-4 md:gap-6 text-sm">
              <div>
                <span className="font-semibold text-white">{profile.posts_count}</span>
                <span className="text-gray-400 ml-1">Posts</span>
              </div>
              <div>
                <span className="font-semibold text-white">{profile.realms_count}</span>
                <span className="text-gray-400 ml-1">Realms</span>
              </div>
            </div>
          </div>
        </div>

        {/* Long Bio Section (if exists) */}
        {profile.long_bio && (
          <div className="mt-6 pt-6 border-t border-gray-700">
            <h2 className="text-lg font-semibold mb-2">Background</h2>
            <p className="text-gray-300 whitespace-pre-wrap">{profile.long_bio}</p>
          </div>
        )}

        {/* Tags */}
        {profile.tags && (
          <div className="mt-4 pt-4 border-t border-gray-700">
            <div className="flex flex-wrap gap-2">
              {profile.tags.split(',').map((tag, index) => (
                <span key={index} className="px-2 py-1 bg-purple-900/30 text-purple-300 rounded text-sm">
                  #{tag.trim()}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Recent Posts */}
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
