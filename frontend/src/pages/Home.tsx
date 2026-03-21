import { useState, useEffect, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Image, X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Post, Realm, Character, LibraryImage } from '@/lib/types';
import CommentSection from '@/components/CommentSection';
import ReactionBar from '@/components/ReactionBar';
import PostMenu from '@/components/PostMenu';
import AttachImageModal from '@/components/AttachImageModal';

const WORKSPACE_PASTE_HINT_KEY = 'ficshon.workspace_paste_hint';

export default function Home() {
  const navigate = useNavigate();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const user = useAuthStore((s) => s.user);
  const postSuccessTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
  const [showPostSuccessNudge, setShowPostSuccessNudge] = useState(false);

  const [showImageModal, setShowImageModal] = useState(false);
  const [attachedImage, setAttachedImage] = useState<LibraryImage | null>(null);

  // Workspace paste hint — read synchronously to avoid flicker
  const [showWorkspacePasteHint, setShowWorkspacePasteHint] = useState(
    () => localStorage.getItem(WORKSPACE_PASTE_HINT_KEY) === 'true'
  );
  const dismissWorkspacePasteHint = () => {
    localStorage.removeItem(WORKSPACE_PASTE_HINT_KEY);
    setShowWorkspacePasteHint(false);
  };

  // Welcome banner — shown only when the user has no characters yet.
  // Dismissed state is session-persistent via localStorage; avoids flashing
  // by reading the flag synchronously in the useState initialiser.
  const BANNER_KEY = 'ficshon.dismissed_welcome_banner';
  const [bannerDismissed, setBannerDismissed] = useState(
    () => localStorage.getItem(BANNER_KEY) === 'true'
  );
  const dismissBanner = () => {
    localStorage.setItem(BANNER_KEY, 'true');
    setBannerDismissed(true);
  };
  // Only true once data has loaded and we know the count is 0.
  // Uses the `characters` array already fetched by loadData().
  const isFirstTimeUser = !loading && characters.length === 0;

  // "Get started" nudge — has a character but no authored posts visible in the feed.
  // Filters the already-fetched `posts` for the current user's id; no extra API call needed.
  // Conservative: only checks the current feed window, which is sufficient for new users.
  const hasNoOwnPosts = !loading && posts.filter(p => p.author_user_id === user?.id).length === 0;
  const showGetStartedCard = !loading && characters.length > 0 && hasNoOwnPosts;

  // Open-starter "Request to Join" state
  const [joinLoading, setJoinLoading] = useState<Record<number, boolean>>({});
  const [joinSent, setJoinSent] = useState<Record<number, boolean>>({});
  const [joinError, setJoinError] = useState<Record<number, string>>({});

  // Clean up the auto-hide timer if the component unmounts mid-countdown.
  useEffect(() => () => { if (postSuccessTimerRef.current) clearTimeout(postSuccessTimerRef.current); }, []);

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
        ...(attachedImage ? { image_url: attachedImage.url } : {}),
      });
      setPosts(prev => [created, ...prev]);
      setQuickContent('');
      setQuickContentType('ooc');
      setQuickPostKind('general');
      setAttachedImage(null);
      // Show the post-success nudge and auto-hide after 10 s.
      if (postSuccessTimerRef.current) clearTimeout(postSuccessTimerRef.current);
      setShowPostSuccessNudge(true);
      postSuccessTimerRef.current = setTimeout(() => setShowPostSuccessNudge(false), 10_000);
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

  const getPostTypeBadge = (contentType: string) => {
    const badges = {
      ic: { label: 'IC', className: 'bg-emerald-600 text-white' },
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

      {/* First-time user banner — hidden once dismissed or once a character exists */}
      {isFirstTimeUser && !bannerDismissed && (
        <div className="flex items-start justify-between gap-4 bg-emerald-600/10 border border-emerald-600/20 rounded-lg px-4 py-4 mb-6">
          <div className="space-y-1">
            <p className="text-sm font-semibold text-emerald-300">Welcome to Ficshon</p>
            <p className="text-sm text-gray-400">
              Create your first character to unlock identity-locked scenes and posting.
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => navigate('/characters/new')}
              className="btn btn-primary text-sm"
            >
              Create character
            </button>
            <button
              onClick={dismissBanner}
              className="text-gray-500 hover:text-gray-300 transition-colors"
              aria-label="Dismiss welcome banner"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {/* "Get started" nudge — has a character but no own posts yet in the feed */}
      {showGetStartedCard && (
        <div className="border border-gray-800 rounded-lg bg-gray-900/50 px-4 py-4 mb-6 space-y-3">
          <div className="space-y-1">
            <p className="text-sm font-semibold text-gray-200">Get started</p>
            <p className="text-sm text-gray-400">
              Introduce your character and start your first story.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={focusComposer} className="btn btn-primary text-sm">
              Write first post
            </button>
            <button
              onClick={() => navigate(`/characters/${characters[0].id}`)}
              className="btn btn-secondary text-sm"
            >
              Go to your character
            </button>
          </div>
        </div>
      )}

      {/* Quick Post composer for The Commons */}
      {commonsRealm ? (
        <div className="card mb-6">
          <h3 className="text-lg font-semibold mb-3">
            Post in <span className="text-emerald-400">The Commons</span>
          </h3>
          {showWorkspacePasteHint && (
            <div className="flex items-center justify-between text-xs text-gray-500 mb-3">
              <span>From Workspace: paste your draft into the composer.</span>
              <button
                type="button"
                onClick={dismissWorkspacePasteHint}
                className="text-gray-400 hover:text-gray-200 transition-colors ml-3 flex-shrink-0"
                aria-label="Dismiss"
              >
                ✕
              </button>
            </div>
          )}
          <textarea
            ref={composerRef}
            value={quickContent}
            onChange={(e) => setQuickContent(e.target.value)}
            onFocus={() => {
              localStorage.removeItem(WORKSPACE_PASTE_HINT_KEY);
              setShowWorkspacePasteHint(false);
            }}
            className="textarea w-full mb-3"
            placeholder="Share an intro, plot idea, or just say hello..."
            rows={3}
          />
          {attachedImage && (
            <div className="flex items-center gap-3 mb-3 p-2 rounded-lg bg-gray-800/50 border border-gray-700">
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
              type="button"
              onClick={() => setShowImageModal(true)}
              className="btn btn-secondary text-sm flex items-center gap-1.5"
            >
              <Image className="w-4 h-4" />
              Attach image
            </button>
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
          {/* Post-success nudge — appears only after a successful Commons post */}
          {showPostSuccessNudge && (
            <div className="flex items-center justify-between gap-3 mt-2">
              <span className="text-xs text-gray-500">Posted to Commons.</span>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  type="button"
                  onClick={() => navigate('/realms')}
                  className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
                >
                  Share in a Realm
                </button>
                <button
                  type="button"
                  onClick={() => { if (postSuccessTimerRef.current) clearTimeout(postSuccessTimerRef.current); setShowPostSuccessNudge(false); }}
                  className="text-gray-600 hover:text-gray-400 transition-colors"
                  aria-label="Dismiss"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            </div>
          )}
          {/* Realms discovery nudge */}
          <div className="mt-3 pt-3 border-t border-gray-800 space-y-2">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs text-gray-500">
                Realms are themed spaces for roleplay — posting there helps the right people find you.
              </p>
              <button
                type="button"
                onClick={() => navigate('/realms')}
                className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors flex-shrink-0"
              >
                Browse Realms →
              </button>
            </div>
            <div className="flex items-center justify-between">
              <p className="text-xs text-gray-500">
                Prefer long-form? Draft in <span className="font-semibold text-gray-400">Workspace</span>.
              </p>
              <button
                type="button"
                onClick={() => navigate('/workspace')}
                className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
              >
                Open Workspace →
              </button>
            </div>
          </div>
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
            const realmName = getRealmName(post.realm_id);
            const realm = realms.find(r => r.id === post.realm_id);
            const isCommons = realm?.is_commons;
            const profileHref = post.author_username ? `/u/${encodeURIComponent(post.author_username)}` : '#';

            return (
              <div key={post.id} className="card">
                {/* Post header: character-first identity */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 flex-wrap min-w-0">
                    {/* Author identity — character takes priority, username is fallback */}
                    {post.character_name ? (
                      <Link to={profileHref} className="flex items-center gap-1.5 group mr-0.5 flex-shrink-0">
                        {post.character_avatar_url ? (
                          <img
                            src={post.character_avatar_url}
                            alt={post.character_name}
                            className="w-7 h-7 rounded-md object-cover border border-gray-700 group-hover:border-emerald-500/50 transition-colors"
                          />
                        ) : (
                          <div className="w-7 h-7 rounded-md bg-emerald-600/20 border border-emerald-500/20 flex items-center justify-center text-[11px] font-semibold text-emerald-400 flex-shrink-0">
                            {post.character_name.charAt(0)}
                          </div>
                        )}
                        <span className="text-sm font-medium text-emerald-400 group-hover:text-emerald-300 transition-colors">
                          {post.character_name}
                        </span>
                      </Link>
                    ) : post.author_username ? (
                      <Link to={profileHref} className="flex items-center gap-1.5 group mr-0.5 flex-shrink-0">
                        <div className="w-7 h-7 rounded-md bg-gray-700 border border-gray-600 flex items-center justify-center text-[11px] font-medium text-gray-400 flex-shrink-0">
                          {post.author_username.charAt(0).toUpperCase()}
                        </div>
                        <span className="text-sm text-gray-400 group-hover:text-emerald-300 transition-colors">
                          @{post.author_username}
                        </span>
                      </Link>
                    ) : null}
                    {getPostTypeBadge(post.content_type)}
                    {getPostKindBadge(post.post_kind)}
                    <span className="text-xs text-gray-500">
                      in <span className={isCommons ? 'text-emerald-400 font-semibold' : 'text-emerald-300'}>{realmName}</span>
                    </span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-xs text-gray-500">
                      {new Date(post.created_at).toLocaleDateString()}
                    </span>
                    {(post.author_user_id === user?.id || user?.is_admin) && (
                      <PostMenu postId={post.id} onDeleted={(id) => setPosts(prev => prev.filter(p => p.id !== id))} />
                    )}
                  </div>
                </div>

                {/* Post content */}
                {post.title && (
                  <h3 className="text-xl font-semibold mb-2">{post.title}</h3>
                )}
                <p className="text-gray-300 whitespace-pre-wrap leading-relaxed mt-1">{post.content}</p>

                {post.image_url && (
                  <img
                    src={post.image_url}
                    alt={post.title || 'Post image'}
                    className="mt-3 rounded-lg max-h-96 object-contain"
                  />
                )}

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

      <AttachImageModal
        open={showImageModal}
        onClose={() => setShowImageModal(false)}
        onSelect={(img) => { setAttachedImage(img); setShowImageModal(false); }}
        selectedId={attachedImage?.id}
      />
    </div>
  );
}
