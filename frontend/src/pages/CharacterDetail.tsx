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
  Lock,
  Camera,
  BookOpen,
  MessageCircle,
  Globe,
  Users,
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

const VISIBILITY_ICONS = {
  public: Globe,
  friends: Users,
  private: Lock,
} as const;

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
      <div className="min-h-screen flex items-center justify-center text-gray-400">
        Loading…
      </div>
    );
  }

  if (error || !character) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-gray-400">{error || 'Character not found.'}</p>
        <button className="btn btn-secondary" onClick={() => navigate('/characters')}>
          Back to Characters
        </button>
      </div>
    );
  }

  const isOwner = !!(currentUser && character.owner_id === currentUser.id);
  const VisIcon = VISIBILITY_ICONS[character.visibility] || Globe;

  const coverPosX = character.cover_position_x ?? 0.5;
  const coverPosY = character.cover_position_y ?? 0.5;
  const avatarScale = character.avatar_scale ?? 1.0;
  const avatarPosX = character.avatar_position_x ?? 0.5;
  const avatarPosY = character.avatar_position_y ?? 0.5;

  const metaLine = [character.species, character.role, character.era].filter(Boolean).join(' · ');

  const tabs: { id: Tab; label: string }[] = [
    { id: 'timeline', label: 'Timeline' },
    { id: 'stories', label: 'Stories' },
    { id: 'media', label: 'Media' },
    { id: 'mentions', label: 'Mentions' },
    ...(isOwner ? [{ id: 'manage' as Tab, label: 'Manage' }] : []),
  ];

  return (
    <div className="min-h-screen bg-[#0F1419]">
      {/* === HERO — the character's public identity === */}
      <div className="relative" style={{ background: 'radial-gradient(ellipse 62% 92% at 0% 24%, rgba(130,100,215,0.15) 0%, transparent 75%), radial-gradient(ellipse 62% 92% at 100% 24%, rgba(16,185,129,0.14) 0%, transparent 75%), #0F1419' }}>
        <div className="max-w-[1000px] mx-auto px-4 sm:px-8 pt-0 pb-8">

          {/* Arrival banner */}
          {justCreated && (
            <div className="bg-emerald-600/10 border border-emerald-600/20 rounded-lg px-4 py-4 my-4 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Feather className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-semibold text-emerald-300">
                      {character.name} is live on Ficshon.
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      Write your first post to introduce them to the community.
                    </p>
                  </div>
                </div>
                <button
                  onClick={dismissBanner}
                  className="text-gray-600 hover:text-gray-400 transition-colors flex-shrink-0 mt-0.5"
                  aria-label="Dismiss"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => navigate('/')} className="btn btn-primary text-sm">
                  Post to The Commons
                </button>
                <button onClick={() => navigate('/storylab')} className="btn btn-secondary text-sm">
                  Open StoryLab
                </button>
              </div>
            </div>
          )}

          {/* Cover band */}
          <div className="relative h-[220px] sm:h-[300px] md:h-[360px] rounded-2xl overflow-hidden bg-gradient-to-br from-emerald-700 via-emerald-600 to-emerald-500">
            {character.cover_url && (
              <img
                src={character.cover_url}
                alt={`${character.name}'s cover`}
                className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                style={{ objectPosition: `${coverPosX * 100}% ${coverPosY * 100}%` }}
                draggable={false}
              />
            )}
            {/* Gradient vignette */}
            <div className="absolute inset-0" style={{ background: 'linear-gradient(to bottom, rgba(15,20,25,0.45) 0%, rgba(15,20,25,0.05) 35%, rgba(15,20,25,0.75) 100%)' }} />
            {!character.cover_url && (
              <div className="absolute inset-0 flex items-end justify-end p-4">
                <Feather className="w-16 h-16 text-white/10" />
              </div>
            )}
          </div>

          {/* Identity row — avatar overlaps the cover's lower edge */}
          <div className="flex items-start gap-4 sm:gap-5 -mt-5 sm:-mt-6 relative z-10">
            <div className="relative flex-shrink-0">
              <div className="w-28 h-28 sm:w-32 sm:h-32 md:w-36 md:h-36 rounded-2xl bg-gradient-to-br from-emerald-500 to-emerald-700 p-1 sm:p-1.5 shadow-2xl shadow-emerald-700/40 ring-[3px] ring-[#0F1419]">
                <div className="relative w-full h-full rounded-xl overflow-hidden bg-[#2D3139]">
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
                    <div className="w-full h-full flex items-center justify-center text-3xl font-bold text-white/80 bg-gradient-to-br from-emerald-500 to-emerald-700">
                      {character.name.charAt(0).toUpperCase()}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Name, meta, stats, action buttons */}
            <div className="flex-1 min-w-0 pt-9 sm:pt-11 md:pt-12">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0 flex-1">
                  <h1 className="text-xl sm:text-2xl md:text-[28px] font-bold text-white tracking-tight truncate">
                    {character.name}
                  </h1>
                  {metaLine && (
                    <p className="text-[#E8ECEF]/60 text-sm sm:text-base mt-0.5 truncate">{metaLine}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-3 sm:gap-5 mt-2">
                    <span className="flex items-baseline gap-1">
                      <span className="text-sm sm:text-base font-semibold text-white tracking-tight">{timeline.length}</span>
                      <span className="text-[#E8ECEF]/60 text-xs sm:text-sm">Posts</span>
                    </span>
                    <span className="flex items-baseline gap-1" title="Follower counts are coming soon">
                      <span className="text-sm sm:text-base font-semibold text-white/50 tracking-tight">—</span>
                      <span className="text-[#E8ECEF]/60 text-xs sm:text-sm">Followers</span>
                    </span>
                    {isOwner && (
                      <span className="inline-flex items-center gap-1.5 text-xs text-[#E8ECEF]/50">
                        <VisIcon className="w-3.5 h-3.5" />
                        <span className="capitalize">{character.visibility}</span>
                        {character.visual_locked && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-900/30 border border-emerald-800/40 text-emerald-400/80">
                            <Lock className="w-3 h-3" />
                            Identity locked
                          </span>
                        )}
                      </span>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0 pt-1">
                  {!isOwner && (
                    <>
                      {/* Messaging is character-to-character — only viewers who
                          own a character can open a conversation. */}
                      {(currentUser?.character_count ?? 0) > 0 && (
                        <button
                          className="bg-[#1A1D23] border border-[#E8ECEF]/15 text-[#E8ECEF]/90 hover:bg-[#252930] hover:border-[#E8ECEF]/30 hover:text-white px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium transition-all shadow-lg"
                          onClick={() => navigate(`/messages/new?characterId=${id}`)}
                        >
                          <MessageSquare className="w-4 h-4 flex-shrink-0" />
                          Message
                        </button>
                      )}
                      <button
                        className="bg-gradient-to-r from-emerald-500 to-emerald-400 hover:from-emerald-400 hover:to-emerald-500 text-white px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium transition-all shadow-lg shadow-emerald-500/30 border border-white/10"
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
                      className="bg-[#1A1D23] border border-[#2D3139] hover:border-[#E8ECEF]/20 text-[#E8ECEF]/80 hover:text-white px-4 py-2 rounded-lg flex items-center gap-2 text-sm transition-all"
                    >
                      <Sparkles className="w-4 h-4" />
                      Manage
                    </button>
                  )}
                </div>
              </div>
              {followHint && (
                <p className="text-xs text-[#E8ECEF]/40 mt-2">{followHint}</p>
              )}
            </div>
          </div>

          {/* Tabs */}
          <div className="flex items-center gap-1 mt-5 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-3 sm:px-5 py-2 rounded-lg text-xs sm:text-sm font-medium whitespace-nowrap transition-all duration-200 ${
                  activeTab === tab.id
                    ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/20'
                    : 'text-[#E8ECEF]/70 hover:text-white hover:bg-[#2D3139]/40'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* === CONTENT === */}
      <div className="max-w-[1000px] mx-auto px-4 sm:px-8 py-6 pb-16">

        {/* Bio — shown above every public tab */}
        {activeTab !== 'manage' && (character.short_bio || character.long_bio || character.tags) && (
          <div className="mb-8 max-w-3xl space-y-4">
            {character.short_bio && (
              <p className="text-[#E8ECEF]/90 text-base sm:text-lg leading-relaxed">{character.short_bio}</p>
            )}
            {character.long_bio && (
              <div className="bg-[#1A1D23]/40 border border-[#2D3139]/60 rounded-2xl p-4">
                <p className="text-sm text-[#E8ECEF]/70 whitespace-pre-wrap">{character.long_bio}</p>
              </div>
            )}
            {character.tags && (
              <div className="flex flex-wrap gap-2">
                {character.tags.split(',').map((tag, i) => (
                  <span key={i} className="px-2.5 py-1 bg-emerald-900/40 text-emerald-300 text-xs rounded-full border border-emerald-800/40">
                    {tag.trim()}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Timeline */}
        {activeTab === 'timeline' && (
          <div className="space-y-4">
            {timelineLoading ? (
              <p className="text-sm text-gray-500">Loading posts…</p>
            ) : timeline.length === 0 ? (
              <div className="rounded-2xl p-12 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                <Feather className="w-12 h-12 text-[#E8ECEF]/30 mx-auto mb-4" />
                <h3 className="text-white text-lg font-semibold mb-1">No Posts Yet</h3>
                <p className="text-[#E8ECEF]/60 text-sm">{character.name} hasn't posted yet.</p>
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
          <div className="rounded-2xl p-12 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
            <BookOpen className="w-12 h-12 text-[#E8ECEF]/30 mx-auto mb-4" />
            <h3 className="text-white text-lg font-semibold mb-1">No Stories Yet</h3>
            <p className="text-[#E8ECEF]/60 text-sm">
              Stories featuring {character.name} will appear here.
            </p>
          </div>
        )}

        {/* Media */}
        {activeTab === 'media' && (
          galleryImages.length === 0 ? (
            <div className="rounded-2xl p-12 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
              <Camera className="w-12 h-12 text-[#E8ECEF]/30 mx-auto mb-4" />
              <h3 className="text-white text-lg font-semibold mb-1">No Media Yet</h3>
              <p className="text-[#E8ECEF]/60 text-sm">
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
          <div className="space-y-4">
            {mentionsLoading && (
              <div className="flex justify-center py-12">
                <div className="w-8 h-8 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin" />
              </div>
            )}
            {!mentionsLoading && mentions.length === 0 && (
              <div className="rounded-2xl p-12 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                <MessageCircle className="w-12 h-12 text-[#E8ECEF]/30 mx-auto mb-4" />
                <h3 className="text-white text-lg font-semibold mb-1">No Mentions Yet</h3>
                <p className="text-[#E8ECEF]/60 text-sm">
                  Posts that mention {character.name} will appear here.
                </p>
              </div>
            )}
            {!mentionsLoading && mentions.map((item, idx) => (
              <PostCard key={idx} item={item} character={null} />
            ))}
          </div>
        )}

        {/* Manage — owner only */}
        {activeTab === 'manage' && isOwner && (
          <div className="space-y-6 max-w-3xl">
            <div className="rounded-2xl p-5 bg-[#1A1D23]/40 border border-[#2D3139]/60 space-y-3">
              <h3 className="text-sm font-semibold text-white">Character Tools</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => navigate(`/images?characterId=${character.id}`)}
                  className="text-sm flex items-center gap-2 btn btn-secondary"
                >
                  <ImageIcon className="w-3.5 h-3.5" />
                  Generate Images
                </button>
                {character.visual_locked && (
                  <button
                    onClick={() => setShowCanonModal(true)}
                    className="text-sm flex items-center gap-2 btn btn-secondary"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Manage Character Canon
                  </button>
                )}
              </div>
              <p className="text-xs text-gray-500">
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
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 shadow-lg pointer-events-none">
          {coverToast}
        </div>
      )}

      {/* Image lightbox */}
      <ErrorBoundary>
      {lightboxIdx !== null && galleryImages[lightboxIdx] && (
        <div
          className={`fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm transition-opacity duration-200 ${lbVisible ? 'opacity-100' : 'opacity-0'}`}
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
              className="w-full rounded-lg"
            />
            <div className="flex items-center justify-between mt-2">
              <p className="text-xs text-gray-400 capitalize">
                {galleryImages[lightboxIdx].kind?.replace(/_/g, ' ')}
              </p>
              {isOwner && (
                <button
                  className="text-xs px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
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
          <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh]">

            {/* Header */}
            <div className="flex items-center justify-between gap-3 px-6 pt-6 pb-4 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-emerald-900/40 border border-emerald-700/40 flex items-center justify-center flex-shrink-0">
                  <Sparkles className="w-4 h-4 text-emerald-400" />
                </div>
                <h2 className="text-sm font-semibold text-white">Manage Character Canon</h2>
              </div>
              <button
                onClick={() => setShowCanonModal(false)}
                className="text-gray-500 hover:text-gray-300 transition-colors p-1 flex-shrink-0"
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
          <div className="bg-gray-900 border border-gray-700 rounded-lg p-6 max-w-md w-full mx-4 space-y-4">
            {deleteStep === 1 ? (
              <>
                <h3 className="text-lg font-semibold text-red-400">Reset Character Identity</h3>
                <div className="text-sm text-gray-300 space-y-2">
                  <p>This will <strong>permanently delete</strong> your character <strong>{character.name}</strong> and all associated data:</p>
                  <ul className="list-disc list-inside text-gray-400 space-y-1">
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
                  <span className="text-sm text-gray-300">I understand this action is permanent and cannot be undone.</span>
                </label>
                <div className="flex gap-3 pt-2">
                  <button
                    className="btn btn-secondary text-sm flex-1"
                    onClick={closeDeleteModal}
                  >
                    Cancel
                  </button>
                  <button
                    className="bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm px-4 py-2 rounded transition-colors flex-1"
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
                <p className="text-sm text-gray-300">
                  Are you absolutely sure you want to permanently delete <strong>{character.name}</strong>?
                </p>
                {deleteError && (
                  <p className="text-sm text-red-400 bg-red-400/10 rounded-lg px-3 py-2">{deleteError}</p>
                )}
                <div className="flex gap-3 pt-2">
                  <button
                    className="btn btn-secondary text-sm flex-1"
                    onClick={closeDeleteModal}
                    disabled={deleting}
                  >
                    Cancel
                  </button>
                  <button
                    className="bg-red-600 hover:bg-red-500 disabled:opacity-40 text-white text-sm px-4 py-2 rounded transition-colors flex-1"
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
    <div className="rounded-2xl p-5 bg-[#1A1D23]/40 border border-[#2D3139]/60">
      <div className="flex items-center gap-2.5 mb-3 flex-wrap">
        <div className="w-8 h-8 rounded-lg overflow-hidden bg-emerald-600/20 border border-emerald-500/20 flex items-center justify-center flex-shrink-0">
          {authorAvatar ? (
            <img src={authorAvatar} alt={authorName} className="w-full h-full object-cover" />
          ) : (
            <span className="text-sm font-semibold text-emerald-400">{authorName.charAt(0)}</span>
          )}
        </div>
        <span className="text-sm font-medium text-emerald-400">{authorName}</span>
        {item.realm_name && (
          <span className="text-[11px] text-gray-600">in {item.realm_name}</span>
        )}
        <span className="text-[11px] text-gray-600 ml-auto">
          {new Date(item.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
        </span>
      </div>
      {post.title && (
        <h3 className="text-base font-semibold text-gray-100 mb-1">{post.title}</h3>
      )}
      <p className="text-sm text-gray-300 whitespace-pre-wrap leading-relaxed">
        <MentionText text={post.content ?? ''} mentions={post.mentions} />
      </p>
      {post.image_url && (
        <img
          src={post.image_url}
          alt={post.title || 'Post image'}
          className="mt-3 rounded-lg max-h-80 object-contain"
          loading="lazy"
          decoding="async"
        />
      )}
    </div>
  );
}
