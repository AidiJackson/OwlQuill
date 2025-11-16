import { useState, useEffect } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { Post, Realm } from '@/lib/types';

export default function Home() {
  const [realms, setRealms] = useState<Realm[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        const realmsData = await apiClient.getRealms();
        setRealms(realmsData);

        if (realmsData.length > 0) {
          const allPosts = await Promise.all(
            realmsData.slice(0, 3).map((realm) => apiClient.getRealmPosts(realm.id))
          );
          setPosts(allPosts.flat().sort((a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          ));
        }
      } catch (error) {
        console.error('Failed to load data:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, []);

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
          {posts.map((post) => (
            <div key={post.id} className="card">
              {post.title && (
                <h3 className="text-xl font-semibold mb-2">{post.title}</h3>
              )}
              <p className="text-gray-300 whitespace-pre-wrap">{post.content}</p>
              <div className="mt-4 text-sm text-gray-500">
                {new Date(post.created_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
