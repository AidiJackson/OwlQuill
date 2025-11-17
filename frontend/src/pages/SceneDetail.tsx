import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Scene, Post, Character } from '@/lib/types';

export default function SceneDetail() {
  const { sceneId } = useParams<{ sceneId: string }>();
  const navigate = useNavigate();
  const [scene, setScene] = useState<Scene | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [showPostForm, setShowPostForm] = useState(false);
  const [newPost, setNewPost] = useState({
    title: '',
    content: '',
    content_type: 'ic' as 'ic' | 'ooc' | 'narration',
    character_id: undefined as number | undefined,
  });

  useEffect(() => {
    const loadData = async () => {
      if (!sceneId) return;

      try {
        const [sceneData, postsData, charactersData] = await Promise.all([
          apiClient.getScene(Number(sceneId)),
          apiClient.getScenePosts(Number(sceneId)),
          apiClient.getCharacters(),
        ]);
        setScene(sceneData);
        setPosts(postsData);
        setCharacters(charactersData);
      } catch (error) {
        console.error('Failed to load scene:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [sceneId]);

  const handleCreatePost = async () => {
    if (!sceneId || !newPost.content.trim()) return;

    try {
      const createdPost = await apiClient.createPost(Number(sceneId), newPost);
      setPosts([createdPost, ...posts]);
      setNewPost({
        title: '',
        content: '',
        content_type: 'ic',
        character_id: undefined,
      });
      setShowPostForm(false);
    } catch (error) {
      console.error('Failed to create post:', error);
      alert('Failed to create post. Make sure you are a member of this realm.');
    }
  };

  const getCharacterName = (characterId?: number): string | null => {
    if (!characterId) return null;
    const character = characters.find((c) => c.id === characterId);
    return character?.name || null;
  };

  const getPostTypeBadge = (contentType: string) => {
    const badges = {
      ic: { label: 'IC', className: 'bg-purple-600 text-white' },
      ooc: { label: 'OOC', className: 'bg-blue-600 text-white' },
      narration: { label: 'NARRATION', className: 'bg-amber-600 text-white' },
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

  if (!scene) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Scene not found</p>
        <button onClick={() => navigate(-1)} className="btn btn-secondary mt-4">
          Go Back
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      {/* Scene header */}
      <div className="card mb-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1">
            <h1 className="text-3xl font-bold mb-2">{scene.title}</h1>
            {scene.description && (
              <p className="text-gray-300 whitespace-pre-wrap mb-3">{scene.description}</p>
            )}
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span>Created {new Date(scene.created_at).toLocaleDateString()}</span>
              <button
                onClick={() => navigate(`/realms/${scene.realm_id}`)}
                className="text-owl-400 hover:text-owl-300 transition-colors"
              >
                ← Back to Realm
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Create post section */}
      <div className="mb-6">
        {!showPostForm ? (
          <button onClick={() => setShowPostForm(true)} className="btn btn-primary w-full">
            + New Post
          </button>
        ) : (
          <div className="card">
            <h3 className="text-xl font-semibold mb-4">Create Post</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-2">Title (optional)</label>
                <input
                  type="text"
                  value={newPost.title}
                  onChange={(e) => setNewPost({ ...newPost, title: e.target.value })}
                  className="input"
                  placeholder="Post title..."
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-2">Content *</label>
                <textarea
                  value={newPost.content}
                  onChange={(e) => setNewPost({ ...newPost, content: e.target.value })}
                  className="textarea"
                  placeholder="Write your post..."
                  rows={6}
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-2">Post Type</label>
                  <select
                    value={newPost.content_type}
                    onChange={(e) =>
                      setNewPost({
                        ...newPost,
                        content_type: e.target.value as 'ic' | 'ooc' | 'narration',
                      })
                    }
                    className="input"
                  >
                    <option value="ic">In-Character (IC)</option>
                    <option value="ooc">Out-of-Character (OOC)</option>
                    <option value="narration">Narration</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Character (optional)</label>
                  <select
                    value={newPost.character_id || ''}
                    onChange={(e) =>
                      setNewPost({
                        ...newPost,
                        character_id: e.target.value ? Number(e.target.value) : undefined,
                      })
                    }
                    className="input"
                  >
                    <option value="">None</option>
                    {characters.map((char) => (
                      <option key={char.id} value={char.id}>
                        {char.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex gap-4">
                <button onClick={handleCreatePost} className="btn btn-primary">
                  Post
                </button>
                <button
                  onClick={() => {
                    setShowPostForm(false);
                    setNewPost({
                      title: '',
                      content: '',
                      content_type: 'ic',
                      character_id: undefined,
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

      {/* Posts list */}
      <div>
        <h2 className="text-2xl font-bold mb-4">Posts</h2>
        {posts.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400">No posts yet in this scene.</p>
            <p className="text-sm text-gray-500 mt-2">Be the first to post!</p>
          </div>
        ) : (
          <div className="space-y-4">
            {posts.map((post) => {
              const characterName = getCharacterName(post.character_id);

              return (
                <div key={post.id} className="card">
                  {/* Post header */}
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      {getPostTypeBadge(post.content_type)}
                      {characterName && (
                        <span className="text-sm font-medium text-owl-400">{characterName}</span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500">
                      {new Date(post.created_at).toLocaleDateString()}
                    </span>
                  </div>

                  {/* Post content */}
                  {post.title && <h3 className="text-xl font-semibold mb-2">{post.title}</h3>}
                  <p className="text-gray-300 whitespace-pre-wrap">{post.content}</p>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
