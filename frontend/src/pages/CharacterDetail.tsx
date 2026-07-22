import { useState, useEffect, useRef } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import {
  Feather,
  RefreshCw,
  MessageSquare,
  UserPlus,
  Trash2,
  X,
  Check,
  Sparkles,
  Image as ImageIcon,
  Camera,
  BookOpen,
  MessageCircle,
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character, ProfileTimelineItem, User } from '@/lib/types';
import CanonManager from '@/components/CanonManager';
import MentionText from '@/components/MentionText';
import { listCharacterImages, resolveImageUrl, setCharacterAvatar } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import ImageGrid from '@/features/images/components/ImageGrid';
import IdentityCanonSection from '@/features/characterCreation/components/IdentityCanonSection';
import PostComposer from '@/features/posts/components/PostComposer';
import ErrorBoundary from '@/components/ErrorBoundary';

type Tab = 'timeline' | 'stories' | 'media' | 'mentions' | 'manage';

/** The public character profile — the character IS the public identity.
 *  Nothing on this page may expose the owning account. Owner tooling lives
 *  behind the owner-only Manage tab. */
export default function CharacterDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [character, setCharacter] = useState<Character | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const justCreated = searchParams.get('created') === '1';

  const [activeTab, setActiveTab] = useState<Tab>('timeline');

  // Follow is a placeholder in this phase — no backend, no fake state.
  const [followHint, setFollowHint] = useState('');

  // Manage Character Canon modal — hosts the CanonManager (single source of identity truth)
  const [showCanonModal, setShowCanonModal] = useState(false);

  const [galleryImages, setGalleryImages] = useState<CharacterImageRead[]>([]);
  const [timeline, setTimeline] = useState<ProfileTimelineItem[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(true);
  const [mentions, setMentions] = useState<ProfileTimelineItem[]>([]);
  const [mentionsLoaded, setMentionsLoaded] = useState(false);
  const [mentionsLoading, setMentionsLoading] = useState(false);
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  const [lbVisible, setLbVisible] = useState(false);

  // Set-avatar state
  const [settingAvatar, setSettingAvatar] = useState(false);
  const [avatarSet, setAvatarSet] = useState(false);

  // Mounted guard — prevents stale setState calls after navigation away
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Post composer state
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerImage, setComposerImage] = useState<CharacterImageRead | null>(null);

  // Cover toast state
  const [coverToast, setCoverToast] = useState('');

  // Delete modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleteStep, setDeleteStep] = useState<1 | 2>(1);
  const [deleteConfirmed, setDeleteConfirmed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const handleDeleteCharacter = async () => {
    if (!id) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await apiClient.deleteCharacter(Number(id));
      navigate('/characters');
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete character.');
      setDeleting(false);
    }
  };

  const openDeleteModal = () => {
    setShowDeleteModal(true);
    setDeleteStep(1);
    setDeleteConfirmed(false);
    setDeleteError('');
  };

  const closeDeleteModal = () => {
    setShowDeleteModal(false);
    setDeleteStep(1);
    setDeleteConfirmed(false);
    setDeleteError('');
  };

  const handleSetAvatar = async (img: CharacterImageRead) => {
    if (!character) return;
    setSettingAvatar(true);
    setAvatarSet(false);
    try {
      await setCharacterAvatar(character.id, img.id);
      if (!mountedRef.current) return;
      setCharacter({ ...character, avatar_url: resolveImageUrl(img.url) });
      setAvatarSet(true);
      const t = setTimeout(() => { if (mountedRef.current) setAvatarSet(false); }, 2000);
      // Store timer so it can be GC'd; no explicit cancel needed since the guard is inside
      void t;
    } catch {
      // Silently fail — user can retry
    } finally {
      if (mountedRef.current) setSettingAvatar(false);
    }
  };

  const handleUseInPost = (image: CharacterImageRead) => {
    setComposerImage(image);
    setComposerOpen(true);
  };

  const handleSetAsCover = async (image: CharacterImageRead) => {
    if (!character) return;
    try {
      const result = await apiClient.setCharacterCover(character.id, 'character', image.id);
      if (!mountedRef.current) return;
      setCharacter({ ...character, cover_url: result.cover_url });
      setCoverToast('Cover image updated');
      setTimeout(() => { if (mountedRef.current) setCoverToast(''); }, 3000);
    } catch {
      if (!mountedRef.current) return;
      setCoverToast('Could not set cover. Try again.');
      setTimeout(() => { if (mountedRef.current) setCoverToast(''); }, 3000);
    }
  };

  // Drives enter (opacity-0→1, scale-95→100) and exit transitions for the gallery lightbox.
  // Safety: uses mountedRef so the delayed clear never fires on an unmounted component.
  useEffect(() => {
    if (lightboxIdx === null) { setLbVisible(false); return; }
    const id = requestAnimationFrame(() => { if (mountedRef.current) setLbVisible(true); });
    return () => cancelAnimationFrame(id);
  }, [lightboxIdx]); // eslint-disable-line react-hooks/exhaustive-deps

  const closeLightbox = () => {
    setLbVisible(false);
    setTimeout(() => { if (mountedRef.current) setLightboxIdx(null); }, 200);
  };

  useEffect(() => {
    if (!id) return;
    const charId = Number(id);
    Promise.all([
      apiClient.getCharacter(charId),
      apiClient.getMe().catch(() => null),
    ])
      .then(([char, user]) => {
        setCharacter(char);
        setCurrentUser(user);
        // Fetch gallery images (non-blocking — don't gate the page on this)
        listCharacterImages(charId)
          .then(setGalleryImages)
          .catch(() => {});
        // Character-only timeline (the public profile feed)
        apiClient.getCharacterPosts(charId)
          .then(setTimeline)
          .catch(() => setTimeline([]))
          .finally(() => setTimelineLoading(false));
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Character not found'))
      .finally(() => setLoading(false));
  }, [id]);

  // Lazy-load mentions when the tab is first opened
  useEffect(() => {
    if (activeTab !== 'mentions' || !id || mentionsLoaded) return;
    setMentionsLoading(true);
    apiClient.getCharacterMentions(Number(id))
      .then((items) => { if (mountedRef.current) setMentions(items); })
      .catch(() => { if (mountedRef.current) setMentions([]); })
      .finally(() => {
        if (mountedRef.current) {
          setMentionsLoaded(true);
          setMentionsLoading(false);
        }
      });
  }, [activeTab, id, mentionsLoaded]);

  const dismissBanner = () => {
    searchParams.delete('created');
    setSearchParams(searchParams, { replace: true });
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center text-ink-3">
        Loading…
      </div>
    );
  }

  if (error || !character) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 bg-app">
        <p className="text-ink-2">{error || 'Character not found.'}</p>
        <button
          className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
          onClick={() => navigate('/characters')}
        >
          Back to Characters
        </button>
      </div>
    );
  }

  const isOwner = !!(currentUser && character.owner_id === currentUser.id);

  const coverPosX = character.cover_position_x ?? 0.5;
  const coverPosY = character.cover_position_y ?? 0.5;
  const avatarScale = character.avatar_scale ?? 1.0;
  const avatarPosX = character.avatar_position_x ?? 0.5;
  const avatarPosY = character.avatar_position_y ?? 0.5;

  const metaLine = [character.role, character.era].filter(Boolean).join(' · ');

  const tabs: { id: Tab; label: string }[] = [
    { id: 'timeline', label: 'Timeline' },
    { id: 'stories', label: 'Stories' },
    { id: 'media', label: 'Media' },
    { id: 'mentions', label: 'Mentions' },
    ...(isOwner ? [{ id: 'manage' as Tab, label: 'Manage' }] : []),
  ];

  return (
    <div className="min-h-screen bg-app">
      {/* Arrival banner — floats above the establishing shot */}
      {justCreated && (
        <div className="max-w-[1000px] mx-auto px-4 sm:px-8">
          <div className="bg-gem-soft border border-gem/20 rounded-2xl px-5 py-4 my-4 space-y-3">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <Feather className="w-4 h-4 text-gem flex-shrink-0 mt-0.5" />
                <div>
                  <p className="text-sm font-semibold text-gem">
                    {character.name} is live on Ficshon.
                  </p>
                  <p className="text-xs text-ink-2 mt-0.5">
                    Write your first post to introduce them to the community.
                  </p>
                </div>
              </div>
              <button
                onClick={dismissBanner}
                className="text-ink-3 hover:text-ink-2 transition-colors flex-shrink-0 mt-0.5"
                aria-label="Dismiss"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => navigate('/')}
                className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors"
              >
                Post to The Commons
              </button>
              <button
                onClick={() => navigate('/storylab')}
                className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
              >
                Open StoryLab
              </button>
            </div>
          </div>
        </div>
      )}

      {/* === HERO — the cover backs the entire character introduction:
           establishing shot → name → avatar & stats → tabs. The gradient
           completes the fade into the page background at the hero's lower
           boundary, so the timeline begins on solid ground below the fold. === */}
      <section className="relative isolate">
        {/* Cover backdrop — spans the full hero */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          {character.cover_url ? (
            <img
              src={character.cover_url}
              alt={`${character.name}'s cover`}
              className="absolute inset-0 w-full h-full object-cover"
              style={{ objectPosition: `${coverPosX * 100}% ${coverPosY * 100}%` }}
              draggable={false}
            />
          ) : (
            /* Designed fallback — quiet gem atmosphere, no borrowed imagery */
            <div
              className="absolute inset-0"
              style={{
                background:
                  'radial-gradient(ellipse 70% 90% at 20% 0%, rgb(var(--gem) / 0.16) 0%, transparent 60%), radial-gradient(ellipse 60% 80% at 90% 100%, rgb(var(--gem) / 0.08) 0%, transparent 55%), var(--surface)',
              }}
            >
              <Feather className="absolute top-[24%] right-8 w-16 h-16 text-ink-3/25" />
            </div>
          )}
          {/* Cinematic fade into the page background */}
          <div className="cover-gradient absolute inset-0" />
        </div>

        <div className="relative max-w-[1000px] mx-auto px-4 sm:px-8">
          {/* Establishing space — pure cover, no content competes with the image */}
          <div className="h-[32vh] min-h-[190px] sm:h-[46vh] sm:min-h-[360px] lg:h-[52vh] max-h-[640px]" />

          {/* Title — the character's name IS the headline */}
          {metaLine && (
            <span className="hero-text-glow block font-mono text-[11px] uppercase tracking-[0.14em] text-ink-2 mb-2">
              {metaLine}
            </span>
          )}
          <h1
            className="hero-text-glow font-serif font-semibold text-ink leading-[0.98] tracking-[-0.02em] break-words"
            style={{ fontSize: 'clamp(36px, 6.5vw, 72px)' }}
          >
            {character.name}
          </h1>

          {/* Identity band — avatar anchored lower-left, stats & actions beside it */}
          <div className="flex items-end gap-4 sm:gap-6 mt-6 sm:mt-9">
            <div className="relative flex-shrink-0">
              <div className="w-24 h-24 sm:w-28 sm:h-28 md:w-32 md:h-32 rounded-2xl overflow-hidden border-[3px] border-app shadow-[0_0_0_1px_var(--border-md),0_8px_28px_rgba(0,0,0,0.4)] bg-surface-elevated">
                {character.avatar_url ? (
                  <img
                    src={character.avatar_url}
                    alt={character.name}
                    className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                    style={avatarScale > 1.001 ? {
                      transformOrigin: 'center center',
                      transform: `scale(${avatarScale}) translate(${(0.5 - avatarPosX) * (avatarScale - 1) / avatarScale * 100}%, ${(0.5 - avatarPosY) * (avatarScale - 1) / avatarScale * 100}%)`,
                    } : undefined}
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center font-serif text-3xl font-semibold text-gem bg-gem-soft">
                    {character.name.charAt(0).toUpperCase()}
                  </div>
                )}
              </div>
            </div>

            {/* Stats + action buttons */}
            <div className="flex-1 min-w-0 pb-1 sm:pb-2">
              <div className="flex items-end justify-between gap-3 flex-wrap">
                <div className="flex flex-wrap items-center gap-5 sm:gap-8 min-w-0">
                  <span className="text-center">
                    <span className="block font-serif text-xl sm:text-2xl font-medium text-ink leading-tight">{timeline.length}</span>
                    <span className="block font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3">Posts</span>
                  </span>
                  <span className="text-center" title="Follower counts are coming soon">
                    <span className="block font-serif text-xl sm:text-2xl font-medium text-ink-3 leading-tight">—</span>
                    <span className="block font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3">Followers</span>
                  </span>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  {!isOwner && (
                    <>
                      {/* Messaging is character-to-character — only viewers who
                          own a character can open a conversation. */}
                      {(currentUser?.character_count ?? 0) > 0 && (
                        <button
                          className="bg-surface-elevated border border-edge text-ink-2 hover:text-ink hover:border-edge-md px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium transition-all"
                          onClick={() => navigate(`/messages/new?characterId=${id}`)}
                        >
                          <MessageSquare className="w-4 h-4 flex-shrink-0" />
                          Message
                        </button>
                      )}
                      <button
                        className="bg-gem hover:bg-gem/90 text-gem-ink px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-semibold transition-all"
                        onClick={() => setFollowHint('Following is coming soon.')}
                      >
                        <UserPlus className="w-4 h-4 flex-shrink-0" />
                        Follow
                      </button>
                    </>
                  )}
                  {isOwner && (
                    <button
                      onClick={() => setActiveTab('manage')}
                      className="bg-surface-elevated border border-edge hover:border-edge-md text-ink-2 hover:text-ink px-4 py-2 rounded-lg flex items-center gap-2 text-sm transition-all"
                    >
                      <Sparkles className="w-4 h-4" />
                      Manage
                    </button>
                  )}
                </div>
              </div>
              {followHint && (
                <p className="text-xs text-ink-3 mt-2">{followHint}</p>
              )}
            </div>
          </div>

          {/* Tabs — the hero's lower boundary */}
          <div className="flex items-center gap-1 mt-6 sm:mt-8 border-b border-edge overflow-x-auto hide-scrollbar">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 sm:px-4 py-2.5 -mb-px text-xs sm:text-sm font-medium whitespace-nowrap border-b-2 transition-colors duration-200 ${
                  activeTab === tab.id
                    ? 'border-gem text-ink'
                    : 'border-transparent text-ink-3 hover:text-ink-2'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* === CONTENT === */}
      <div className="max-w-[1000px] mx-auto px-4 sm:px-8 py-8 pb-16">

        {/* Bio — the character's own introduction, shown above every public tab */}
        {activeTab !== 'manage' && (character.short_bio || character.long_bio || character.tags) && (
          <div className="mb-10 max-w-3xl space-y-5">
            {character.short_bio && (
              <p className="font-serif text-lg sm:text-xl leading-[1.6] text-ink">{character.short_bio}</p>
            )}
            {character.long_bio && (
              <p className="text-[15px] leading-[1.75] text-ink-2 whitespace-pre-wrap">{character.long_bio}</p>
            )}
            {character.tags && (
              <div className="flex flex-wrap gap-2">
                {character.tags.split(',').map((tag, i) => (
                  <span key={i} className="px-2.5 py-1 bg-surface-elevated text-ink-2 font-mono text-[11px] rounded-full">
                    {tag.trim()}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Timeline */}
        {activeTab === 'timeline' && (
          <div className="max-w-3xl">
            {timelineLoading ? (
              <p className="text-sm text-ink-3">Loading posts…</p>
            ) : timeline.length === 0 ? (
              <div className="py-16 text-center">
                <Feather className="w-10 h-10 text-ink-3/50 mx-auto mb-4" />
                <h3 className="font-serif text-xl text-ink mb-1">No Posts Yet</h3>
                <p className="text-ink-3 text-sm">{character.name} hasn't posted yet.</p>
              </div>
            ) : (
              timeline.map((item, idx) => (
                <PostCard key={idx} item={item} character={character} />
              ))
            )}
          </div>
        )}

        {/* Stories — placeholder until character-scoped stories ship */}
        {activeTab === 'stories' && (
          <div className="py-16 text-center max-w-3xl">
            <BookOpen className="w-10 h-10 text-ink-3/50 mx-auto mb-4" />
            <h3 className="font-serif text-xl text-ink mb-1">No Stories Yet</h3>
            <p className="text-ink-3 text-sm">
              Stories featuring {character.name} will appear here.
            </p>
          </div>
        )}

        {/* Media */}
        {activeTab === 'media' && (
          galleryImages.length === 0 ? (
            <div className="py-16 text-center max-w-3xl">
              <Camera className="w-10 h-10 text-ink-3/50 mx-auto mb-4" />
              <h3 className="font-serif text-xl text-ink mb-1">No Media Yet</h3>
              <p className="text-ink-3 text-sm">
                Images of {character.name} will appear here.
              </p>
            </div>
          ) : (
            <ErrorBoundary>
              <ImageGrid
                images={galleryImages}
                onImageClick={(idx) => setLightboxIdx(idx)}
                onUseInPost={isOwner ? handleUseInPost : undefined}
                onSetAsCover={isOwner ? handleSetAsCover : undefined}
              />
            </ErrorBoundary>
          )
        )}

        {/* Mentions */}
        {activeTab === 'mentions' && (
          <div className="max-w-3xl">
            {mentionsLoading && (
              <div className="flex justify-center py-12">
                <div className="w-8 h-8 border-4 border-gem/25 border-t-gem rounded-full animate-spin" />
              </div>
            )}
            {!mentionsLoading && mentions.length === 0 && (
              <div className="py-16 text-center">
                <MessageCircle className="w-10 h-10 text-ink-3/50 mx-auto mb-4" />
                <h3 className="font-serif text-xl text-ink mb-1">No Mentions Yet</h3>
                <p className="text-ink-3 text-sm">
                  Posts that mention {character.name} will appear here.
                </p>
              </div>
            )}
            {!mentionsLoading && mentions.map((item, idx) => (
              <PostCard key={idx} item={item} character={null} />
            ))}
          </div>
        )}

        {/* Manage — owner only. The character's backstage. */}
        {activeTab === 'manage' && isOwner && (
          <div className="space-y-6 max-w-3xl">
            <div className="rounded-2xl p-5 bg-surface border border-edge space-y-3">
              <h3 className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3">Character Tools</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => navigate(`/images?characterId=${character.id}`)}
                  className="text-sm flex items-center gap-2 px-3.5 py-2 rounded-lg bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
                >
                  <ImageIcon className="w-3.5 h-3.5" />
                  Generate Images
                </button>
                {character.visual_locked && (
                  <button
                    onClick={() => setShowCanonModal(true)}
                    className="text-sm flex items-center gap-2 px-3.5 py-2 rounded-lg bg-surface-elevated text-ink-2 hover:text-ink transition-colors"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Manage Character Canon
                  </button>
                )}
              </div>
              <p className="text-xs text-ink-3">
                Set the avatar from any gallery image (open it from the Media tab), and set a
                cover with the “Set as cover” action on a gallery image.
              </p>
            </div>

            {/* Identity Canon — v2 canon pack cards (stored in canon JSON, not the
                CharacterImage library), shown separately from scene/library images. */}
            <ErrorBoundary>
              <IdentityCanonSection characterId={character.id} />
            </ErrorBoundary>

            <div className="rounded-2xl p-5 bg-red-950/20 border border-red-900/30 space-y-2">
              <h3 className="text-sm font-semibold text-red-400">Danger Zone</h3>
              <button
                className="text-xs text-red-500 hover:text-red-400 transition-colors flex items-center gap-1"
                onClick={openDeleteModal}
              >
                <Trash2 className="w-3 h-3" />
                Reset Character Identity
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Post composer */}
      <PostComposer
        open={composerOpen}
        onClose={() => { setComposerOpen(false); setComposerImage(null); }}
        preloadedImage={composerImage}
      />

      {/* Cover toast */}
      {coverToast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg bg-surface-overlay border border-edge-md text-sm text-ink shadow-lg pointer-events-none">
          {coverToast}
        </div>
      )}

      {/* Image lightbox */}
      <ErrorBoundary>
      {lightboxIdx !== null && galleryImages[lightboxIdx] && (
        <div
          className={`fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm transition-opacity duration-200 ${lbVisible ? 'opacity-100' : 'opacity-0'}`}
          onClick={closeLightbox}
        >
          <div
            className={`relative max-w-md w-full mx-4 transition-all duration-200 ease-out ${lbVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'}`}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 z-10"
              onClick={closeLightbox}
            >
              <X className="w-4 h-4" />
            </button>
            <img
              src={resolveImageUrl(galleryImages[lightboxIdx].url)}
              alt={galleryImages[lightboxIdx].kind?.replace(/_/g, ' ') ?? ''}
              className="w-full rounded-xl"
            />
            <div className="flex items-center justify-between mt-2">
              <p className="font-mono text-xs text-white/60 capitalize">
                {galleryImages[lightboxIdx].kind?.replace(/_/g, ' ')}
              </p>
              {isOwner && (
                <button
                  className="text-xs px-3 py-1.5 rounded-lg bg-gem hover:bg-gem/90 text-gem-ink font-semibold transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  disabled={settingAvatar}
                  onClick={() => handleSetAvatar(galleryImages[lightboxIdx!])}
                >
                  {avatarSet ? (
                    <><Check className="w-3 h-3" />Avatar set</>
                  ) : settingAvatar ? (
                    <><RefreshCw className="w-3 h-3 animate-spin" />Saving…</>
                  ) : (
                    'Set as avatar'
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
      </ErrorBoundary>

      {/* Manage Character Canon modal — single source of identity truth (CanonManager) */}
      {showCanonModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-surface-overlay border border-edge-md rounded-2xl w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh]">

            {/* Header */}
            <div className="flex items-center justify-between gap-3 px-6 pt-6 pb-4 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-gem-soft border border-gem/25 flex items-center justify-center flex-shrink-0">
                  <Sparkles className="w-4 h-4 text-gem" />
                </div>
                <h2 className="text-sm font-semibold text-ink">Manage Character Canon</h2>
              </div>
              <button
                onClick={() => setShowCanonModal(false)}
                className="text-ink-3 hover:text-ink-2 transition-colors p-1 flex-shrink-0"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body — scrollable */}
            <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-4 min-h-0">
              <CanonManager
                characterId={character.id}
                isOwner={isOwner}
                isAdmin={!!currentUser?.is_admin}
                characterName={character.name}
              />
            </div>
          </div>
        </div>
      )}

      {/* Delete character modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-surface-overlay border border-edge-md rounded-2xl p-6 max-w-md w-full mx-4 space-y-4">
            {deleteStep === 1 ? (
              <>
                <h3 className="text-lg font-semibold text-red-400">Reset Character Identity</h3>
                <div className="text-sm text-ink-2 space-y-2">
                  <p>This will <strong>permanently delete</strong> your character <strong>{character.name}</strong> and all associated data:</p>
                  <ul className="list-disc list-inside text-ink-3 space-y-1">
                    <li>Character profile, bio, and DNA</li>
                    <li>All generated images</li>
                    <li>All conversations and messages as this character</li>
                    <li>Character references on posts will be cleared</li>
                  </ul>
                  <p className="text-amber-400">After deletion, you must wait <strong>24 hours</strong> before creating a new character.</p>
                </div>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={deleteConfirmed}
                    onChange={(e) => setDeleteConfirmed(e.target.checked)}
                    className="mt-1 accent-red-500"
                  />
                  <span className="text-sm text-ink-2">I understand this action is permanent and cannot be undone.</span>
                </label>
                <div className="flex gap-3 pt-2">
                  <button
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors flex-1"
                    onClick={closeDeleteModal}
                  >
                    Cancel
                  </button>
                  <button
                    className="bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm px-4 py-2 rounded-lg transition-colors flex-1"
                    disabled={!deleteConfirmed}
                    onClick={() => setDeleteStep(2)}
                  >
                    Continue
                  </button>
                </div>
              </>
            ) : (
              <>
                <h3 className="text-lg font-semibold text-red-400">Final Confirmation</h3>
                <p className="text-sm text-ink-2">
                  Are you absolutely sure you want to permanently delete <strong>{character.name}</strong>?
                </p>
                {deleteError && (
                  <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{deleteError}</p>
                )}
                <div className="flex gap-3 pt-2">
                  <button
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-elevated text-ink-2 hover:text-ink transition-colors flex-1"
                    onClick={closeDeleteModal}
                    disabled={deleting}
                  >
                    Cancel
                  </button>
                  <button
                    className="bg-red-600 hover:bg-red-500 disabled:opacity-40 text-white text-sm px-4 py-2 rounded-lg transition-colors flex-1"
                    onClick={handleDeleteCharacter}
                    disabled={deleting}
                  >
                    {deleting ? 'Deleting…' : 'Delete Character Permanently'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** Timeline/mention post card. Attribution is always the authoring CHARACTER
 *  (from the post payload) — never an account. `character` is the profile
 *  being viewed; when the payload has no character of its own (legacy), the
 *  profile character is used for timeline items and "Wanderer" for mentions. */
function PostCard({
  item,
  character,
}: {
  item: ProfileTimelineItem;
  character: Character | null;
}) {
  const post = item.payload as {
    id?: number;
    title?: string;
    content?: string;
    image_url?: string;
    character_name?: string;
    character_avatar_url?: string;
    mentions?: import('@/lib/types').PostMention[];
  };

  const authorName = post.character_name || character?.name || 'Wanderer';
  const authorAvatar = post.character_avatar_url ?? (post.character_name ? null : character?.avatar_url) ?? null;

  return (
    <article className="py-6 border-b border-edge">
      <div className="flex items-center gap-2.5 mb-3 flex-wrap">
        <div className="w-8 h-8 rounded-full overflow-hidden bg-gem-soft flex items-center justify-center flex-shrink-0 border border-edge-md">
          {authorAvatar ? (
            <img src={authorAvatar} alt={authorName} className="w-full h-full object-cover" />
          ) : (
            <span className="text-sm font-semibold text-gem">{authorName.charAt(0)}</span>
          )}
        </div>
        <span className="text-sm font-medium text-ink">{authorName}</span>
        {item.realm_name && (
          <span className="font-mono text-[11px] text-ink-3">in {item.realm_name}</span>
        )}
        <span className="font-mono text-[11px] text-ink-3 ml-auto">
          {new Date(item.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
        </span>
      </div>
      {post.title && (
        <h3 className="font-serif text-lg font-medium text-ink mb-1.5 leading-snug">{post.title}</h3>
      )}
      <p className="font-serif text-[16px] text-ink whitespace-pre-wrap leading-[1.75]">
        <MentionText text={post.content ?? ''} mentions={post.mentions} />
      </p>
      {post.image_url && (
        <img
          src={post.image_url}
          alt={post.title || 'Post image'}
          className="mt-4 rounded-xl border border-edge max-h-96 object-contain"
          loading="lazy"
          decoding="async"
        />
      )}
    </article>
  );
}
