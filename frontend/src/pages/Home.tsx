import { useState, useEffect, useRef } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ficDebug } from '@/lib/ficDebug';
import { Image, X } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { Post, Realm, Character, LibraryImage, CharacterSearchResult } from '@/lib/types';
import { authorLink } from '@/lib/authorLink';
import CommentSection from '@/components/CommentSection';
import ReactionBar from '@/components/ReactionBar';
import PostMenu from '@/components/PostMenu';
import AttachImageModal from '@/components/AttachImageModal';
import MentionText from '@/components/MentionText';
import HappeningInFicshon from '@/components/HappeningInFicshon';
import { hasActingCharacter } from '@/lib/entitlements';

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
  const [composerCharId, setComposerCharId] = useState<number | null>(null);
  const [posting, setPosting] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const [showPostSuccessNudge, setShowPostSuccessNudge] = useState(false);

  const [showImageModal, setShowImageModal] = useState(false);
  useEffect(() => {
    if (showImageModal) ficDebug.modalOpen('Home:attachImageModal');
    else ficDebug.modalClose('Home:attachImageModal');
  }, [showImageModal]);
  const [attachedImage, setAttachedImage] = useState<LibraryImage | null>(null);

  // Right-panel character discovery — live directory data (existing endpoint).
  // Purely presentational; failures collapse the section silently.
  const [discoverChars, setDiscoverChars] = useState<CharacterSearchResult[]>([]);
  useEffect(() => {
    apiClient.getCharacterDirectory(8)
      .then(setDiscoverChars)
      .catch(() => setDiscoverChars([]));
  }, []);

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

  // Default the posting identity to the ACTIVE character (single-character
  // accounts resolve to their one character automatically). Multi-character
  // founders with no active selection still pick explicitly.
  useEffect(() => {
    if (composerCharId !== null) return;
    const activeId = user?.active_character?.id;
    if (activeId && characters.some((c) => c.id === activeId)) {
      setComposerCharId(activeId);
    } else if (characters.length === 1) {
      setComposerCharId(characters[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characters, user?.active_character?.id]);

  // Dev diagnostics: mount/unmount tracking.
  useEffect(() => {
    ficDebug.mount('Home');
    return () => ficDebug.unmount('Home');
  }, []);

  // Clean up the auto-hide timer if the component unmounts mid-countdown.
  useEffect(() => () => { if (postSuccessTimerRef.current) clearTimeout(postSuccessTimerRef.current); }, []);

  useEffect(() => {
    const loadData = async () => {
      const [feedResult, realmsResult, charsResult] = await Promise.allSettled([
        apiClient.getFeed(),
        apiClient.getRealms(),
        apiClient.getCharacters(),
      ]);

      if (feedResult.status === 'fulfilled') setPosts(feedResult.value);
      else console.error('Failed to load feed:', feedResult.reason);

      if (realmsResult.status === 'fulfilled') setRealms(realmsResult.value);
      else console.error('Failed to load realms:', realmsResult.reason);

      if (charsResult.status === 'fulfilled') setCharacters(charsResult.value);
      else console.error('Failed to load characters:', charsResult.reason);

      setLoading(false);
    };

    loadData();
  }, []);

  const commonsRealm = realms.find(r => r.is_commons);

  const handleQuickPost = async () => {
    if (!commonsRealm || !quickContent.trim()) return;
    // Require an explicit character selection when the user has characters
    if (characters.length > 0 && !composerCharId) {
      setPostError('Select a character to post as.');
      return;
    }
    setPosting(true);
    setPostError(null);
    try {
      const created = await apiClient.createPost(commonsRealm.id, {
        content: quickContent.trim(),
        content_type: quickContentType,
        post_kind: quickPostKind,
        ...(composerCharId ? { character_id: composerCharId } : {}),
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
    if (!user) {
      setJoinError(m => ({ ...m, [postId]: 'You must be logged in.' }));
      return;
    }
    // Identity-first: the request comes from the CHARACTER (never the account
    // username). Wanderers send an identity-less request.
    const joinChar = user.active_character ?? null;
    if (!joinChar && hasActingCharacter(user)) {
      setJoinError(m => ({ ...m, [postId]: 'Choose your active character first (sidebar switcher).' }));
      return;
    }
    setJoinLoading(m => ({ ...m, [postId]: true }));
    setJoinError(m => { const { [postId]: _, ...rest } = m; return rest; });
    try {
      await apiClient.createComment(postId, {
        content: joinChar
          ? `@${joinChar.name} requested to join this starter.`
          : 'A wanderer requested to join this starter.',
        content_type: 'ooc',
        ...(joinChar ? { character_id: joinChar.id } : {}),
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
      ic:        { label: 'IC',        className: 'text-gem bg-gem-soft border-gem/25' },
      ooc:       { label: 'OOC',       className: 'text-ink-3 bg-surface-elevated border-edge' },
      narration: { label: 'NARRATION', className: 'text-amber-400/80 bg-amber-950/20 border-amber-800/40' },
    };
    const badge = badges[contentType as keyof typeof badges] || badges.ic;
    return (
      <span className={`px-1.5 py-0.5 text-[10px] font-mono tracking-[0.06em] uppercase rounded border select-none ${badge.className}`}>
        {badge.label}
      </span>
    );
  };

  const getPostKindBadge = (postKind?: string) => {
    if (!postKind || postKind === 'general') return null;
    const kinds: Record<string, { label: string; className: string }> = {
      open_starter:   { label: 'Open Starter',   className: 'text-teal-400/80 bg-teal-950/20 border-teal-800/40' },
      finished_piece: { label: 'Finished Piece', className: 'text-rose-400/70 bg-rose-950/20 border-rose-800/40' },
    };
    const kind = kinds[postKind];
    if (!kind) return null;
    return (
      <span className={`px-1.5 py-0.5 text-[10px] font-mono tracking-[0.06em] uppercase rounded border select-none ${kind.className}`}>
        {kind.label}
      </span>
    );
  };

  const getSourceTypePill = (sourceType?: string | null) => {
    const pills: Record<string, { label: string; className: string }> = {
      user:          { label: '✍️ User Written', className: 'text-ink-3 bg-surface-elevated border-edge' },
      ai_assisted:   { label: '✨ AI Assisted',  className: 'text-purple-400/80 bg-purple-950/30 border-purple-800/40' },
      ai_generated:  { label: '🤖 AI Generated', className: 'text-blue-400/70 bg-blue-950/20 border-blue-800/40' },
    };
    const pill = pills[sourceType ?? 'user'] ?? pills.user;
    return (
      <span className={`px-1.5 py-0.5 text-[10px] font-medium rounded border select-none ${pill.className}`}>
        {pill.label}
      </span>
    );
  };

  // Quiet select styling shared by the composer controls
  const selectCls =
    'bg-surface-elevated border border-edge rounded-lg px-2.5 py-1.5 text-sm text-ink-2 cursor-pointer focus:outline-none';

  if (loading) {
    return (
      <div className="p-10">
        <p className="text-ink-3">Loading...</p>
      </div>
    );
  }

  const sidePanelRealms = realms.filter(r => !r.is_commons).slice(0, 3);
  const sidePanelDiscover = discoverChars
    .filter(dc => !characters.some(c => c.id === dc.id))
    .slice(0, 4);

  return (
    <div className="mx-auto max-w-6xl px-5 sm:px-8 py-10">
      <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_280px] lg:gap-12">
        {/* ── Main column ─────────────────────────────────────────── */}
        <div className="max-w-[660px] min-w-0">
          <h1 className="font-serif text-4xl font-medium tracking-[-0.02em] text-ink mb-8">
            The Commons
          </h1>

          {/* First-time user banner — hidden once dismissed or once a character exists */}
          {isFirstTimeUser && !bannerDismissed && (
            <div className="flex items-start justify-between gap-4 bg-gem-soft border border-gem/20 rounded-2xl px-5 py-4 mb-6">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-gem">Welcome to Ficshon</p>
                <p className="text-sm text-ink-2">
                  Create your character to start writing, posting, and roleplaying in the world.
                </p>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => navigate('/characters/new')}
                  className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors"
                >
                  Create character
                </button>
                <button
                  onClick={dismissBanner}
                  className="text-ink-3 hover:text-ink-2 transition-colors"
                  aria-label="Dismiss welcome banner"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {/* "Get started" nudge — has a character but no own posts yet in the feed */}
          {showGetStartedCard && (
            <div className="rounded-2xl bg-gem-soft border border-gem/20 px-5 py-4 mb-6 space-y-3">
              <div className="space-y-1">
                <p className="text-sm font-semibold text-gem">Your character is ready — say hello</p>
                <p className="text-sm text-ink-2">
                  Post as <span className="text-ink font-medium">{characters[0]?.name ?? 'your character'}</span> to introduce yourself to the community. This is how people find you.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={focusComposer}
                  className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors"
                >
                  Write first post
                </button>
                <button
                  onClick={() => navigate('/storylab')}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
                >
                  Try StoryLab
                </button>
              </div>
            </div>
          )}

          {/* Quick Post composer for The Commons — posts are authored by
              characters, so the composer only exists once you have one. */}
          {commonsRealm && characters.length === 0 ? (
            <div className="rounded-2xl border border-edge bg-surface mb-8 text-center py-10 px-6">
              <p className="font-serif text-lg text-ink mb-1">Create your character to start posting</p>
              <p className="text-sm text-ink-3 mb-5">On Ficshon, your character is your voice.</p>
              <button
                onClick={() => navigate('/characters/new')}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors"
              >
                Create your character
              </button>
            </div>
          ) : commonsRealm ? (
            <div className="rounded-2xl border border-edge bg-surface mb-8 p-5">
              <h3 className="text-sm font-medium mb-3 text-ink-2">
                <>Writing as <span className="text-gem">{composerCharId ? (characters.find(c => c.id === composerCharId)?.name ?? characters[0].name) : characters[0].name}</span></>
              </h3>
              {showWorkspacePasteHint && (
                <div className="flex items-center justify-between text-xs text-ink-3 mb-3">
                  <span>From Workspace: paste your draft into the composer.</span>
                  <button
                    type="button"
                    onClick={dismissWorkspacePasteHint}
                    className="text-ink-3 hover:text-ink transition-colors ml-3 flex-shrink-0"
                    aria-label="Dismiss"
                  >
                    ✕
                  </button>
                </div>
              )}

              {/* Posting identity */}
              {characters.length > 0 && (
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xs text-ink-3 flex-shrink-0">Posting as</span>
                  {characters.length === 1 ? (
                    // Single character — display-only, clearly visible
                    <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-elevated border border-edge text-sm select-none">
                      {characters[0].avatar_url ? (
                        <img
                          src={characters[0].avatar_url}
                          alt={characters[0].name}
                          className="w-5 h-5 rounded-full object-cover flex-shrink-0"
                        />
                      ) : (
                        <div className="w-5 h-5 rounded-full bg-gem-soft flex items-center justify-center text-[9px] font-semibold text-gem flex-shrink-0">
                          {characters[0].name.charAt(0)}
                        </div>
                      )}
                      <span className="text-gem font-medium">{characters[0].name}</span>
                    </div>
                  ) : (
                    // Multi-character — explicit dropdown, no silent default
                    <select
                      value={composerCharId ?? ''}
                      onChange={(e) => setComposerCharId(e.target.value ? Number(e.target.value) : null)}
                      className={selectCls}
                    >
                      <option value="" disabled>— select character —</option>
                      {characters.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  )}
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
                className="w-full mb-3 bg-transparent border-none resize-none text-[15px] leading-[1.7] text-ink placeholder:text-ink-3 focus:outline-none min-h-[80px]"
                placeholder="Share an intro, plot idea, or just say hello..."
                rows={3}
              />
              {attachedImage && (
                <div className="flex items-center gap-3 mb-3 p-2 rounded-lg bg-surface-elevated border border-edge">
                  <img
                    src={attachedImage.url}
                    alt={attachedImage.prompt_summary || 'Attached image'}
                    className="w-12 h-16 rounded object-cover"
                  />
                  <span className="text-xs text-ink-2 flex-1 truncate">
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
              <div className="flex flex-wrap items-center gap-2.5 pt-3 border-t border-edge">
                <select
                  value={quickContentType}
                  onChange={(e) => setQuickContentType(e.target.value as 'ooc' | 'ic' | 'narration')}
                  className={selectCls}
                >
                  <option value="ooc">OOC</option>
                  <option value="ic">IC</option>
                  <option value="narration">Narration</option>
                </select>
                <select
                  value={quickPostKind}
                  onChange={(e) => setQuickPostKind(e.target.value as 'general' | 'open_starter' | 'finished_piece')}
                  className={selectCls}
                >
                  <option value="general">General</option>
                  <option value="open_starter">Open Starter</option>
                  <option value="finished_piece">Finished Piece</option>
                </select>
                <button
                  type="button"
                  onClick={() => setShowImageModal(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-ink-2 bg-surface-elevated hover:text-ink transition-colors"
                >
                  <Image className="w-4 h-4" />
                  Attach image
                </button>
                <button
                  onClick={handleQuickPost}
                  disabled={posting || !quickContent.trim()}
                  className="ml-auto px-5 py-1.5 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors disabled:opacity-40"
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
                  <span className="text-xs text-ink-3">Posted to Commons.</span>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => navigate('/realms')}
                      className="text-xs text-gem hover:opacity-80 transition-opacity"
                    >
                      Share in a Realm
                    </button>
                    <button
                      type="button"
                      onClick={() => { if (postSuccessTimerRef.current) clearTimeout(postSuccessTimerRef.current); setShowPostSuccessNudge(false); }}
                      className="text-ink-3 hover:text-ink-2 transition-colors"
                      aria-label="Dismiss"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              )}
              {/* Realms discovery nudge */}
              <div className="mt-3 pt-3 border-t border-edge space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-xs text-ink-3">
                    Realms are themed spaces for roleplay — posting there helps the right people find you.
                  </p>
                  <button
                    type="button"
                    onClick={() => navigate('/realms')}
                    className="text-xs text-gem hover:opacity-80 transition-opacity flex-shrink-0"
                  >
                    Browse Realms →
                  </button>
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-xs text-ink-3">
                    Prefer long-form? Draft in <span className="font-semibold text-ink-2">Workspace</span>.
                  </p>
                  <button
                    type="button"
                    onClick={() => navigate('/workspace')}
                    className="text-xs text-gem hover:opacity-80 transition-opacity"
                  >
                    Open Workspace →
                  </button>
                </div>
              </div>
            </div>
          ) : !loading && (
            <div className="rounded-2xl border border-edge bg-surface mb-8 p-5">
              <p className="text-red-400 text-sm">
                The Commons realm could not be found. Quick posting is unavailable.
              </p>
            </div>
          )}

          {posts.length === 0 ? (
            <div className="text-center py-14">
              <h2 className="font-serif text-3xl font-medium text-ink mb-3">Welcome to The Commons</h2>
              <p className="text-ink-2 mb-2 max-w-lg mx-auto">
                The Commons is your shared space for OOC intros, plotting sessions, writing prompts, and getting to know fellow writers.
              </p>
              <p className="text-sm text-ink-3 mb-6 max-w-lg mx-auto">
                No need to join a realm first — just start posting.
              </p>
              <div className="flex flex-wrap justify-center gap-3">
                <button
                  onClick={focusComposer}
                  className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors"
                >
                  {characters.length > 0
                    ? `Post as ${characters[0].name}`
                    : 'Post in The Commons'}
                </button>
                {characters.length === 0 && (
                  <button
                    onClick={() => navigate('/characters/new')}
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
                  >
                    Create Character
                  </button>
                )}
                <button
                  onClick={() => navigate('/realms')}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
                >
                  Browse Realms
                </button>
              </div>
            </div>
          ) : (
            <div>
              {posts.map((post) => {
                const realmName = getRealmName(post.realm_id);
                const realm = realms.find(r => r.id === post.realm_id);
                const isCommons = realm?.is_commons;
                // Identity-first: character posts link to the character profile;
                // anything else renders as an unlinked Wanderer.
                const author = authorLink(post);
                const headerHref = author.href ?? '#';

                return (
                  <article key={post.id} className="py-7 border-b border-edge group">
                    {/* Post header: two-level identity — character row + attribution row */}
                    <div className="flex items-start justify-between mb-4 gap-2">
                      <div className="flex items-start gap-3 min-w-0 flex-1">
                        {/* Avatar — circular, identity-first */}
                        {post.character_name ? (
                          <Link to={headerHref} className="flex-shrink-0 mt-0.5">
                            {post.character_avatar_url ? (
                              <img
                                src={post.character_avatar_url}
                                alt={post.character_name}
                                className="w-9 h-9 rounded-full object-cover border border-edge-md group-hover:border-gem/40 transition-colors"
                              />
                            ) : (
                              <div className="w-9 h-9 rounded-full bg-gem-soft border border-gem/20 flex items-center justify-center text-sm font-semibold text-gem flex-shrink-0">
                                {post.character_name.charAt(0)}
                              </div>
                            )}
                          </Link>
                        ) : (
                          <div className="flex-shrink-0 mt-0.5">
                            <div className="w-9 h-9 rounded-full bg-surface-elevated border border-edge flex items-center justify-center text-sm font-medium text-ink-3">
                              ✦
                            </div>
                          </div>
                        )}

                        {/* Identity text: name + badges on first line, attribution on second */}
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            {post.character_name ? (
                              <Link to={headerHref} className="text-sm font-semibold text-ink hover:text-gem transition-colors leading-tight">
                                {post.character_name}
                              </Link>
                            ) : (
                              <span className="text-sm font-medium text-ink-2">{author.label}</span>
                            )}
                            {getPostTypeBadge(post.content_type)}
                            {getPostKindBadge(post.post_kind)}
                            {getSourceTypePill(post.source_type)}
                          </div>
                          <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                            <span className="text-[11px] font-mono text-ink-3">
                              in <span className={isCommons ? 'text-ink-3' : 'text-gem/80'}>{realmName}</span>
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-1.5 flex-shrink-0 mt-0.5">
                        <span className="text-[11px] font-mono text-ink-3">
                          {new Date(post.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                        </span>
                        {(post.author_user_id === user?.id || user?.is_admin) && (
                          <PostMenu postId={post.id} onDeleted={(id) => setPosts(prev => prev.filter(p => p.id !== id))} />
                        )}
                      </div>
                    </div>

                    {/* Post content — in-world writing reads as literature */}
                    {post.title && (
                      <h3 className="font-serif text-[21px] font-medium leading-[1.35] mb-2 text-ink">{post.title}</h3>
                    )}
                    <p
                      className={`whitespace-pre-wrap ${
                        post.content_type === 'ooc'
                          ? 'text-[15px] leading-[1.7] text-ink-2'
                          : 'font-serif text-[17px] leading-[1.75] text-ink'
                      }`}
                    >
                      <MentionText text={post.content} mentions={post.mentions} />
                    </p>

                    {post.image_url && (
                      <img
                        src={post.image_url}
                        alt={post.title || 'Post image'}
                        className="mt-4 rounded-xl border border-edge max-h-[32rem] object-contain"
                        loading="lazy"
                        decoding="async"
                      />
                    )}

                    {post.post_kind === 'open_starter' && (
                      <div className="mt-4 px-4 py-3 bg-gem-soft rounded-xl flex items-center justify-between gap-3 flex-wrap">
                        <p className="text-xs text-ink-2">
                          Open to collaboration — comment OOC or request to continue in a Scene.
                        </p>
                        <button
                          onClick={() => requestToJoin(post.id)}
                          disabled={joinLoading[post.id] || joinSent[post.id]}
                          className={`text-xs px-3 py-1.5 rounded-lg border transition-colors flex-shrink-0 ${
                            joinSent[post.id]
                              ? 'border-gem/25 text-gem/70 cursor-default'
                              : joinLoading[post.id]
                                ? 'border-edge text-ink-3 cursor-wait'
                                : 'border-gem/30 text-gem hover:bg-gem/10'
                          }`}
                        >
                          {joinLoading[post.id] ? 'Sending…' : joinSent[post.id] ? 'Request sent' : 'Request to join'}
                        </button>
                        {joinError[post.id] && (
                          <p className="text-red-400 text-xs w-full mt-0.5">{joinError[post.id]}</p>
                        )}
                      </div>
                    )}

                    <ReactionBar postId={post.id} />
                    <CommentSection postId={post.id} characters={characters} defaultExpanded={joinSent[post.id]} />
                  </article>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Right panel — live data only ─────────────────────────── */}
        <aside className="hidden lg:block lg:sticky lg:top-10 self-start space-y-9 pt-2">
          {/* Public, character-first activity — replaces the old account-centric
              "Your Characters" list. Shown to every audience so the Commons stays
              focused on the fictional world, not account management. Collapses
              quietly if the feed is empty or failed to load. */}
          <HappeningInFicshon posts={posts} realms={realms} loading={loading} />

          {sidePanelRealms.length > 0 && (
            <section>
              <h3 className="text-[11px] font-mono uppercase tracking-[0.1em] text-ink-3 mb-4">
                Realms
              </h3>
              <div className="space-y-3">
                {sidePanelRealms.map((realm) => (
                  <Link
                    key={realm.id}
                    to={`/realms/${realm.id}`}
                    className="block rounded-xl overflow-hidden border border-edge hover:border-edge-md transition-colors"
                  >
                    <div className="h-[72px] relative overflow-hidden bg-gem-soft">
                      {realm.banner_url && (
                        <img src={realm.banner_url} alt={realm.name} className="w-full h-full object-cover" />
                      )}
                      <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent" />
                    </div>
                    <div className="px-3 py-2.5 bg-surface">
                      <div className="text-[13px] font-semibold text-ink leading-tight truncate">{realm.name}</div>
                      {(realm.genre || realm.tagline) && (
                        <div className="text-[11px] text-ink-3 mt-0.5 truncate">{realm.genre || realm.tagline}</div>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
              <Link
                to="/realms"
                className="mt-3 block w-full text-center border border-edge rounded-xl py-2 text-xs font-medium text-ink-2 hover:text-ink hover:border-edge-md transition-colors"
              >
                Browse all Realms
              </Link>
            </section>
          )}

          {sidePanelDiscover.length > 0 && (
            <section>
              <h3 className="text-[11px] font-mono uppercase tracking-[0.1em] text-ink-3 mb-4">
                Characters to Discover
              </h3>
              <div className="space-y-1">
                {sidePanelDiscover.map((dc) => (
                  <Link
                    key={dc.id}
                    to={`/characters/${dc.id}`}
                    className="flex items-center gap-2.5 px-2 py-1.5 -mx-2 rounded-xl hover:bg-surface-elevated transition-colors"
                  >
                    {dc.avatar_url ? (
                      <img
                        src={dc.avatar_url}
                        alt={dc.name}
                        className="w-9 h-9 rounded-full object-cover border border-edge-md flex-shrink-0"
                      />
                    ) : (
                      <div className="w-9 h-9 rounded-full bg-surface-elevated flex items-center justify-center text-sm font-semibold text-ink-3 flex-shrink-0">
                        {dc.name.charAt(0)}
                      </div>
                    )}
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium text-ink leading-tight truncate">{dc.name}</div>
                      {(dc.species || dc.short_bio) && (
                        <div className="text-[11px] text-ink-3 leading-tight truncate">{dc.species || dc.short_bio}</div>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            </section>
          )}
        </aside>
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
