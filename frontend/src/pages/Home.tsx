import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Post, Realm, Character } from '@/lib/types';

export default function Home() {
  const [realms, setRealms] = useState<Realm[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        // Load feed posts from realms the user is a member of
        const feedPosts = await apiClient.getFeed();
        setPosts(feedPosts);

        // Load realms and characters for display mapping
        const [realmsData, charactersData] = await Promise.all([
          apiClient.getRealms(),
          apiClient.getCharacters()
        ]);
        setRealms(realmsData);
        setCharacters(charactersData);
      } catch (error) {
        console.error('Failed to load data:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, []);

  const getRealmName = (realmId?: number): string => {
    if (!realmId) return 'Unknown Realm';
    const realm = realms.find(r => r.id === realmId);
    return realm?.name || 'Unknown Realm';
  };

  const getCharacterName = (characterId?: number): string | null => {
    if (!characterId) return null;
    const character = characters.find(c => c.id === characterId);
    return character?.name || null;
  };

  const getPostTypeBadge = (contentType: string) => {
    const badges = {
      ic: { label: 'IC', className: 'bg-purple-600 text-white' },
      ooc: { label: 'OOC', className: 'bg-blue-600 text-white' },
      narration: { label: 'NARRATION', className: 'bg-amber-600 text-white' }
    };
    const badge = badges[contentType as keyof typeof badges] || badges.ic;
    return (
      <span className={`px-2 py-1 text-xs font-semibold rounded ${badge.className}`}>
        {badge.label}
      </span>
    );
  };

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Loading...</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h1 className="text-3xl font-bold mb-8">Home Feed</h1>

      {posts.length === 0 ? (
        <div className="card text-center">
          <p className="text-gray-400 mb-4">No posts yet!</p>
          <p className="text-sm text-gray-500">
            Join a realm and start posting to see content here.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {posts.map((post) => {
            const characterName = getCharacterName(post.character_id);
            const realmName = getRealmName(post.realm_id);

            return (
              <div key={post.id} className="card">
                {/* Post header with metadata */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {getPostTypeBadge(post.content_type)}
                    <span className="text-sm text-gray-400">
                      {characterName && <span className="font-medium text-owl-400">{characterName}</span>}
                      {characterName && ' in '}
                      <span className="text-owl-300">{realmName}</span>
                    </span>
                  </div>
                  <span className="text-xs text-gray-500">
                    {new Date(post.created_at).toLocaleDateString()}
                  </span>
                </div>

                {/* Post content */}
                {post.title && (
                  <h3 className="text-xl font-semibold mb-2">{post.title}</h3>
                )}
                <p className="text-gray-300 whitespace-pre-wrap">{post.content}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
