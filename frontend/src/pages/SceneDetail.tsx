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
  const [showReportModal, setShowReportModal] = useState<number | null>(null);
  const [reportReason, setReportReason] = useState<'harassment' | 'nsfw' | 'spam' | 'other'>('spam');
  const [reportDetails, setReportDetails] = useState('');

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

  const handleBlockUser = async (userId: number) => {
    if (confirm('Are you sure you want to block this user?')) {
      try {
        await apiClient.createBlock(userId);
        alert('User blocked successfully. Their content will no longer appear.');
        window.location.reload();
      } catch (error) {
        console.error('Failed to block user:', error);
        alert('Failed to block user. Please try again.');
      }
    }
  };

  const handleReportPost = async (postId: number) => {
    try {
      await apiClient.createReport({
        target_type: 'scene_post',
        target_id: postId,
        reason: reportReason,
        details: reportDetails || undefined,
      });
      alert('Report submitted successfully. Thank you for helping keep the community safe.');
      setShowReportModal(null);
      setReportDetails('');
      setReportReason('spam');
    } catch (error) {
      console.error('Failed to report post:', error);
      alert('Failed to submit report. Please try again.');
    }
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
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          {characterName ? (
                            <span className="font-semibold text-owl-400">{characterName}</span>
                          ) : (
                            <span className="text-gray-500">Anonymous</span>
                          )}
                          <span className="text-xs text-gray-500">
                            {new Date(post.created_at).toLocaleString()}
                          </span>
                        </div>
                        <div className="relative group">
                          <button className="text-gray-400 hover:text-gray-200 px-2">⋮</button>
                          <div className="hidden group-hover:block absolute right-0 mt-2 w-48 bg-gray-800 border border-gray-700 rounded shadow-lg z-10">
                            <button
                              onClick={() => handleBlockUser(post.author_user_id)}
                              className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-700"
                            >
                              Block User
                            </button>
                            <button
                              onClick={() => setShowReportModal(post.id)}
                              className="block w-full text-left px-4 py-2 text-sm hover:bg-gray-700"
                            >
                              Report Post
                            </button>
                          </div>
                        </div>
                      </div>
                      <p className="text-gray-300 whitespace-pre-wrap">{post.content}</p>
                    </div>
                  </div>

                  {/* Report modal */}
                  {showReportModal === post.id && (
                    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                      <div className="bg-gray-800 p-6 rounded-lg max-w-md w-full mx-4">
                        <h3 className="text-xl font-bold mb-4">Report Post</h3>
                        <div className="space-y-4">
                          <div>
                            <label className="block text-sm font-medium mb-2">Reason</label>
                            <select
                              value={reportReason}
                              onChange={(e) => setReportReason(e.target.value as any)}
                              className="input"
                            >
                              <option value="harassment">Harassment</option>
                              <option value="nsfw">NSFW Content</option>
                              <option value="spam">Spam</option>
                              <option value="other">Other</option>
                            </select>
                          </div>
                          <div>
                            <label className="block text-sm font-medium mb-2">Additional Details (Optional)</label>
                            <textarea
                              value={reportDetails}
                              onChange={(e) => setReportDetails(e.target.value)}
                              className="textarea"
                              rows={3}
                              placeholder="Provide any additional context..."
                            />
                          </div>
                          <div className="flex gap-4">
                            <button
                              onClick={() => handleReportPost(post.id)}
                              className="btn btn-primary flex-1"
                            >
                              Submit Report
                            </button>
                            <button
                              onClick={() => setShowReportModal(null)}
                              className="btn btn-secondary flex-1"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
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
