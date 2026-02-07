import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { Image } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Realm, Post, Character, Scene, SceneVisibility, LibraryImage } from '@/lib/types';
import CommentSection from '@/components/CommentSection';
import ReactionBar from '@/components/ReactionBar';
import AttachImageModal from '@/components/AttachImageModal';

export default function RealmDetail() {
  const { realmId } = useParams<{ realmId: string }>();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [realm, setRealm] = useState<Realm | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(true);
  const [showPostForm, setShowPostForm] = useState(false);

  // Scenes state
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [showSceneForm, setShowSceneForm] = useState(false);
  const [newScene, setNewScene] = useState({
    title: '',
    openingContent: '',
    visibility: 'PUBLIC' as SceneVisibility,
    character_id: undefined as number | undefined,
  });
  const [sceneCreating, setSceneCreating] = useState(false);

  const [showImageModal, setShowImageModal] = useState(false);
  const [attachedImage, setAttachedImage] = useState<LibraryImage | null>(null);

  // Open-starter "Request to Join" state
  const [joinLoading, setJoinLoading] = useState<Record<number, boolean>>({});
  const [joinSent, setJoinSent] = useState<Record<number, boolean>>({});
  const [joinError, setJoinError] = useState<Record<number, string>>({});
  const [newPost, setNewPost] = useState({
    title: '',
    content: '',
    content_type: 'ic' as 'ic' | 'ooc' | 'narration',
    post_kind: 'general' as 'general' | 'open_starter' | 'finished_piece',
    character_id: undefined as number | undefined,
  });

  useEffect(() => {
    const loadData = async () => {
      if (!realmId) return;

      try {
        const [realmData, postsData, charactersData, scenesData] = await Promise.all([
          apiClient.getRealm(Number(realmId)),
          apiClient.getRealmPosts(Number(realmId)),
          apiClient.getCharacters(),
          apiClient.listScenes(Number(realmId)).catch(() => [] as Scene[]),
        ]);
        setRealm(realmData);
        setPosts(postsData);
        setCharacters(charactersData);
        setScenes(scenesData);
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
        post_kind: 'general',
        character_id: undefined,
      });
      setAttachedImage(null);
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

  const requestToJoin = async (postId: number) => {
    if (!user?.username) {
      setJoinError(m => ({ ...m, [postId]: 'You must be logged in.' }));
      return;
    }
    setJoinLoading(m => ({ ...m, [postId]: true }));
    setJoinError(m => { const { [postId]: _, ...rest } = m; return rest; });
    try {
      await apiClient.createComment(postId, {
        content: `@${user.username} requested to join this starter.`,
        content_type: 'ooc',
      });
      setJoinSent(m => ({ ...m, [postId]: true }));
    } catch (e) {
      setJoinError(m => ({ ...m, [postId]: 'Failed to send request. Please try again.' }));
      console.error(e);
    } finally {
      setJoinLoading(m => ({ ...m, [postId]: false }));
    }
  };

  const handleCreateScene = async () => {
    if (!realmId || !newScene.title.trim() || !newScene.openingContent.trim()) return;
    setSceneCreating(true);
    try {
      const scene = await apiClient.createScene({
        realm_id: Number(realmId),
        title: newScene.title.trim(),
        visibility: newScene.visibility,
      });
      await apiClient.createScenePost(scene.id, {
        content: newScene.openingContent.trim(),
        character_id: newScene.character_id,
      });
      navigate(`/scenes/${scene.id}`);
    } catch (err) {
      console.error('Failed to create scene:', err);
      alert('Failed to create scene. Make sure you are a member of this realm.');
    } finally {
      setSceneCreating(false);
    }
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

  const getPostKindBadge = (postKind?: string) => {
    if (!postKind || postKind === 'general') return null;
    const kinds: Record<string, { label: string; className: string }> = {
      open_starter: { label: 'Open Starter', className: 'bg-teal-700 text-white' },
      finished_piece: { label: 'Finished Piece', className: 'bg-rose-700 text-white' },
    };
    const kind = kinds[postKind];
    if (!kind) return null;
    return (
      <span className={`px-2 py-1 text-xs font-semibold rounded ${kind.className}`}>
        {kind.label}
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
              {!realm.is_commons && (
                <button onClick={handleJoinRealm} className="btn btn-primary">
                  Join Realm
                </button>
              )}
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

      {/* Scenes section */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-2xl font-bold">Scenes</h2>
          <button
            onClick={() => setShowSceneForm(!showSceneForm)}
            className="btn btn-primary text-sm"
          >
            {showSceneForm ? 'Cancel' : '+ New Scene'}
          </button>
        </div>

        {showSceneForm && (
          <div className="card mb-4">
            <h3 className="text-lg font-semibold mb-3">Create Open Starter Scene</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1">Title</label>
                <input
                  type="text"
                  value={newScene.title}
                  onChange={(e) => setNewScene({ ...newScene, title: e.target.value })}
                  className="input"
                  placeholder="Scene title..."
                />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Opening Post</label>
                <textarea
                  value={newScene.openingContent}
                  onChange={(e) => setNewScene({ ...newScene, openingContent: e.target.value })}
                  className="textarea"
                  placeholder="Write the opening turn..."
                  rows={4}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium mb-1">Visibility</label>
                  <select
                    value={newScene.visibility}
                    onChange={(e) => setNewScene({ ...newScene, visibility: e.target.value as SceneVisibility })}
                    className="input"
                  >
                    <option value="PUBLIC">Public</option>
                    <option value="UNLISTED">Unlisted</option>
                    <option value="PRIVATE">Private</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1">Character (optional)</label>
                  <select
                    value={newScene.character_id ?? ''}
                    onChange={(e) => setNewScene({ ...newScene, character_id: e.target.value ? Number(e.target.value) : undefined })}
                    className="input"
                  >
                    <option value="">Post as yourself</option>
                    {characters.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              </div>
              <button
                onClick={handleCreateScene}
                disabled={sceneCreating || !newScene.title.trim() || !newScene.openingContent.trim()}
                className="btn btn-primary"
              >
                {sceneCreating ? 'Creating...' : 'Create Scene'}
              </button>
            </div>
          </div>
        )}

        {scenes.length === 0 ? (
          <div className="card text-center">
            <p className="text-gray-400 text-sm">No scenes yet. Create one to start a collaborative story!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {scenes.map((s) => (
              <div
                key={s.id}
                className="card flex items-center justify-between cursor-pointer hover:border-owl-500 transition-colors"
                onClick={() => navigate(`/scenes/${s.id}`)}
              >
                <div>
                  <span className="font-semibold">{s.title}</span>
                  <span className="text-xs text-gray-500 ml-2">
                    {s.post_count} {s.post_count === 1 ? 'turn' : 'turns'}
                  </span>
                </div>
                <span className={`px-2 py-0.5 text-xs font-semibold rounded ${
                  s.visibility === 'PUBLIC' ? 'bg-green-600 text-white'
                    : s.visibility === 'UNLISTED' ? 'bg-yellow-600 text-white'
                    : 'bg-red-600 text-white'
                }`}>
                  {s.visibility === 'PUBLIC' ? 'Public' : s.visibility === 'UNLISTED' ? 'Unlisted' : 'Private'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Create post section */}
      <div className="mb-6">
        {!showPostForm ? (
          <button
            onClick={() => {
              if (realm.is_commons) {
                setNewPost((prev) => ({ ...prev, content_type: 'ooc' }));
              }
              setShowPostForm(true);
            }}
            className="btn btn-primary w-full"
          >
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
                <label className="block text-sm font-medium mb-2">Content</label>
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
                  <label className="block text-sm font-medium mb-2">Voice</label>
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
                    <option value="ooc">Out-of-Character (OOC)</option>
                    <option value="ic">In-Character (IC)</option>
                    <option value="narration">Narration</option>
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2">Post Kind</label>
                  <select
                    value={newPost.post_kind}
                    onChange={(e) =>
                      setNewPost({
                        ...newPost,
                        post_kind: e.target.value as 'general' | 'open_starter' | 'finished_piece',
                      })
                    }
                    className="input"
                  >
                    <option value="general">General</option>
                    <option value="open_starter">Open Starter</option>
                    <option value="finished_piece">Finished Piece</option>
                  </select>
                </div>
              </div>

              {!realm.is_commons && (
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
              )}

              {attachedImage && (
                <div className="flex items-center gap-3 p-2 rounded-lg bg-gray-800/50 border border-gray-700">
                  <img
                    src={attachedImage.url}
                    alt={attachedImage.prompt_summary || 'Attached image'}
                    className="w-12 h-16 rounded object-cover"
                  />
                  <span className="text-xs text-gray-400 flex-1 truncate">
                    {attachedImage.prompt_summary || 'Attached image'}
                  </span>
                  <button
                    type="button"
                    onClick={() => setAttachedImage(null)}
                    className="text-xs text-red-400 hover:text-red-300 transition-colors"
                  >
                    Remove
                  </button>
                </div>
              )}

              <div className="flex gap-4">
                <button onClick={handleCreatePost} className="btn btn-primary">
                  Post
                </button>
                <button
                  type="button"
                  onClick={() => setShowImageModal(true)}
                  className="btn btn-secondary flex items-center gap-1.5"
                >
                  <Image className="w-4 h-4" />
                  Attach image
                </button>
                <button
                  onClick={() => {
                    setShowPostForm(false);
                    setAttachedImage(null);
                    setNewPost({
                      title: '',
                      content: '',
                      content_type: 'ic',
                      post_kind: 'general',
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
                      {getPostKindBadge(post.post_kind)}
                      {characterName ? (
                        <span className="text-sm font-medium text-owl-400">{characterName}</span>
                      ) : post.author_username ? (
                        <Link to={`/u/${encodeURIComponent(post.author_username)}`} className="text-sm text-gray-400 hover:text-owl-300 hover:underline transition-colors">@{post.author_username}</Link>
                      ) : null}
                    </div>
                    <span className="text-xs text-gray-500">
                      {new Date(post.created_at).toLocaleDateString()}
                    </span>
                  </div>

                  {/* Post content */}
                  {post.title && <h3 className="text-xl font-semibold mb-2">{post.title}</h3>}
                  <p className="text-gray-300 whitespace-pre-wrap">{post.content}</p>

                  {post.post_kind === 'open_starter' && (
                    <div className="mt-3 p-3 bg-teal-900/30 border border-teal-800 rounded-lg">
                      <p className="text-xs text-teal-300 mb-2">
                        Open Starter — use comments for OOC. Roleplay continues in a Scene.
                      </p>
                      <button
                        onClick={() => requestToJoin(post.id)}
                        disabled={joinLoading[post.id] || joinSent[post.id]}
                        className={`text-xs px-3 py-1 rounded ${
                          joinSent[post.id]
                            ? 'bg-green-700 text-green-200 cursor-default'
                            : joinLoading[post.id]
                              ? 'bg-gray-700 text-gray-400 cursor-wait'
                              : 'bg-teal-700 text-white hover:bg-teal-600 transition-colors'
                        }`}
                      >
                        {joinLoading[post.id] ? 'Sending\u2026' : joinSent[post.id] ? 'Request Sent' : 'Request to Join'}
                      </button>
                      {joinError[post.id] && (
                        <p className="text-red-400 text-xs mt-1">{joinError[post.id]}</p>
                      )}
                    </div>
                  )}

                  <ReactionBar postId={post.id} />
                  <CommentSection postId={post.id} characters={characters} defaultExpanded={joinSent[post.id]} />
                </div>
              );
            })}
          </div>
        )}
      </div>

      <AttachImageModal
        open={showImageModal}
        onClose={() => setShowImageModal(false)}
        onSelect={(img) => { setAttachedImage(img); setShowImageModal(false); }}
        selectedId={attachedImage?.id}
      />
    </div>
  );
}
