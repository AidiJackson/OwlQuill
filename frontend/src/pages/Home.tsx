import { useState, useEffect, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Post, Realm, Character } from '@/lib/types';
import CommentSection from '@/components/CommentSection';
import ReactionBar from '@/components/ReactionBar';

export default function Home() {
  const navigate = useNavigate();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const user = useAuthStore((s) => s.user);

  const [realms, setRealms] = useState<Realm[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [posts, setPosts] = useState<Post[]>([]);
  const [loading, setLoading] = useState(true);

  // Quick-post composer state
  const [quickContent, setQuickContent] = useState('');
  const [quickContentType, setQuickContentType] = useState<'ooc' | 'ic' | 'narration'>('ooc');
  const [quickPostKind, setQuickPostKind] = useState<'general' | 'open_starter' | 'finished_piece'>('general');
  const [posting, setPosting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);

  // Open-starter "Request to Join" state
  const [joinLoading, setJoinLoading] = useState<Record<number, boolean>>({});
  const [joinSent, setJoinSent] = useState<Record<number, boolean>>({});
  const [joinError, setJoinError] = useState<Record<number, string>>({});

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

  const commonsRealm = realms.find(r => r.is_commons);

  const handleQuickPost = async () => {
    if (!commonsRealm || !quickContent.trim()) return;
    setPosting(true);
    setPostError(null);
    try {
      const created = await apiClient.createPost(commonsRealm.id, {
        content: quickContent.trim(),
        content_type: quickContentType,
        post_kind: quickPostKind,
      });
      setPosts(prev => [created, ...prev]);
      setQuickContent('');
      setQuickContentType('ooc');
      setQuickPostKind('general');
    } catch (err) {
      setPostError(err instanceof Error ? err.message : 'Failed to create post');
    } finally {
      setPosting(false);
    }
  };

  const focusComposer = () => {
    composerRef.current?.focus();
    composerRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
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

  return (
    <div className="max-w-4xl mx-auto p-8">
      <h1 className="text-3xl font-bold mb-8">Home Feed</h1>

      {/* Quick Post composer for The Commons */}
      {commonsRealm ? (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold mb-3">
            Post in <span className="text-emerald-400">The Commons</span>
          </h3>
          <textarea
            ref={composerRef}
            value={quickContent}
            onChange={(e) => setQuickContent(e.target.value)}
            className="textarea w-full mb-3"
            placeholder="Share an intro, plot idea, or just say hello..."
            rows={3}
          />
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={quickContentType}
              onChange={(e) => setQuickContentType(e.target.value as 'ooc' | 'ic' | 'narration')}
              className="input w-auto text-sm"
            >
              <option value="ooc">OOC</option>
              <option value="ic">IC</option>
              <option value="narration">Narration</option>
            </select>
            <select
              value={quickPostKind}
              onChange={(e) => setQuickPostKind(e.target.value as 'general' | 'open_starter' | 'finished_piece')}
              className="input w-auto text-sm"
            >
              <option value="general">General</option>
              <option value="open_starter">Open Starter</option>
              <option value="finished_piece">Finished Piece</option>
            </select>
            <button
              onClick={handleQuickPost}
              disabled={posting || !quickContent.trim()}
              className="btn btn-primary text-sm ml-auto"
            >
              {posting ? 'Posting...' : 'Post'}
            </button>
          </div>
          {postError && (
            <p className="text-red-400 text-sm mt-2">{postError}</p>
          )}
        </div>
      ) : !loading && (
        <div className="card mb-6">
          <p className="text-red-400 text-sm">
            The Commons realm could not be found. Quick posting is unavailable.
          </p>
        </div>
      )}

      {posts.length === 0 ? (
        <div className="card text-center py-10">
          <h2 className="text-2xl font-bold text-emerald-400 mb-3">Welcome to The Commons</h2>
          <p className="text-gray-300 mb-2 max-w-lg mx-auto">
            The Commons is your shared space for OOC intros, plotting sessions, writing prompts, and getting to know fellow writers.
          </p>
          <p className="text-sm text-gray-500 mb-6 max-w-lg mx-auto">
            No need to join a realm first — just start posting!
          </p>
          <div className="flex flex-wrap justify-center gap-3">
            <button onClick={focusComposer} className="btn btn-primary">
              Post in The Commons
            </button>
            <button onClick={() => navigate('/realms')} className="btn btn-secondary">
              Browse Realms
            </button>
            <button onClick={() => navigate('/characters')} className="btn btn-secondary text-sm opacity-80">
              Create Character
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          {posts.map((post) => {
            const characterName = getCharacterName(post.character_id);
            const realmName = getRealmName(post.realm_id);

            const realm = realms.find(r => r.id === post.realm_id);
            const isCommons = realm?.is_commons;

            return (
              <div key={post.id} className="card">
                {/* Post header with metadata */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {getPostTypeBadge(post.content_type)}
                    {getPostKindBadge(post.post_kind)}
                    <span className="text-sm text-gray-400">
                      {characterName ? (
                        <span className="font-medium text-owl-400">{characterName}</span>
                      ) : post.author_username ? (
                        <Link to={`/u/${encodeURIComponent(post.author_username)}`} className="text-gray-400 hover:text-owl-300 hover:underline transition-colors">@{post.author_username}</Link>
                      ) : null}
                      {(characterName || post.author_username) && ' in '}
                      <span className={isCommons ? 'text-emerald-400 font-semibold' : 'text-owl-300'}>{realmName}</span>
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
  );
}
