import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Scene, ScenePost, Character } from '@/lib/types';

export default function SceneDetail() {
  const { sceneId } = useParams<{ sceneId: string }>();
  const navigate = useNavigate();
  const [scene, setScene] = useState<Scene | null>(null);
  const [posts, setPosts] = useState<ScenePost[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [newPost, setNewPost] = useState({
    content: '',
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
      const createdPost = await apiClient.createScenePost(Number(sceneId), newPost);
      setPosts([...posts, createdPost]);
      setNewPost({
        content: '',
        character_id: undefined,
      });
    } catch (error) {
      console.error('Failed to create post:', error);
      alert('Failed to create post. Make sure you have access to this scene.');
    }
  };

  const getCharacterName = (characterId?: number): string | null => {
    if (!characterId) return null;
    const character = characters.find((c) => c.id === characterId);
    return character?.name || null;
  };

  const getCharacterAvatar = (characterId?: number): string | null => {
    if (!characterId) return null;
    const character = characters.find((c) => c.id === characterId);
    return character?.portrait_url || character?.avatar_url || null;
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
        <button onClick={() => navigate('/scenes')} className="btn btn-secondary mt-4">
          Back to Scenes
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
              <p className="text-gray-300 whitespace-pre-wrap mb-4">{scene.description}</p>
            )}
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span>{new Date(scene.created_at).toLocaleDateString()}</span>
              <span className="capitalize px-2 py-1 bg-owl-900 rounded text-owl-300">
                {scene.visibility}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Posts thread */}
      <div className="mb-6">
        <h2 className="text-2xl font-bold mb-4">Scene Thread</h2>
        {posts.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400">No posts yet in this scene.</p>
            <p className="text-sm text-gray-500 mt-2">Be the first to post!</p>
          </div>
        ) : (
          <div className="space-y-4">
            {posts.map((post) => {
              const characterName = getCharacterName(post.character_id);
              const characterAvatar = getCharacterAvatar(post.character_id);

              return (
                <div key={post.id} className="card">
                  <div className="flex items-start gap-4">
                    {/* Character avatar */}
                    <div className="w-12 h-12 rounded-full overflow-hidden bg-gray-700 flex-shrink-0">
                      {characterAvatar ? (
                        <img
                          src={characterAvatar}
                          alt={characterName || 'Avatar'}
                          className="w-full h-full object-cover"
                          onError={(e) => {
                            e.currentTarget.style.display = 'none';
                          }}
                        />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-gray-500">
                          {characterName ? characterName.charAt(0).toUpperCase() : '?'}
                        </div>
                      )}
                    </div>

                    {/* Post content */}
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-2">
                        {characterName ? (
                          <span className="font-semibold text-owl-400">{characterName}</span>
                        ) : (
                          <span className="text-gray-500">Anonymous</span>
                        )}
                        <span className="text-xs text-gray-500">
                          {new Date(post.created_at).toLocaleString()}
                        </span>
                      </div>
                      <p className="text-gray-300 whitespace-pre-wrap">{post.content}</p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Post composer */}
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">Add to Scene</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium mb-2">Post as Character</label>
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
              <option value="">None (Anonymous)</option>
              {characters.map((char) => (
                <option key={char.id} value={char.id}>
                  {char.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Your Post</label>
            <textarea
              value={newPost.content}
              onChange={(e) => setNewPost({ ...newPost, content: e.target.value })}
              className="textarea"
              placeholder="Write your roleplay post..."
              rows={6}
            />
          </div>

          <button
            onClick={handleCreatePost}
            className="btn btn-primary"
            disabled={!newPost.content.trim()}
          >
            Post
          </button>
        </div>
      </div>
    </div>
  );
}
