import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Scene, ScenePost, Character, Realm } from '@/lib/types';

export default function SceneDetail() {
  const { sceneId } = useParams<{ sceneId: string }>();
  const navigate = useNavigate();
  const [scene, setScene] = useState<Scene | null>(null);
  const [posts, setPosts] = useState<ScenePost[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [realm, setRealm] = useState<Realm | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [replyContent, setReplyContent] = useState('');
  const [selectedCharacterId, setSelectedCharacterId] = useState<number | undefined>(undefined);
  const [posting, setPosting] = useState(false);

  useEffect(() => {
    const loadData = async () => {
      if (!sceneId) return;

      try {
        const [sceneData, charactersData] = await Promise.all([
          apiClient.getScene(Number(sceneId)),
          apiClient.getCharacters(),
        ]);

        setScene(sceneData.scene);
        setPosts(sceneData.posts);
        setCharacters(charactersData);

        // Auto-select first character if available
        if (charactersData.length > 0 && !selectedCharacterId) {
          setSelectedCharacterId(charactersData[0].id);
        }

        // Load realm if scene has one
        if (sceneData.scene.realm_id) {
          try {
            const realmData = await apiClient.getRealm(sceneData.scene.realm_id);
            setRealm(realmData);
          } catch (err) {
            console.error('Failed to load realm:', err);
          }
        }

        setError(null);
      } catch (error) {
        console.error('Failed to load scene:', error);
        setError('Failed to load scene. It may not exist or you may not have access.');
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [sceneId]);

  const handleCreatePost = async () => {
    if (!sceneId || !selectedCharacterId || !replyContent.trim()) {
      return;
    }

    setPosting(true);
    try {
      const newPost = await apiClient.createScenePost(Number(sceneId), {
        character_id: selectedCharacterId,
        content: replyContent,
      });

      // Add character info to the post if available
      const character = characters.find((c) => c.id === selectedCharacterId);
      if (character) {
        newPost.character = character;
      }

      setPosts([...posts, newPost]);
      setReplyContent('');

      // Update scene's last_activity_at
      if (scene) {
        setScene({ ...scene, last_activity_at: new Date().toISOString() });
      }
    } catch (error) {
      console.error('Failed to create post:', error);
      alert('Failed to post. Please try again.');
    } finally {
      setPosting(false);
    }
  };

  const getCharacterName = (post: ScenePost): string => {
    if (post.character) {
      return post.character.name;
    }
    const character = characters.find((c) => c.id === post.character_id);
    return character?.name || 'Unknown Character';
  };

  const getCharacterAvatar = (post: ScenePost): string | undefined => {
    if (post.character?.portrait_url) {
      return post.character.portrait_url;
    }
    const character = characters.find((c) => c.id === post.character_id);
    return character?.portrait_url;
  };

  const formatTimestamp = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) {
      return 'just now';
    } else if (diffMins < 60) {
      return `${diffMins}m ago`;
    } else if (diffHours < 24) {
      return `${diffHours}h ago`;
    } else if (diffDays < 7) {
      return `${diffDays}d ago`;
    } else {
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
  };

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Loading scene...</p>
      </div>
    );
  }

  if (error || !scene) {
    return (
      <div className="p-8">
        <p className="text-red-400 mb-4">{error || 'Scene not found'}</p>
        <button onClick={() => navigate('/scenes')} className="btn btn-secondary">
          Back to Scenes
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      {/* Scene Header */}
      <div className="card mb-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-2">
              <button
                onClick={() => navigate('/scenes')}
                className="text-gray-500 hover:text-gray-300 text-sm"
              >
                ← Back to Scenes
              </button>
            </div>
            <h1 className="text-3xl font-bold mb-2">{scene.title}</h1>
            {scene.summary && (
              <p className="text-gray-300 mb-4 whitespace-pre-wrap">{scene.summary}</p>
            )}
          </div>
          <div className="flex gap-2">
            {scene.is_nsfw && (
              <span className="px-3 py-1 text-sm font-semibold rounded bg-red-600 text-white h-fit">
                18+
              </span>
            )}
            {scene.has_violence && (
              <span className="px-3 py-1 text-sm font-semibold rounded bg-orange-600 text-white h-fit">
                Violence
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-4 text-sm text-gray-500">
          {realm && (
            <Link to={`/realms/${realm.id}`} className="text-owl-400 hover:text-owl-300">
              Realm: {realm.name}
            </Link>
          )}
          <span className={`px-2 py-1 rounded text-xs ${
            scene.visibility === 'public'
              ? 'bg-green-600/20 text-green-400'
              : scene.visibility === 'friends'
              ? 'bg-blue-600/20 text-blue-400'
              : 'bg-gray-600/20 text-gray-400'
          }`}>
            {scene.visibility}
          </span>
          <span>Created: {new Date(scene.created_at).toLocaleDateString()}</span>
        </div>

        {scene.tags && scene.tags.trim() && (
          <div className="mt-4 flex flex-wrap gap-2">
            {scene.tags.split(',').map((tag, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-owl-900 text-owl-300 text-xs rounded"
              >
                {tag.trim()}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Posts Thread */}
      <div className="mb-6">
        <h2 className="text-2xl font-bold mb-4">Thread</h2>
        {posts.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400">No posts yet in this scene</p>
            <p className="text-sm text-gray-500 mt-1">Be the first to start the story!</p>
          </div>
        ) : (
          <div className="space-y-4">
            {posts.map((post) => {
              const characterName = getCharacterName(post);
              const avatarUrl = getCharacterAvatar(post);

              return (
                <div key={post.id} className="card">
                  <div className="flex gap-4">
                    {avatarUrl && (
                      <div className="flex-shrink-0">
                        <img
                          src={avatarUrl}
                          alt={characterName}
                          className="w-12 h-12 rounded-full object-cover"
                          onError={(e) => {
                            e.currentTarget.style.display = 'none';
                          }}
                        />
                      </div>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-2">
                        <h4 className="font-semibold text-owl-400">{characterName}</h4>
                        <span className="text-xs text-gray-500">
                          {formatTimestamp(post.created_at)}
                        </span>
                      </div>
                      <p className="text-gray-200 whitespace-pre-wrap">{post.content}</p>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Reply Composer */}
      <div className="card">
        <h3 className="text-xl font-semibold mb-4">Reply</h3>

        {characters.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-gray-400 mb-4">You need a character to post in this scene</p>
            <Link to="/characters" className="btn btn-primary">
              Create a Character
            </Link>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">Reply as</label>
              <select
                value={selectedCharacterId || ''}
                onChange={(e) => setSelectedCharacterId(Number(e.target.value))}
                className="input"
              >
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
                value={replyContent}
                onChange={(e) => setReplyContent(e.target.value)}
                className="textarea"
                rows={6}
                placeholder="Write your character's response..."
              />
            </div>

            <button
              onClick={handleCreatePost}
              disabled={posting || !replyContent.trim() || !selectedCharacterId}
              className="btn btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {posting ? 'Posting...' : 'Send Reply'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
