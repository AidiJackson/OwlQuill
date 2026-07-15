import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { ficDebug } from '@/lib/ficDebug';
import { apiClient } from '@/lib/apiClient';
import { useAuthStore } from '@/lib/store';
import type { PublicUserProfile, ProfileTimelineItem, CharacterSearchResult, Post } from '@/lib/types';
import MentionText from '@/components/MentionText';
import {
  Camera,
  MapPin,
  Calendar,
  Feather,
  Heart,
  MessageCircle,
  Share2,
  BookOpen,
  UserPlus,
  Sparkles,
  RefreshCw,
  ChevronDown,
  Check,
  Move,
  Trash2,
} from 'lucide-react';
import AvatarPickerModal from '@/components/AvatarPickerModal';

type Tab = 'timeline' | 'characters' | 'stories' | 'media' | 'mentions';

export default function UserProfile() {
  const { username } = useParams<{ username: string }>();
  const navigate = useNavigate();
  const authUser = useAuthStore((s) => s.user);

  const [profile, setProfile] = useState<PublicUserProfile | null>(null);
  const [timeline, setTimeline] = useState<ProfileTimelineItem[]>([]);
  const [characters, setCharacters] = useState<CharacterSearchResult[]>([]);
  const [mentionedPosts, setMentionedPosts] = useState<Post[]>([]);
  const [mentionsLoading, setMentionsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('timeline');

  const isOwnProfile = authUser?.username === username;
  const isAdmin = (() => {
    if (!authUser?.email) return false;
    const adminList = (import.meta.env.VITE_ADMIN_EMAILS || '').split(',').map((e: string) => e.trim().toLowerCase()).filter(Boolean);
    return adminList.includes(authUser.email.toLowerCase());
  })();

  const setUser = useAuthStore((s) => s.setUser);

  // Cover generation (admin-only beta)
  const [showCoverGen, setShowCoverGen] = useState(false);
  const [coverGenLoading, setCoverGenLoading] = useState(false);
  const [coverGenError, setCoverGenError] = useState('');

  // Avatar picker
  const [showAvatarPicker, setShowAvatarPicker] = useState(false);

  // Cover action menu
  const [showCoverMenu, setShowCoverMenu] = useState(false);

  // Inline cover repositioning
  const [coverEditMode, setCoverEditMode] = useState(false);
  const [editPosX, setEditPosX] = useState(0.5);
  const [editPosY, setEditPosY] = useState(0.5);
  const [coverSaving, setCoverSaving] = useState(false);
  const [coverSaveError, setCoverSaveError] = useState('');
  const editPosXRef = useRef(0.5);
  const editPosYRef = useRef(0.5);
  const editDragRef = useRef<{ startX: number; startY: number; startPosX: number; startPosY: number } | null>(null);
  const editDragCleanup = useRef<(() => void) | null>(null);
  const coverHeroRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { editPosXRef.current = editPosX; }, [editPosX]);
  useEffect(() => { editPosYRef.current = editPosY; }, [editPosY]);


  // Avatar edit mode
  const [avatarEditMode, setAvatarEditMode] = useState(false);
  const [editAvatarX, setEditAvatarX] = useState(0.5);
  const [editAvatarY, setEditAvatarY] = useState(0.5);
  const [editAvatarScale, setEditAvatarScale] = useState(1.0);
  const [avatarSaving, setAvatarSaving] = useState(false);
  const [avatarSaveError, setAvatarSaveError] = useState('');
  const editAvatarXRef = useRef(0.5);
  const editAvatarYRef = useRef(0.5);
  const editAvatarScaleRef = useRef(1.0);
  const avatarFrameRef = useRef<HTMLDivElement | null>(null);
  const avatarDragCleanup = useRef<(() => void) | null>(null);
  useEffect(() => { editAvatarXRef.current = editAvatarX; }, [editAvatarX]);
  useEffect(() => { editAvatarYRef.current = editAvatarY; }, [editAvatarY]);
  useEffect(() => { editAvatarScaleRef.current = editAvatarScale; }, [editAvatarScale]);

  useEffect(() => {
    ficDebug.mount('UserProfile');
    return () => {
      editDragCleanup.current?.();
      avatarDragCleanup.current?.();
      ficDebug.unmount('UserProfile');
    };
  }, []);

  // Profile character selector (view-only, no global effect)
  const [selectedCharId, setSelectedCharId] = useState<number | null>(null);
  const [showCharSelector, setShowCharSelector] = useState(false);

  // CTA state for non-own profile buttons
  const [collaborateRequested, setCollaborateRequested] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [messageHint, setMessageHint] = useState('');

  const handleMessage = () => {
    if (characters.length === 0) {
      setMessageHint('This user has no characters yet.');
      setTimeout(() => setMessageHint(''), 3000);
      return;
    }
    navigate(`/messages/new?characterId=${characters[0].id}`);
  };

  const handleCollaborate = () => {
    setCollaborateRequested(true);
  };

  const handleShare = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch {
      // clipboard API unavailable — silent fail
    }
  };

  const coverPresets = [
    { id: 'enchanted_library', label: 'Enchanted Library' },
    { id: 'midnight_citadel', label: 'Midnight Citadel' },
    { id: 'celestial_garden', label: 'Celestial Garden' },
  ];

  const handleGenerateCover = async (presetName: string) => {
    setCoverGenLoading(true);
    setCoverGenError('');
    try {
      const result = await apiClient.generateProfileCover(presetName);
      setProfile((prev) => prev ? { ...prev, cover_url: result.cover_url } : prev);
      setShowCoverGen(false);
    } catch (err) {
      setCoverGenError(err instanceof Error ? err.message : 'Failed to generate cover.');
    } finally {
      setCoverGenLoading(false);
    }
  };

  const enterCoverEdit = (char: { id: number; cover_url?: string | null; cover_position_x?: number | null; cover_position_y?: number | null; cover_scale?: number | null }) => {
    ficDebug.modalOpen('UserProfile:coverEdit');
    setEditPosX(char.cover_position_x ?? 0.5);
    setEditPosY(char.cover_position_y ?? 0.5);
    setCoverSaveError('');
    setCoverEditMode(true);
  };

  const cancelCoverEdit = () => {
    ficDebug.modalClose('UserProfile:coverEdit');
    editDragCleanup.current?.();
    setCoverEditMode(false);
  };

  const enterAvatarEdit = () => {
    const char = editableAvatarChar;
    if (!char) return;
    setEditAvatarX(char.avatar_position_x ?? 0.5);
    setEditAvatarY(char.avatar_position_y ?? 0.5);
    setEditAvatarScale(char.avatar_scale ?? 1.0);
    setAvatarSaveError('');
    setAvatarEditMode(true);
  };

  const cancelAvatarEdit = () => {
    avatarDragCleanup.current?.();
    setAvatarEditMode(false);
  };

  const saveAvatarEdit = async () => {
    if (!editableAvatarChar) return;
    setAvatarSaving(true);
    setAvatarSaveError('');
    try {
      await apiClient.updateCharacter(editableAvatarChar.id, {
        avatar_position_x: editAvatarXRef.current,
        avatar_position_y: editAvatarYRef.current,
        avatar_scale: editAvatarScaleRef.current,
      });
      setCharacters((prev) =>
        prev.map((c) =>
          c.id === editableAvatarChar.id
            ? { ...c, avatar_position_x: editAvatarXRef.current, avatar_position_y: editAvatarYRef.current, avatar_scale: editAvatarScaleRef.current }
            : c
        )
      );
      setAvatarEditMode(false);
    } catch (err) {
      setAvatarSaveError(err instanceof Error ? err.message : 'Failed to save.');
    } finally {
      setAvatarSaving(false);
    }
  };

  const saveCoverEdit = async (charId: number) => {
    setCoverSaving(true);
    setCoverSaveError('');
    try {
      await apiClient.updateCharacter(charId, {
        cover_position_x: editPosXRef.current,
        cover_position_y: editPosYRef.current,
        cover_scale: 1.0,
      });
      setCharacters((prev) =>
        prev.map((c) =>
          c.id === charId ? { ...c, cover_position_x: editPosXRef.current, cover_position_y: editPosYRef.current, cover_scale: 1.0 } : c
        )
      );
      ficDebug.modalClose('UserProfile:coverEdit');
      setCoverEditMode(false);
    } catch (err) {
      setCoverSaveError(err instanceof Error ? err.message : 'Failed to save.');
    } finally {
      setCoverSaving(false);
    }
  };

  const startCoverDrag = useCallback((clientX: number, clientY: number) => {
    editDragCleanup.current?.();
    ficDebug.dragStart('UserProfile:coverDrag');
    editDragRef.current = {
      startX: clientX,
      startY: clientY,
      startPosX: editPosXRef.current,
      startPosY: editPosYRef.current,
    };
    // object-position approach: drag right reveals left side of image (posX decreases)
    const applyMove = (x: number, y: number) => {
      if (!editDragRef.current || !coverHeroRef.current) return;
      const { offsetWidth: w, offsetHeight: h } = coverHeroRef.current;
      const dx = (x - editDragRef.current.startX) / w;
      const dy = (y - editDragRef.current.startY) / h;
      setEditPosX(Math.min(1, Math.max(0, editDragRef.current.startPosX - dx)));
      setEditPosY(Math.min(1, Math.max(0, editDragRef.current.startPosY - dy)));
    };
    const onMouseMove = (ev: MouseEvent) => applyMove(ev.clientX, ev.clientY);
    const onTouchMove = (ev: TouchEvent) => { ev.preventDefault(); applyMove(ev.touches[0].clientX, ev.touches[0].clientY); };
    const onEnd = () => {
      ficDebug.dragEnd('UserProfile:coverDrag');
      editDragRef.current = null;
      editDragCleanup.current = null;
      ficDebug.listenerRemove('UserProfile:mousemove');
      ficDebug.listenerRemove('UserProfile:mouseup');
      ficDebug.listenerRemove('UserProfile:touchmove');
      ficDebug.listenerRemove('UserProfile:touchend');
      ficDebug.listenerRemove('UserProfile:touchcancel');
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onEnd);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onEnd);
      window.removeEventListener('touchcancel', onEnd);
    };
    editDragCleanup.current = onEnd;
    ficDebug.listenerAttach('UserProfile:mousemove');
    ficDebug.listenerAttach('UserProfile:mouseup');
    ficDebug.listenerAttach('UserProfile:touchmove');
    ficDebug.listenerAttach('UserProfile:touchend');
    ficDebug.listenerAttach('UserProfile:touchcancel');
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onEnd);
    window.addEventListener('touchmove', onTouchMove, { passive: false });
    window.addEventListener('touchend', onEnd);
    window.addEventListener('touchcancel', onEnd);
  }, []);

  const startAvatarDrag = useCallback((clientX: number, clientY: number) => {
    avatarDragCleanup.current?.();
    const currentScale = editAvatarScaleRef.current;
    if (currentScale <= 1.001) return;
    const startState = { startX: clientX, startY: clientY, startPosX: editAvatarXRef.current, startPosY: editAvatarYRef.current };
    const applyMove = (x: number, y: number) => {
      if (!avatarFrameRef.current) return;
      const { offsetWidth: w, offsetHeight: h } = avatarFrameRef.current;
      const s = editAvatarScaleRef.current;
      if (s <= 1.001) return;
      const dx = (x - startState.startX) / w;
      const dy = (y - startState.startY) / h;
      const dposX = -dx * s / (s - 1);
      const dposY = -dy * s / (s - 1);
      setEditAvatarX(Math.min(1, Math.max(0, startState.startPosX + dposX)));
      setEditAvatarY(Math.min(1, Math.max(0, startState.startPosY + dposY)));
    };
    const onMouseMove = (ev: MouseEvent) => applyMove(ev.clientX, ev.clientY);
    const onTouchMove = (ev: TouchEvent) => { ev.preventDefault(); applyMove(ev.touches[0].clientX, ev.touches[0].clientY); };
    const onEnd = () => {
      avatarDragCleanup.current = null;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onEnd);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onEnd);
      window.removeEventListener('touchcancel', onEnd);
    };
    avatarDragCleanup.current = onEnd;
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onEnd);
    window.addEventListener('touchmove', onTouchMove, { passive: false });
    window.addEventListener('touchend', onEnd);
    window.addEventListener('touchcancel', onEnd);
  }, []);

  useEffect(() => {
    if (showAvatarPicker) ficDebug.modalOpen('UserProfile:avatarPicker');
    else ficDebug.modalClose('UserProfile:avatarPicker');
  }, [showAvatarPicker]);

  useEffect(() => {
    setSelectedCharId(null);
    setShowCharSelector(false);
  }, [username]);

  // Fetch mentions when mentions tab is first activated
  useEffect(() => {
    if (activeTab !== 'mentions' || !username) return;
    if (mentionedPosts.length > 0) return; // already loaded
    setMentionsLoading(true);
    apiClient.getUserMentions(username)
      .then(setMentionedPosts)
      .catch(() => setMentionedPosts([]))
      .finally(() => setMentionsLoading(false));
  }, [activeTab, username]);

  useEffect(() => {
    if (!username) return;
    setLoading(true);
    setError(null);

    Promise.all([
      apiClient.getUserProfile(username),
      apiClient.getUserTimeline(username, 20),
      apiClient.getUserCharacters(username),
    ])
      .then(([profileData, timelineData, charsData]) => {
        setProfile(profileData);
        setTimeline(timelineData);
        setCharacters(charsData);
        // Restore the owner's saved default presentation from localStorage.
        // Only applies when viewing your own profile; visitors always start fresh.
        if (authUser?.username === username) {
          const saved = localStorage.getItem(`fic_profile_default_view_${username}`);
          if (saved && saved !== 'user') {
            const savedCharId = parseInt(saved, 10);
            if (!isNaN(savedCharId) && charsData.some((c: CharacterSearchResult) => c.id === savedCharId)) {
              setSelectedCharId(savedCharId);
            }
          }
        }
      })
      .catch(() => setError('User not found'))
      .finally(() => setLoading(false));
  }, [username]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-emerald-500/30 border-t-emerald-500 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-[#E8ECEF]/60">Loading profile...</p>
        </div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <p className="text-[#E8ECEF]/60 mb-4">{error || 'User not found'}</p>
        <button onClick={() => navigate('/')} className="btn btn-secondary">
          Go Home
        </button>
      </div>
    );
  }

  const displayName = profile.display_name || profile.username;

  // Character-first profile surface (profile-view only, no global effect)
  const activeChar = characters.find((c) => c.id === selectedCharId) ?? null;
  const heroDisplayName = activeChar ? activeChar.name : displayName;
  const heroAvatarUrl = activeChar?.avatar_url ?? profile.avatar_url ?? null;

  // Character whose cover can be repositioned inline (own profile only)
  // Must be declared before heroCover* so position falls through correctly
  const editableChar = activeChar ?? (characters.length === 1 && characters[0].cover_url ? characters[0] : null);
  const canEditCoverInline = isOwnProfile && !!editableChar;

  // Character whose avatar can be repositioned — does NOT require cover_url.
  // editableChar gates on cover_url which silently blocks avatar edit for users
  // who have a character but no cover image yet.
  const editableAvatarChar = activeChar ?? (characters.length === 1 ? characters[0] : null);

  // Use editableChar as the cover source when no explicit character is selected,
  // so position reads/writes are consistent with what the reposition feature saves.
  const heroCoverChar = activeChar ?? editableChar;
  const heroCoverUrl = heroCoverChar?.cover_url ?? profile.cover_url ?? null;
  const heroCoverPositionY = heroCoverChar?.cover_position_y ?? 0.5;
  const isMobile = window.innerWidth < 768;
  const heroCoverPositionX = heroCoverChar?.cover_position_x ?? (isMobile ? 0.2 : 0.5);
  const heroBio = activeChar ? (activeChar.short_bio ?? null) : (profile.bio ?? null);

  // What the hero actually renders — stays on same cover URL in/out of edit mode
  const displayCoverUrl = heroCoverUrl;
  const displayPosX = coverEditMode ? editPosX : heroCoverPositionX;
  const displayPosY = coverEditMode ? editPosY : heroCoverPositionY;

  const joinDate = new Date(profile.created_at).toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
  });

  // Roster visibility (seeding mode): a user's character roster/count is only
  // shown to its owner. In seeding mode the API returns an empty roster to
  // non-owners, so `characters.length === 0` there and we hide the count/tab/
  // selector entirely. With seeding mode off the API returns public characters
  // and this naturally shows them.
  const showRoster = isOwnProfile || characters.length > 0;

  const stats = {
    posts: timeline.filter((i) => i.type === 'post').length,
    characters: characters.length,
    realms: 0,
    collaborators: 0,
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: 'timeline', label: 'Timeline' },
    ...(showRoster ? [{ id: 'characters' as Tab, label: 'Characters' }] : []),
    { id: 'stories', label: 'Stories' },
    { id: 'media', label: 'Media' },
    { id: 'mentions', label: 'Mentions' },
  ];

  return (
    <div className="min-h-screen bg-[#0F1419]">
      {/* === HERO SECTION — constrained width, Facebook-style === */}
      {/* Atmospheric hero wrapper: full-bleed radial wash with Ficshon tones */}
      <div className="relative" style={{background: 'radial-gradient(ellipse 62% 92% at 0% 24%, rgba(130,100,215,0.15) 0%, transparent 75%), radial-gradient(ellipse 62% 92% at 100% 24%, rgba(16,185,129,0.14) 0%, transparent 75%), radial-gradient(ellipse 70% 34% at 50% 0%, rgba(16,185,129,0.06) 0%, transparent 60%), #0F1419'}}>
      <div className="max-w-[1000px] mx-auto px-4 sm:px-8 pt-0 pb-20 sm:pb-28 md:pb-36">

        {/* Cover band — rounded, not full-bleed */}
        <div
          ref={coverHeroRef}
          className="relative h-[290px] sm:h-[380px] md:h-[460px] rounded-2xl overflow-hidden bg-gradient-to-br from-emerald-700 via-emerald-600 to-emerald-500"
          style={coverEditMode ? { cursor: 'grab', touchAction: 'none', userSelect: 'none' } : undefined}
          onMouseDown={coverEditMode ? (e) => { e.preventDefault(); startCoverDrag(e.clientX, e.clientY); } : undefined}
          onTouchStart={coverEditMode ? (e) => { e.preventDefault(); startCoverDrag(e.touches[0].clientX, e.touches[0].clientY); } : undefined}
        >
          {/* Edit-mode overlay: drag hint only */}
          {coverEditMode && (
            <div className="absolute inset-0 z-20 pointer-events-none flex items-start justify-center pt-3">
              <span className="text-sm text-white/70 select-none font-medium bg-[#0F1419]/60 backdrop-blur-sm rounded-xl px-4 py-2">
                Drag to reposition
              </span>
            </div>
          )}

          {/* Cover image (if set) — scale+translate transform pans within the container.
               At scale=1 this is identity. At scale>1, translate ranges guarantee no empty edges. */}
          {displayCoverUrl && (
            <img
              src={displayCoverUrl}
              alt="Profile cover"
              className="absolute inset-0 w-full h-full object-cover pointer-events-none"
              style={{ objectPosition: `${displayPosX * 100}% ${displayPosY * 100}%` }}
              draggable={false}
            />
          )}

          {/* Gradient overlay — richer vignette: strong top/bottom darkening + side tints */}
          <div className="absolute inset-0" style={{background: 'linear-gradient(to bottom, rgba(15,20,25,0.50) 0%, rgba(15,20,25,0.08) 35%, rgba(15,20,25,0.78) 100%), linear-gradient(to bottom right, rgba(16,185,129,0.10) 0%, transparent 50%), linear-gradient(to bottom left, rgba(168,85,247,0.08) 0%, transparent 42%)'}} />

          {/* Subtle pattern (no cover image) */}
          {!heroCoverUrl && (
            <div
              className="absolute inset-0 opacity-[0.03]"
              style={{
                backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
              }}
            />
          )}

          {/* Cover action menu — own profile, not in reposition mode */}
          {isOwnProfile && !coverEditMode && (
            <div className="absolute bottom-3 right-3 z-20">
              <button
                onClick={() => setShowCoverMenu((v) => !v)}
                className="bg-[#0F1419]/80 md:bg-[#0F1419]/60 md:backdrop-blur-md border border-[#E8ECEF]/10 text-white hover:bg-[#1A1D23]/80 hover:border-[#E8ECEF]/20 px-3 py-1.5 rounded-lg flex items-center gap-1.5 text-xs sm:text-sm transition-all shadow-lg"
              >
                <Camera className="w-3.5 h-3.5" />
                <span>Cover</span>
                <ChevronDown className="w-3 h-3 text-white/60" />
              </button>

              {showCoverMenu && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setShowCoverMenu(false)} />
                  <div className="absolute bottom-full right-0 mb-2 z-50 bg-[#1A1D23] border border-[#2D3139] rounded-xl shadow-2xl shadow-black/60 py-1.5 min-w-[180px]">
                    <Link
                      to="/images"
                      onClick={() => setShowCoverMenu(false)}
                      className="flex items-center gap-3 px-4 py-2.5 text-sm text-[#E8ECEF]/80 hover:text-white hover:bg-[#252930] transition-colors"
                    >
                      <Camera className="w-4 h-4 flex-shrink-0" />
                      Choose cover
                    </Link>
                    {canEditCoverInline && (
                      <button
                        onClick={() => { enterCoverEdit(editableChar!); setShowCoverMenu(false); }}
                        className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-[#E8ECEF]/80 hover:text-white hover:bg-[#252930] transition-colors text-left"
                      >
                        <Move className="w-4 h-4 flex-shrink-0" />
                        Reposition
                      </button>
                    )}
                    {isAdmin && (
                      <button
                        onClick={() => { setShowCoverGen((v) => !v); setShowCoverMenu(false); }}
                        className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-[#E8ECEF]/80 hover:text-white hover:bg-[#252930] transition-colors text-left"
                      >
                        <Sparkles className="w-4 h-4 flex-shrink-0" />
                        Generate cover
                      </button>
                    )}
                    <div className="h-px bg-[#2D3139] mx-3 my-1" />
                    <button
                      disabled
                      title="Cover removal is not yet supported"
                      className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-[#E8ECEF]/30 cursor-not-allowed text-left"
                    >
                      <Trash2 className="w-4 h-4 flex-shrink-0" />
                      Remove cover
                    </button>
                  </div>
                </>
              )}
            </div>
          )}

          {/* Admin: cover generation panel */}
          {showCoverGen && isAdmin && (
            <div className="absolute bottom-14 right-3 z-30 bg-[#1A1D23]/90 backdrop-blur-md border border-[#E8ECEF]/10 rounded-lg p-3 shadow-xl space-y-2 min-w-[200px]">
              <p className="text-xs text-[#E8ECEF]/50 flex items-center gap-1">
                <Sparkles className="w-3 h-3" />
                Generate Cover (Beta)
              </p>
              {coverPresets.map((preset) => (
                <button
                  key={preset.id}
                  onClick={() => handleGenerateCover(preset.id)}
                  disabled={coverGenLoading}
                  className="w-full text-left text-sm text-[#E8ECEF]/80 hover:text-white hover:bg-[#2D3139]/60 px-2 py-1.5 rounded transition-colors disabled:opacity-40"
                >
                  {preset.label}
                </button>
              ))}
              {coverGenLoading && (
                <div className="flex items-center gap-2 text-xs text-[#E8ECEF]/50 px-2 py-1">
                  <RefreshCw className="w-3 h-3 animate-spin" />
                  Generating...
                </div>
              )}
              {coverGenError && (
                <p className="text-xs text-red-400 px-2">{coverGenError}</p>
              )}
            </div>
          )}
        </div>

        {/* Identity row — avatar overlaps the cover's lower edge */}
        <div className="flex items-start gap-4 sm:gap-5 -mt-4 sm:-mt-5 md:-mt-6 relative z-10">

          {/* Avatar — pulled up to straddle the cover bottom edge */}
          <div className="relative flex-shrink-0">
            <div
              ref={avatarFrameRef}
              className="w-32 h-32 sm:w-36 sm:h-36 md:w-40 md:h-40 rounded-2xl bg-gradient-to-br from-emerald-500 to-emerald-700 p-1 sm:p-1.5 shadow-2xl shadow-emerald-700/40 ring-[3px] ring-[#0F1419]"
              style={avatarEditMode ? { cursor: 'grab', touchAction: 'none', userSelect: 'none' } : undefined}
              onMouseDown={avatarEditMode ? (e) => { e.preventDefault(); startAvatarDrag(e.clientX, e.clientY); } : undefined}
              onTouchStart={avatarEditMode ? (e) => { e.preventDefault(); startAvatarDrag(e.touches[0].clientX, e.touches[0].clientY); } : undefined}
            >
              <div className="relative w-full h-full rounded-xl overflow-hidden bg-[#2D3139]">
                {heroAvatarUrl ? (
                  <img
                    src={heroAvatarUrl}
                    alt={`${heroDisplayName}'s avatar`}
                    className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                    style={(() => {
                      const s = avatarEditMode ? editAvatarScale : (editableAvatarChar?.avatar_scale ?? 1.0);
                      if (!avatarEditMode && s <= 1.001) return {};
                      const px = avatarEditMode ? editAvatarX : (editableAvatarChar?.avatar_position_x ?? 0.5);
                      const py = avatarEditMode ? editAvatarY : (editableAvatarChar?.avatar_position_y ?? 0.5);
                      return {
                        transformOrigin: 'center center',
                        transform: `scale(${s}) translate(${(0.5 - px) * (s - 1) / s * 100}%, ${(0.5 - py) * (s - 1) / s * 100}%)`,
                      };
                    })()}
                    onError={(e) => { e.currentTarget.style.display = 'none'; }}
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-2xl sm:text-3xl md:text-4xl font-bold text-white/80 bg-gradient-to-br from-emerald-500 to-emerald-700">
                    {profile.username.charAt(0).toUpperCase()}
                  </div>
                )}
              </div>
            </div>
            {isOwnProfile && !avatarEditMode && (
              <button
                onClick={() => setShowAvatarPicker(true)}
                className="absolute -bottom-1 -right-1 w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-emerald-500 hover:bg-emerald-400 shadow-lg shadow-emerald-500/30 flex items-center justify-center transition-all border border-white/10"
              >
                <Camera className="w-3.5 h-3.5 text-white" />
              </button>
            )}
            {isOwnProfile && heroAvatarUrl && !avatarEditMode && (
              <button
                onClick={enterAvatarEdit}
                title="Reposition avatar"
                className="absolute -bottom-1 -left-1 w-8 h-8 sm:w-9 sm:h-9 rounded-xl bg-[#1A1D23] hover:bg-[#252930] border border-[#2D3139] hover:border-emerald-500/40 shadow-lg flex items-center justify-center transition-all"
              >
                <Move className="w-3.5 h-3.5 text-[#E8ECEF]/60" />
              </button>
            )}
          </div>

          {/* Name, username, stats, action buttons */}
          <div className="flex-1 min-w-0 pt-12 sm:pt-14 md:pt-16">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div className="min-w-0 flex-1">
                <h1 className="text-xl sm:text-2xl md:text-[28px] font-bold text-white tracking-tight truncate">
                  {heroDisplayName}
                </h1>
                <p className="text-[#E8ECEF]/60 text-sm sm:text-base mt-0.5">
                  @{profile.username}
                </p>
                {/* Stats inline below username */}
                <div className="flex flex-wrap items-center gap-3 sm:gap-5 md:gap-7 mt-2 sm:mt-3">
                  {[
                    { label: 'Posts', value: stats.posts },
                    ...(showRoster ? [{ label: 'Characters', value: stats.characters }] : []),
                    { label: 'Realms', value: stats.realms },
                    { label: 'Collaborators', value: stats.collaborators },
                  ].map((stat) => (
                    <button
                      key={stat.label}
                      className="flex items-baseline gap-1 hover:opacity-80 transition-opacity"
                    >
                      <span className="text-sm sm:text-base font-semibold text-white tracking-tight">
                        {stat.value.toLocaleString()}
                      </span>
                      <span className="text-[#E8ECEF]/60 text-xs sm:text-sm">{stat.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2 flex-shrink-0 pt-1">
                {isOwnProfile && (
                  <button
                    onClick={() => navigate('/profile')}
                    className="bg-[#1A1D23] border border-[#2D3139] hover:border-[#E8ECEF]/20 text-[#E8ECEF]/80 hover:text-white px-3 sm:px-4 py-1.5 sm:py-2 rounded-lg flex items-center gap-2 text-sm transition-all"
                  >
                    <span className="hidden sm:inline">Edit Profile</span>
                    <span className="sm:hidden">Edit</span>
                  </button>
                )}
                {!isOwnProfile && (
                  <>
                    <button
                      onClick={handleMessage}
                      className="bg-[#1A1D23] border border-[#E8ECEF]/15 text-[#E8ECEF]/90 hover:bg-[#252930] hover:border-[#E8ECEF]/30 hover:text-white px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium transition-all shadow-lg"
                    >
                      <MessageCircle className="w-4 h-4 flex-shrink-0" />
                      Message
                    </button>
                    <button
                      onClick={handleCollaborate}
                      disabled={collaborateRequested}
                      className={`px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium transition-all shadow-lg border ${
                        collaborateRequested
                          ? 'bg-[#1A1D23] border-emerald-800/40 text-emerald-400/70 cursor-default'
                          : 'bg-gradient-to-r from-emerald-500 to-emerald-400 hover:from-emerald-400 hover:to-emerald-500 text-white shadow-emerald-500/30 border-white/10'
                      }`}
                    >
                      <UserPlus className="w-4 h-4 flex-shrink-0" />
                      {collaborateRequested ? 'Requested' : 'Collaborate'}
                    </button>
                    <button
                      onClick={handleShare}
                      className="bg-[#1A1D23] border border-[#E8ECEF]/10 text-[#E8ECEF]/50 hover:text-[#E8ECEF]/80 hover:border-[#E8ECEF]/20 p-2 rounded-lg transition-all shadow-lg"
                      title={shareCopied ? 'Link copied!' : 'Copy profile link'}
                    >
                      {shareCopied ? (
                        <Check className="w-4 h-4 text-emerald-400" />
                      ) : (
                        <Share2 className="w-4 h-4" />
                      )}
                    </button>
                  </>
                )}
              </div>
            </div>
            {/* Inline feedback hints below the button row */}
            {!isOwnProfile && (messageHint || collaborateRequested) && (
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 pl-0">
                {messageHint && (
                  <p className="text-xs text-[#E8ECEF]/40">{messageHint}</p>
                )}
                {collaborateRequested && (
                  <p className="text-xs text-[#E8ECEF]/40">Collaboration invites are coming soon — we'll notify you.</p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 mt-5 sm:mt-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 sm:px-5 py-2 sm:py-2.5 rounded-lg text-xs sm:text-sm font-medium transition-all duration-200 ${
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

      {/* Hero/body cutoff — soft gradient edge */}
      <div className="h-px mx-auto max-w-[1000px] px-8">
        <div className="h-px bg-gradient-to-r from-transparent via-white/[0.07] to-transparent" />
      </div>
      <div className="h-20 bg-gradient-to-b from-[#1A1D23]/65 to-transparent pointer-events-none" />
      </div>{/* end atmospheric hero wrapper */}

      {/* === CONTENT AREA === */}
      <div className="bg-[#0F1419]">
        <div className="max-w-[1000px] mx-auto px-4 sm:px-8 py-8 sm:py-12">
          {/* Character Selector — owner sees it with 1+ characters; visitors need 2+ */}
          {(isOwnProfile ? characters.length >= 1 : characters.length > 1) && (
            <div className="flex items-center gap-3 mb-6">
              <span className="text-xs text-[#E8ECEF]/40 uppercase tracking-wider font-medium flex-shrink-0">
                Viewing as
              </span>
              <div className="relative">
                <button
                  onClick={() => setShowCharSelector((v) => !v)}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#1A1D23]/60 border border-[#2D3139] hover:border-[#E8ECEF]/20 transition-all text-sm"
                >
                  {activeChar ? (
                    <>
                      {activeChar.avatar_url ? (
                        <img src={activeChar.avatar_url} alt="" className="w-5 h-5 rounded-md object-cover flex-shrink-0" />
                      ) : (
                        <div className="w-5 h-5 rounded-md bg-emerald-600/30 flex items-center justify-center text-[10px] text-emerald-400 font-medium flex-shrink-0">
                          {activeChar.name.charAt(0)}
                        </div>
                      )}
                      <span className="text-[#E8ECEF]/90 font-medium">{activeChar.name}</span>
                    </>
                  ) : (
                    <>
                      {profile.avatar_url ? (
                        <img src={profile.avatar_url} alt="" className="w-5 h-5 rounded-md object-cover flex-shrink-0" />
                      ) : (
                        <div className="w-5 h-5 rounded-md bg-[#2D3139] flex items-center justify-center text-[10px] text-[#E8ECEF]/50 font-medium flex-shrink-0">
                          {profile.username.charAt(0).toUpperCase()}
                        </div>
                      )}
                      <span className="text-[#E8ECEF]/60">Profile</span>
                    </>
                  )}
                  <ChevronDown className="w-3.5 h-3.5 text-[#E8ECEF]/40 flex-shrink-0" />
                </button>

                {showCharSelector && (
                  <>
                    {/* Backdrop */}
                    <div className="fixed inset-0 z-40" onClick={() => setShowCharSelector(false)} />
                    {/* Popover */}
                    <div className="absolute left-0 top-full mt-1.5 z-50 bg-[#1A1D23] border border-[#2D3139] rounded-xl shadow-2xl shadow-black/60 py-1.5 min-w-[220px]">
                      {/* User profile option */}
                      <button
                        onClick={() => {
                          setSelectedCharId(null);
                          setShowCharSelector(false);
                          if (isOwnProfile && username) {
                            localStorage.setItem(`fic_profile_default_view_${username}`, 'user');
                          }
                        }}
                        className={`w-full flex items-center gap-3 px-3 py-2.5 hover:bg-[#252930] transition-colors text-left ${!activeChar ? 'text-emerald-400' : 'text-[#E8ECEF]/80'}`}
                      >
                        {profile.avatar_url ? (
                          <img src={profile.avatar_url} alt="" className="w-8 h-8 rounded-lg object-cover flex-shrink-0" />
                        ) : (
                          <div className="w-8 h-8 rounded-lg bg-[#2D3139] border border-[#3D4149] flex items-center justify-center text-sm font-medium text-[#E8ECEF]/50 flex-shrink-0">
                            {profile.username.charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium truncate">{displayName}</p>
                          <p className="text-xs text-[#E8ECEF]/40">User profile</p>
                        </div>
                        {!activeChar && <Check className="w-4 h-4 flex-shrink-0" />}
                      </button>

                      <div className="h-px bg-[#2D3139] mx-3 my-1" />

                      {/* Character options */}
                      {characters.map((ch) => (
                        <button
                          key={ch.id}
                          onClick={() => {
                            setSelectedCharId(ch.id);
                            setShowCharSelector(false);
                            if (isOwnProfile && username) {
                              localStorage.setItem(`fic_profile_default_view_${username}`, String(ch.id));
                            }
                          }}
                          className={`w-full flex items-center gap-3 px-3 py-2.5 hover:bg-[#252930] transition-colors text-left ${activeChar?.id === ch.id ? 'text-emerald-400' : 'text-[#E8ECEF]/80'}`}
                        >
                          {ch.avatar_url ? (
                            <img src={ch.avatar_url} alt={ch.name} className="w-8 h-8 rounded-lg object-cover flex-shrink-0" />
                          ) : (
                            <div className="w-8 h-8 rounded-lg bg-emerald-600/20 border border-emerald-500/20 flex items-center justify-center text-sm font-medium text-emerald-400 flex-shrink-0">
                              {ch.name.charAt(0)}
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="text-sm font-medium truncate">{ch.name}</p>
                            {ch.species && <p className="text-xs text-[#E8ECEF]/40 truncate">{ch.species}</p>}
                          </div>
                          {activeChar?.id === ch.id && <Check className="w-4 h-4 flex-shrink-0" />}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Bio Section */}
          <div className="mb-8 max-w-3xl">
            {heroBio && (
              <p className="text-[#E8ECEF]/90 text-base sm:text-lg leading-relaxed mb-6">
                {heroBio}
              </p>
            )}

            {/* Writing Focus & Meta */}
            <div className="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-6">
              <div className="flex items-center gap-2 flex-wrap">
                {['Fantasy', 'Dark Academia', 'Romance'].map((focus, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded-full text-xs hover:bg-emerald-500/30 transition-all"
                  >
                    <Feather className="w-3 h-3" />
                    {focus}
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-5 text-[#E8ECEF]/60">
                <span className="flex items-center gap-2 text-sm">
                  <MapPin className="w-4 h-4" />
                  Creative Realm
                </span>
                <span className="flex items-center gap-2 text-sm">
                  <Calendar className="w-4 h-4" />
                  Joined {joinDate}
                </span>
              </div>
            </div>
          </div>

          {/* Separator */}
          <div className="h-px bg-gradient-to-r from-transparent via-[#2D3139] to-transparent mb-8" />

          {/* Tab Content */}
          <div className="pb-12">
            {activeTab === 'timeline' && (
              <div className="space-y-6">
                {timeline.length === 0 ? (
                  <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                    <Feather className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                    <h3 className="text-white text-xl font-semibold mb-2">
                      No Posts Yet
                    </h3>
                    <p className="text-[#E8ECEF]/60">
                      {isOwnProfile
                        ? 'Share your first post to get started.'
                        : `When ${profile.username} posts, it will appear here.`}
                    </p>
                  </div>
                ) : (
                  timeline.map((item, idx) => (
                    <TimelineItemCard
                      key={idx}
                      item={item}
                      profile={profile}
                    />
                  ))
                )}
              </div>
            )}

            {showRoster && activeTab === 'characters' && (
              <div>
                {characters.length === 0 ? (
                  <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                    <Feather className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                    <h3 className="text-white text-xl font-semibold mb-2">
                      No Public Characters Yet
                    </h3>
                    <p className="text-[#E8ECEF]/60">
                      {isOwnProfile
                        ? 'Create your first character to share with the community.'
                        : `When ${profile.username} shares characters, they'll appear here.`}
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    {characters.map((ch) => (
                      <Link
                        key={ch.id}
                        to={`/characters/${ch.id}`}
                        className="rounded-2xl p-5 bg-[#1A1D23]/40 border border-[#2D3139]/60 hover:border-emerald-500/40 hover:bg-[#1A1D23]/60 transition-all group"
                      >
                        <div className="flex items-start gap-4">
                          {ch.avatar_url ? (
                            <img
                              src={ch.avatar_url}
                              alt={ch.name}
                              className="w-14 h-14 rounded-xl object-cover border border-[#2D3139] flex-shrink-0 group-hover:border-emerald-500/30 transition-colors"
                              loading="lazy"
                              decoding="async"
                            />
                          ) : (
                            <div className="w-14 h-14 rounded-xl bg-[#2D3139] border border-[#3D4149] flex items-center justify-center flex-shrink-0">
                              <Feather className="w-6 h-6 text-[#E8ECEF]/30" />
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <h4 className="font-semibold text-white truncate group-hover:text-emerald-400 transition-colors">
                              {ch.name}
                            </h4>
                            {ch.species && (
                              <p className="text-sm text-[#E8ECEF]/50 mt-0.5">{ch.species}</p>
                            )}
                            {ch.short_bio && (
                              <p className="text-sm text-[#E8ECEF]/60 mt-2 line-clamp-2 leading-relaxed">
                                {ch.short_bio}
                              </p>
                            )}
                          </div>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === 'stories' && (
              <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                <BookOpen className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                <h3 className="text-white text-xl font-semibold mb-2">
                  No Stories Yet
                </h3>
                <p className="text-[#E8ECEF]/60">
                  Your long-form stories and campaigns will appear here
                </p>
              </div>
            )}

            {activeTab === 'media' && (
              <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                <Camera className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                <h3 className="text-white text-xl font-semibold mb-2">
                  No Media Yet
                </h3>
                <p className="text-[#E8ECEF]/60">
                  Images and moodboards you've shared will appear here
                </p>
              </div>
            )}

            {activeTab === 'mentions' && (
              <div className="space-y-4">
                {mentionsLoading && (
                  <div className="flex justify-center py-12">
                    <div className="w-8 h-8 border-4 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
                  </div>
                )}
                {!mentionsLoading && mentionedPosts.length === 0 && (
                  <div className="rounded-2xl p-12 sm:p-16 text-center bg-[#1A1D23]/40 border border-[#2D3139]/60">
                    <MessageCircle className="w-12 h-12 sm:w-14 sm:h-14 text-[#E8ECEF]/30 mx-auto mb-4 sm:mb-5" />
                    <h3 className="text-white text-xl font-semibold mb-2">
                      No Mentions Yet
                    </h3>
                    <p className="text-[#E8ECEF]/60">
                      Posts where you've been mentioned will appear here
                    </p>
                  </div>
                )}
                {!mentionsLoading && mentionedPosts.map((post) => (
                  <div key={post.id} className="rounded-2xl p-5 bg-[#1A1D23]/40 border border-[#2D3139]/60">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-sm font-medium text-violet-400">@{post.author_username}</span>
                      <span className="text-xs text-[#E8ECEF]/40">
                        {new Date(post.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}
                      </span>
                    </div>
                    {post.title && (
                      <h4 className="font-semibold text-white mb-2">{post.title}</h4>
                    )}
                    <p className="text-white/90 whitespace-pre-wrap leading-relaxed">
                      <MentionText text={post.content} mentions={post.mentions} />
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Fixed reposition bar — renders outside the cover div so it's always visible regardless of scroll */}
      {coverEditMode && (
        <div className="fixed bottom-0 left-0 right-0 z-50 bg-[#0F1419]/95 backdrop-blur-md border-t border-[#2D3139] px-4 py-3 flex items-center justify-between">
          <span className="text-sm text-[#E8ECEF]/60 hidden sm:block">Cover reposition</span>
          <div className="flex items-center gap-2 ml-auto">
            {coverSaveError && <span className="text-xs text-red-400 mr-1">{coverSaveError}</span>}
            <button
              onClick={cancelCoverEdit}
              disabled={coverSaving}
              className="px-4 py-2 text-sm text-[#E8ECEF]/70 hover:text-white border border-[#2D3139] hover:border-[#E8ECEF]/20 rounded-lg transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={() => editableChar && saveCoverEdit(editableChar.id)}
              disabled={coverSaving || !editableChar}
              className="px-5 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors disabled:opacity-50 font-medium"
            >
              {coverSaving ? 'Saving…' : 'Save position'}
            </button>
          </div>
        </div>
      )}

      {/* Fixed avatar reposition bar */}
      {avatarEditMode && (
        <div className="fixed bottom-0 left-0 right-0 z-50 bg-[#0F1419]/95 border-t border-[#2D3139] px-4 py-3">
          <div className="flex items-center justify-between max-w-[1000px] mx-auto">
            <div className="flex items-center gap-3">
              <span className="text-sm text-[#E8ECEF]/60 hidden sm:block">Avatar reposition</span>
              <div className="flex items-center gap-2">
                <span className="text-xs text-[#E8ECEF]/50">Zoom</span>
                <input
                  type="range"
                  min="1"
                  max="2"
                  step="0.01"
                  value={editAvatarScale}
                  onChange={(e) => setEditAvatarScale(parseFloat(e.target.value))}
                  className="w-28 sm:w-36 accent-emerald-500"
                />
                <span className="text-xs text-[#E8ECEF]/50 w-8">{editAvatarScale.toFixed(1)}×</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              {avatarSaveError && <span className="text-xs text-red-400 mr-1">{avatarSaveError}</span>}
              <button onClick={cancelAvatarEdit} disabled={avatarSaving}
                className="px-4 py-2 text-sm text-[#E8ECEF]/70 hover:text-white border border-[#2D3139] hover:border-[#E8ECEF]/20 rounded-lg transition-colors disabled:opacity-50">
                Cancel
              </button>
              <button onClick={saveAvatarEdit} disabled={avatarSaving}
                className="px-5 py-2 text-sm bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-colors disabled:opacity-50 font-medium">
                {avatarSaving ? 'Saving…' : 'Save position'}
              </button>
            </div>
          </div>
        </div>
      )}

      <AvatarPickerModal
        open={showAvatarPicker}
        characterId={activeChar?.id}
        onClose={() => setShowAvatarPicker(false)}
        onSaved={(avatarUrl) => {
          if (activeChar) {
            // Update just this character's avatar in local state
            setCharacters((prev) =>
              prev.map((c) => c.id === activeChar.id ? { ...c, avatar_url: avatarUrl } : c)
            );
          } else {
            // No character selected — update the user profile avatar
            setProfile((prev) => prev ? { ...prev, avatar_url: avatarUrl } : prev);
            if (authUser) setUser({ ...authUser, avatar_url: avatarUrl });
          }
          setShowAvatarPicker(false);
        }}
      />
    </div>
  );
}

function TimelineItemCard({
  item,
  profile,
}: {
  item: ProfileTimelineItem;
  profile: PublicUserProfile;
}) {
  const displayName = profile.display_name || profile.username;
  const payload = item.payload as Record<string, unknown>;

  if (item.type === 'scene') {
    const scene = payload as {
      id?: number;
      title?: string;
      description?: string;
    };
    return (
      <Link
        to={`/scenes/${scene.id}`}
        className="block glass-strong rounded-2xl p-6 hover:bg-white/5 transition-colors"
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-gray-800 overflow-hidden flex-shrink-0">
            {profile.avatar_url ? (
              <img
                src={profile.avatar_url}
                alt={displayName}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-sm font-medium text-gray-400">
                {profile.username.charAt(0).toUpperCase()}
              </div>
            )}
          </div>
          <div>
            <p className="font-medium text-white">{displayName}</p>
            <p className="text-sm text-white/50">started a new scene</p>
          </div>
          {item.realm_name && (
            <span className="ml-auto text-sm text-emerald-400 bg-emerald-600/20 px-3 py-1 rounded-full">
              {item.realm_name}
            </span>
          )}
        </div>
        <div className="bg-gray-800/50 rounded-xl p-4 border border-white/10">
          <h4 className="font-semibold text-white mb-1">
            {scene.title || 'Untitled Scene'}
          </h4>
          {scene.description && (
            <p className="text-sm text-white/70 line-clamp-2">
              {scene.description}
            </p>
          )}
        </div>
      </Link>
    );
  }

  const post = payload as {
    id?: number;
    content?: string;
    title?: string;
    content_type?: string;
    image_url?: string;
    character_name?: string;
    character_avatar_url?: string;
    mentions?: import('@/lib/types').PostMention[];
  };

  // Character-first identity: use character if available, fall back to user profile
  const postAuthorName = post.character_name || displayName;
  const postAuthorAvatar = post.character_avatar_url ?? profile.avatar_url ?? null;
  const isCharacterPost = !!post.character_name;

  return (
    <div className="glass-strong rounded-2xl p-6">
      <div className="flex items-center gap-3 mb-4">
        <Link to={`/u/${encodeURIComponent(profile.username)}`} className="flex-shrink-0">
          <div className={`w-10 h-10 overflow-hidden flex-shrink-0 ${isCharacterPost ? 'rounded-xl' : 'rounded-full'} bg-gray-800`}>
            {postAuthorAvatar ? (
              <img
                src={postAuthorAvatar}
                alt={postAuthorName}
                className="w-full h-full object-cover"
              />
            ) : (
              <div className={`w-full h-full flex items-center justify-center text-sm font-medium ${isCharacterPost ? 'text-emerald-400 bg-emerald-600/20' : 'text-gray-400'}`}>
                {postAuthorName.charAt(0).toUpperCase()}
              </div>
            )}
          </div>
        </Link>
        <div className="min-w-0 flex-1">
          <p className={`font-medium truncate ${isCharacterPost ? 'text-emerald-400' : 'text-white'}`}>
            {postAuthorName}
          </p>
          <p className="text-sm text-white/50">
            {new Date(item.created_at).toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
            })}
          </p>
        </div>
        {item.realm_name && (
          <span className="ml-auto text-sm text-emerald-400 bg-emerald-600/20 px-3 py-1 rounded-full flex-shrink-0">
            {item.realm_name}
          </span>
        )}
      </div>

      {post.title && (
        <h4 className="font-semibold text-white mb-2">{post.title}</h4>
      )}

      <p className="text-white/90 whitespace-pre-wrap leading-relaxed">
        <MentionText text={post.content ?? ''} mentions={post.mentions} />
      </p>

      {post.image_url && (
        <img
          src={post.image_url}
          alt={post.title || 'Post image'}
          className="mt-3 rounded-lg max-h-96 object-contain"
          loading="lazy"
          decoding="async"
        />
      )}

      <div className="flex items-center gap-6 mt-4 pt-4 border-t border-white/10">
        <button className="flex items-center gap-2 text-white/50 hover:text-emerald-400 transition-colors">
          <Heart className="w-4 h-4" />
          <span className="text-sm">0</span>
        </button>
        <button className="flex items-center gap-2 text-white/50 hover:text-emerald-400 transition-colors">
          <MessageCircle className="w-4 h-4" />
          <span className="text-sm">0</span>
        </button>
        <button className="flex items-center gap-2 text-white/50 hover:text-emerald-400 transition-colors ml-auto">
          <Share2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
