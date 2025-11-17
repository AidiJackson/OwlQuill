import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { Realm, Post, Character } from '@/lib/types';

export default function RealmDetail() {
  const { realmId } = useParams<{ realmId: string }>();
  const navigate = useNavigate();
  const [realm, setRealm] = useState<Realm | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [showPostForm, setShowPostForm] = useState(false);
  const [aiSuggesting, setAiSuggesting] = useState(false);
  const [aiSummarizing, setAiSummarizing] = useState(false);
  const [sceneSummary, setSceneSummary] = useState<string | null>(null);
  const [newPost, setNewPost] = useState({
    title: '',
    content: '',
    content_type: 'ic' as 'ic' | 'ooc' | 'narration',
    character_id: undefined as number | undefined,
  });

  useEffect(() => {
    const loadData = async () => {
      if (!realmId) return;

      try {
        const [realmData, postsData, charactersData] = await Promise.all([
          apiClient.getRealm(Number(realmId)),
          apiClient.getRealmPosts(Number(realmId)),
          apiClient.getCharacters(),
        ]);
        setRealm(realmData);
        setPosts(postsData);
        setCharacters(charactersData);
      } catch (error) {
        console.error('Failed to load realm:', error);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [realmId]);

  const handleJoinRealm = async () => {
    if (!realmId) return;

    try {
      await apiClient.joinRealm(Number(realmId));
      // Reload realm to update membership status (or show success message)
      alert('Successfully joined realm!');
    } catch (error) {
      console.error('Failed to join realm:', error);
      alert('Failed to join realm. You may already be a member.');
    }
  };

  const handleCreatePost = async () => {
    if (!realmId || !newPost.content.trim()) return;

    try {
      const createdPost = await apiClient.createPost(Number(realmId), newPost);
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

  const handleAiSuggestPost = async () => {
    setAiSuggesting(true);
    try {
      const characterName = newPost.character_id
        ? getCharacterName(newPost.character_id)
        : undefined;

      const recentPosts = posts.slice(0, 5).map((p) => p.content);

      const result = await apiClient.suggestPostReply({
        realm_name: realm?.name,
        character_name: characterName || undefined,
        recent_posts: recentPosts,
        tone_hint: newPost.content_type === 'ic' ? 'in-character' : undefined,
      });

      setNewPost({ ...newPost, content: result.suggested_text });
    } catch (error) {
      console.error('Failed to get AI suggestion:', error);
      alert('AI suggestion failed. The AI service may be unavailable. Please write manually.');
    } finally {
      setAiSuggesting(false);
    }
  };

  const handleAiSummarizeScene = async () => {
    setAiSummarizing(true);
    try {
      const postContents = posts.map((p) => p.content);
      const result = await apiClient.summarizeScene({
        realm_name: realm?.name,
        posts: postContents,
      });
      setSceneSummary(result.summary);
    } catch (error) {
      console.error('Failed to summarize scene:', error);
      alert('AI summarization failed. The AI service may be unavailable.');
    } finally {
      setAiSummarizing(false);
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

  if (!realm) {
    return (
      <div className="p-8">
        <p className="text-gray-400">Realm not found</p>
        <button onClick={() => navigate('/realms')} className="btn btn-secondary mt-4">
          Back to Realms
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-8">
      {/* Realm header with banner */}
      <div className="card overflow-hidden mb-6">
        {realm.banner_url && (
          <div className="h-48 w-full overflow-hidden">
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
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-3xl font-bold">{realm.name}</h1>
              {realm.tagline && <p className="text-owl-400 italic mt-1">{realm.tagline}</p>}
            </div>
            <div className="flex items-center gap-4">
              <span className={`px-3 py-1 text-sm rounded ${realm.is_public ? 'bg-green-600' : 'bg-gray-600'}`}>
                {realm.is_public ? 'Public' : 'Private'}
              </span>
              <button onClick={handleJoinRealm} className="btn btn-primary">
                Join Realm
              </button>
            </div>
          </div>

          {realm.description && (
            <p className="text-gray-300 mb-4 whitespace-pre-wrap">{realm.description}</p>
          )}

          {realm.genre && (
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-500">Genre:</span>
              <span className="text-sm text-owl-300">{realm.genre}</span>
            </div>
          )}
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
                <div className="flex justify-between items-center mb-2">
                  <label className="block text-sm font-medium">Content</label>
                  <button
                    type="button"
                    onClick={handleAiSuggestPost}
                    disabled={aiSuggesting}
                    className="text-sm text-owl-500 hover:text-owl-400 disabled:opacity-50"
                  >
                    {aiSuggesting ? 'Suggesting...' : '✨ AI Suggest Reply'}
                  </button>
                </div>
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
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-2xl font-bold">Posts</h2>
          {posts.length > 0 && (
            <button
              onClick={handleAiSummarizeScene}
              disabled={aiSummarizing}
              className="btn btn-secondary text-sm"
            >
              {aiSummarizing ? 'Summarizing...' : '✨ AI Summarize Scene'}
            </button>
          )}
        </div>

        {/* AI Summary Display */}
        {sceneSummary && (
          <div className="card mb-4 bg-owl-900/50 border border-owl-700">
            <div className="flex justify-between items-start mb-2">
              <h3 className="text-lg font-semibold text-owl-300">AI Scene Summary</h3>
              <button
                onClick={() => setSceneSummary(null)}
                className="text-gray-500 hover:text-gray-300"
              >
                ✕
              </button>
            </div>
            <p className="text-gray-300 whitespace-pre-wrap">{sceneSummary}</p>
          </div>
        )}

        {posts.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400">No posts yet in this realm.</p>
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
