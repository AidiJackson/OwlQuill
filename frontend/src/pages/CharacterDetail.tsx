import { useState, useEffect, useRef } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import {
  Feather,
  RefreshCw,
  MessageSquare,
  Trash2,
  X,
  Sparkles,
  Image as ImageIcon,
  Camera,
  Crop,
  MessageCircle,
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character, ProfileTimelineItem, User } from '@/lib/types';
import CanonManager, { type OwnerStatus } from '@/components/CanonManager';
import MentionText from '@/components/MentionText';
import PostMenu from '@/components/PostMenu';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';
import type { CharacterGalleryImage } from '@/lib/types';
import ImageGrid from '@/features/images/components/ImageGrid';
import { imageKindLabel } from '@/features/images/galleryKinds';
import IdentityCanonSection from '@/features/characterCreation/components/IdentityCanonSection';
import PostComposer from '@/features/posts/components/PostComposer';
import ErrorBoundary from '@/components/ErrorBoundary';
import ConfirmDialog from '@/components/ConfirmDialog';
import CharacterDeleteCooldownNote from '@/components/CharacterDeleteCooldownNote';
import CharacterEditDetails from '@/components/CharacterEditDetails';
import CharacterImagePicker from '@/features/images/components/CharacterImagePicker';
import { hasActingCharacter, isFounder } from '@/lib/entitlements';
import { avatarTransformStyle, coverObjectPosition } from '@/lib/media';
import { useAuthStore } from '@/lib/store';

// Stories is deliberately absent (Polish Phase 5.6, PD-7): the tab was a
// static empty-state placeholder with no character-scoped Stories behind
// it. It returns when that product exists — not wired to Story Spaces to give
// the tab something to do.
type Tab = 'timeline' | 'media' | 'mentions' | 'manage';
const DEFAULT_TAB: Tab = 'timeline';

/** The public character profile — the character IS the public identity.
 *  Nothing on this page may expose the owning account. Owner tooling lives
 *  behind the owner-only Manage tab. */
export default function CharacterDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const setUser = useAuthStore((s) => s.setUser);

  const [character, setCharacter] = useState<Character | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const justCreated = searchParams.get('created') === '1';

  const [activeTab, setActiveTab] = useState<Tab>(DEFAULT_TAB);

  // Manage Character Canon modal — hosts the CanonManager (single source of identity truth)
  const [showCanonModal, setShowCanonModal] = useState(false);
  // Focus: into the dialog on open, back to the launcher on close (Phase 5.8).
  const canonDialogRef = useRef<HTMLDivElement>(null);
  const canonLauncherRef = useRef<HTMLButtonElement>(null);
  const canonWasOpenRef = useRef(false);
  useEffect(() => {
    if (showCanonModal) {
      canonWasOpenRef.current = true;
      canonDialogRef.current?.focus();
    } else if (canonWasOpenRef.current) {
      canonWasOpenRef.current = false;
      canonLauncherRef.current?.focus();
    }
  }, [showCanonModal]);

  const [galleryImages, setGalleryImages] = useState<CharacterGalleryImage[]>([]);
  const [timeline, setTimeline] = useState<ProfileTimelineItem[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(true);
  const [mentions, setMentions] = useState<ProfileTimelineItem[]>([]);
  const [mentionsLoaded, setMentionsLoaded] = useState(false);
  const [mentionsLoading, setMentionsLoading] = useState(false);
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);
  const [lbVisible, setLbVisible] = useState(false);

  // Set-avatar state

  // Mounted guard — prevents stale setState calls after navigation away
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Post composer state
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerImage, setComposerImage] = useState<CharacterGalleryImage | null>(null);

  // Cover toast state
  const [coverToast, setCoverToast] = useState('');

  // Owner image-curation picker — opened from the avatar/cover edit controls.
  const [picker, setPicker] = useState<null | {
    mode: 'avatar' | 'cover';
    repositionOnly: boolean;
    /** Gallery lightbox → picker with that image already chosen (fresh crop). */
    preselectImageId?: number;
  }>(null);

  // Remove avatar / cover (Polish Phase 5.5, PD-6) — a confirmation, not a
  // typed-name one: it clears an association and deletes no image.
  const [removeTarget, setRemoveTarget] = useState<null | 'avatar' | 'cover'>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState('');

  // Delete modal state
  // Delete character — Polish Phase 0 (M2). One dialog, honestly titled, with
  // the character's name typed to confirm. It was "Reset Character Identity"
  // with a checkbox and a second "are you sure": a softer name for a permanent
  // deletion, and two clicks that asked less of the user than typing the name.
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  const handleDeleteCharacter = async () => {
    if (!id) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await apiClient.deleteCharacter(Number(id));
    } catch (err) {
      // Only a failed DELETE is a deletion error. Nothing below this line can
      // be reported here — the character would already be gone.
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete character.');
      setDeleting(false);
      return;
    }

    // Phase 5.3: the account changed on the server (active_character cleared,
    // character_count down, cooldown set) and the auth store is what the
    // sidebar, Profile and creator gating read — so refresh it before leaving,
    // the same way every other mutation does (``setUser`` with the server's
    // account, cf. Profile/BecomeAWriter). DELETE returns no body, so the
    // account is re-read rather than merged. Not ``fetchUser``: it treats any
    // ``/me`` failure as "signed out", and a blip here must not log the user
    // out of a session that just did exactly what they asked.
    try {
      setUser(await apiClient.getMe());
    } catch {
      // The character IS deleted. A stale account snapshot until the next
      // load is the whole cost, and there is nothing the user could do about
      // it here except retry a DELETE that must not be retried — so this is
      // deliberately silent.
    }
    navigate('/characters');
  };

  const openDeleteModal = () => {
    setShowDeleteModal(true);
    setDeleteError('');
  };

  // The sidebar draws the active character's name and avatar from the auth
  // store's copy of /me. After a mutation that changes either, re-read it the
  // way Phase 5.3 does (getMe + setUser, never fetchUser). Always AFTER the
  // mutation has succeeded and always quiet: a failed re-read is a stale
  // sidebar until the next load, and must not make a finished save look
  // like a failure.
  const refreshAccountQuietly = () => {
    apiClient.getMe()
      .then((me) => { if (mountedRef.current) setUser(me); })
      .catch(() => { /* stale sidebar until next load */ });
  };

  // Edit Details (Polish Phase 5.4). The PATCH returns the owner's detail
  // projection — the same document GET returns — so it replaces the page's
  // character outright rather than being merged field by field.
  const handleDetailsSaved = (updated: Character) => {
    const renamed = character !== null && updated.name !== character.name;
    setCharacter(updated);
    if (renamed) refreshAccountQuietly();
  };

  // Remove avatar / cover (Polish Phase 5.5). The DELETE returns the owner
  // projection with the pointer cleared and that surface's framing back at
  // defaults; adopt it outright. Only the avatar reaches the sidebar.
  const handleRemoveConfirmed = async () => {
    if (!character || !removeTarget || removing) return;
    setRemoving(true);
    setRemoveError('');
    try {
      const updated = removeTarget === 'avatar'
        ? await apiClient.removeCharacterAvatar(character.id)
        : await apiClient.removeCharacterCover(character.id);
      if (!mountedRef.current) return;
      setCharacter(updated);
      setRemoveTarget(null);
      setCoverToast(removeTarget === 'avatar' ? 'Profile picture removed' : 'Cover removed');
      setTimeout(() => { if (mountedRef.current) setCoverToast(''); }, 2500);
      if (removeTarget === 'avatar') refreshAccountQuietly();
    } catch (err) {
      if (!mountedRef.current) return;
      setRemoveError(err instanceof Error ? err.message : 'Could not remove. Try again.');
    } finally {
      if (mountedRef.current) setRemoving(false);
    }
  };

  const closeDeleteModal = () => {
    if (deleting) return;
    setShowDeleteModal(false);
    setDeleteError('');
  };

  const handleUseInPost = (image: CharacterGalleryImage) => {
    setComposerImage(image);
    setComposerOpen(true);
  };

  const handleSetAsCover = async (image: CharacterGalleryImage) => {
    if (!character) return;
    try {
      // No framing is passed, and none is sent: the server keeps whatever
      // cover_position_x/y the creator has stored. Changing the picture and
      // framing it are different requests.
      const result = await apiClient.setCharacterCover(character.id, 'character', image.id);
      if (!mountedRef.current) return;
      // The response reports the EFFECTIVE persisted framing, read back off the
      // row, so it is applied here rather than the pre-call copy: the hero then
      // shows exactly what the next load will show.
      setCharacter({
        ...character,
        cover_url: result.cover_url,
        cover_position_x: result.cover_position_x,
        cover_position_y: result.cover_position_y,
      });
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

  // Gallery lightbox → "Use as profile picture" (Polish Phase 5.5). This
  // used to be its own write path: the legacy set-avatar route, no crop, the
  // previous picture's framing left on the new one, a locally invented
  // avatar_url and a silent catch. It now opens the ONE owner path — the
  // picker — with that image chosen, so it gets the same fresh crop, the same
  // canonical route and the same errors as choosing it there.
  const handleUseAsAvatar = (img: CharacterGalleryImage) => {
    closeLightbox();
    setPicker({ mode: 'avatar', repositionOnly: false, preselectImageId: img.id });
  };

  useEffect(() => {
    if (!id) return;
    const charId = Number(id);
    // A new :id on the same page element (Polish Phase 5.6). Nothing loaded
    // or opened for the previous character may survive into this one: the
    // mentions feed would otherwise keep showing the old character's posts,
    // and an owner-only overlay (canon modal, picker, remove/delete dialog)
    // would stay open over a character the viewer may not own.
    setMentions([]);
    setMentionsLoaded(false);
    setShowCanonModal(false);
    setPicker(null);
    setRemoveTarget(null);
    setShowDeleteModal(false);
    setLightboxIdx(null);
    Promise.all([
      apiClient.getCharacter(charId),
      apiClient.getMe().catch(() => null),
    ])
      .then(([char, user]) => {
        setCharacter(char);
        setCurrentUser(user);
        // Fetch gallery images (non-blocking — don't gate the page on this)
        apiClient.listCharacterImages(charId)
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

  // Lazy-load mentions when the tab is first opened. Mentions is always a
  // visible tab, so the raw selection is the right trigger here. The cleanup
  // drops a fetch the :id has moved on from, so it cannot land on the next
  // character's page.
  useEffect(() => {
    if (activeTab !== 'mentions' || !id || mentionsLoaded) return;
    let current = true;
    setMentionsLoading(true);
    apiClient.getCharacterMentions(Number(id))
      .then((items) => { if (current && mountedRef.current) setMentions(items); })
      .catch(() => { if (current && mountedRef.current) setMentions([]); })
      .finally(() => {
        if (current && mountedRef.current) {
          setMentionsLoaded(true);
          setMentionsLoading(false);
        }
      });
    return () => { current = false; };
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

  // Ownership is the SERVER's answer (Polish Phase 5.1). The detail read no
  // longer carries owner_id for a non-owner, so it is not compared here — and
  // it must not be: is_owner is the one signal, and this the one place it is
  // read into the page.
  const isOwner = character.is_owner === true;

  const coverPosX = character.cover_position_x ?? 0.5;
  const coverPosY = character.cover_position_y ?? 0.5;
  const avatarScale = character.avatar_scale ?? 1.0;
  const avatarPosX = character.avatar_position_x ?? 0.5;
  const avatarPosY = character.avatar_position_y ?? 0.5;

  const metaLine = [character.role, character.era].filter(Boolean).join(' · ');

  // The ONE owner-facing definition of the canon's state (Phase 5.7
  // addendum, B), shared with CanonManager so launcher and manager agree.
  // 'established' is visual_locked AND has_identity_canon: the readiness
  // guard's v2 path (computeGeneratorGuards) and the server's canon-content
  // requirement (has_any_canon_content) are both met. 'legacy' is a
  // pre-canon character — visual_locked with nothing in the v2 canon — which
  // the guard may admit but the server cannot ground, so it is not called
  // established. Everything else is 'unfinished'.
  const canonStatus: OwnerStatus = character.visual_locked
    ? (character.has_identity_canon ? 'established' : 'legacy')
    : 'unfinished';
  const canonStatusLabel = { established: 'Established', legacy: 'Needs attention', unfinished: 'In progress' }[canonStatus];

  const tabs: { id: Tab; label: string }[] = [
    { id: 'timeline', label: 'Timeline' },
    { id: 'media', label: 'Media' },
    { id: 'mentions', label: 'Mentions' },
    ...(isOwner ? [{ id: 'manage' as Tab, label: 'Manage' }] : []),
  ];
  // The rendered tab is derived from the tabs this viewer can see, never
  // trusted from state alone (the same rule CanonManager applies). A stale
  // selection — Manage held in state while the :id changed to a character
  // the viewer does not own, or any id no longer in the list — falls back to
  // the default tab instead of rendering a blank page or hidden content.
  const tab: Tab = tabs.some((t) => t.id === activeTab) ? activeTab : DEFAULT_TAB;

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

        {/* Owner-only cover controls — subtle, top-right of the hero. The
            backdrop above is pointer-events-none, so these re-enable clicks. */}
        {isOwner && (
          <div className="absolute top-4 right-4 sm:right-8 z-10 flex items-center gap-2 pointer-events-auto">
            <button
              onClick={() => setPicker({ mode: 'cover', repositionOnly: false })}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface/80 backdrop-blur border border-edge text-ink-2 hover:text-ink hover:border-gem transition-colors flex items-center gap-1.5 shadow-sm"
              title={character.cover_url ? 'Change cover image' : `Choose from ${character.name}'s images`}
            >
              <ImageIcon className="w-3.5 h-3.5" />
              {character.cover_url ? 'Change cover' : 'Add cover'}
            </button>
            {character.cover_url && (
              <button
                onClick={() => setPicker({ mode: 'cover', repositionOnly: true })}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface/80 backdrop-blur border border-edge text-ink-2 hover:text-ink hover:border-gem transition-colors flex items-center gap-1.5 shadow-sm"
                title="Reposition cover"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                Reposition
              </button>
            )}
          </div>
        )}

        <div className="relative max-w-[1000px] mx-auto px-4 sm:px-8">
          {/* Establishing space — pure cover, no content competes with the image */}
          <div className="h-[32vh] min-h-[190px] sm:h-[46vh] sm:min-h-[360px] lg:h-[52vh] max-h-[640px]" />

          {/* Identity composition — avatar, name and stats share one left
              rail, pulled toward the hero's left margin on wide viewports so
              the avatar anchors the lower-left corner of the hero */}
          <div className="xl:-ml-10 2xl:-ml-16">
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

            {/* Identity band — avatar lower-left, stats & controls beside it */}
            <div className="flex items-end gap-4 sm:gap-6 mt-6 sm:mt-9">
              <div className="flex-shrink-0 relative">
                {/* `relative` is load-bearing: the absolutely-positioned image
                    must use this overflow-hidden box as its containing block,
                    or a scaled avatar (avatar_scale > 1) escapes the clip and
                    spills over the stats and tabs */}
                <div className="relative w-24 h-24 sm:w-28 sm:h-28 md:w-32 md:h-32 rounded-2xl overflow-hidden border-[3px] border-app shadow-[0_0_0_1px_var(--border-md),0_8px_28px_rgba(0,0,0,0.4)] bg-surface-elevated">
                  {character.avatar_url ? (
                    <img
                      src={character.avatar_url}
                      alt={character.name}
                      className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                      style={avatarTransformStyle(avatarScale, avatarPosX, avatarPosY)}
                      onError={(e) => { e.currentTarget.style.display = 'none'; }}
                    />
                  ) : isOwner ? (
                    /* Owner, no avatar — restrained affordance, not a public-looking placeholder */
                    <button
                      onClick={() => setPicker({ mode: 'avatar', repositionOnly: false })}
                      className="w-full h-full flex flex-col items-center justify-center gap-1 bg-gem-soft/60 hover:bg-gem-soft transition-colors text-gem"
                    >
                      <Camera className="w-6 h-6" />
                      <span className="text-[10px] font-medium leading-tight text-center px-1">Choose image</span>
                    </button>
                  ) : (
                    <div className="w-full h-full flex items-center justify-center font-serif text-3xl font-semibold text-gem bg-gem-soft">
                      {character.name.charAt(0).toUpperCase()}
                    </div>
                  )}
                </div>
                {/* Owner-only avatar controls beside the avatar corner. Two
                    distinct acts: Change picks another picture; Crop re-frames
                    the current one, opening on its stored crop. */}
                {isOwner && character.avatar_url && (
                  <div className="absolute -bottom-1 -right-1 flex items-center gap-1">
                    <button
                      onClick={() => setPicker({ mode: 'avatar', repositionOnly: true })}
                      className="w-8 h-8 rounded-full bg-surface border border-edge-md shadow-md flex items-center justify-center text-ink-2 hover:text-ink hover:border-gem transition-colors"
                      aria-label="Crop profile picture"
                      title="Crop profile picture"
                    >
                      <Crop className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => setPicker({ mode: 'avatar', repositionOnly: false })}
                      className="w-8 h-8 rounded-full bg-surface border border-edge-md shadow-md flex items-center justify-center text-ink-2 hover:text-ink hover:border-gem transition-colors"
                      aria-label="Change profile picture"
                      title="Change profile picture"
                    >
                      <Camera className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>

              {/* Stats + controls */}
              <div className="flex-1 min-w-0 pb-1 sm:pb-2">
                <div className="flex items-end justify-between gap-3 flex-wrap">
                  <div className="flex flex-wrap items-center gap-5 sm:gap-8 min-w-0">
                    <span className="text-center">
                      <span className="block font-serif text-xl sm:text-2xl font-medium text-ink leading-tight">{timeline.length}</span>
                      <span className="block font-mono text-[10px] uppercase tracking-[0.08em] text-ink-3">Posts</span>
                    </span>
                    {/* Follower stat intentionally omitted: Follow is not yet a
                        real, persistent system, so there is no stored count to
                        show. Re-introduce here alongside the Follow control when
                        the backend lands — see the action-row insertion point. */}
                  </div>

                  {!isOwner && (
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {/* Messaging is character-to-character — only viewers who
                          own a character can open a conversation. */}
                      {hasActingCharacter(currentUser) && (
                        <button
                          className="bg-surface-elevated border border-edge text-ink-2 hover:text-ink hover:border-edge-md px-4 py-2 rounded-lg flex items-center gap-2 text-sm font-medium transition-all"
                          onClick={() => navigate(`/messages/new?characterId=${id}`)}
                        >
                          <MessageSquare className="w-4 h-4 flex-shrink-0" />
                          Message
                        </button>
                      )}
                      {/* Follow control insertion point. Deliberately not
                          rendered until Follow is functional end-to-end
                          (persistence + API + notifications). A dead stub that
                          only flips local text is worse than its absence. */}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Tabs — the hero's lower boundary */}
          <div className="flex items-center gap-1 mt-6 sm:mt-8 border-b border-edge overflow-x-auto hide-scrollbar">
            {tabs.map((t) => (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id)}
                className={`px-3 sm:px-4 py-2.5 -mb-px text-xs sm:text-sm font-medium whitespace-nowrap border-b-2 transition-colors duration-200 ${
                  tab === t.id
                    ? 'border-gem text-ink'
                    : 'border-transparent text-ink-3 hover:text-ink-2'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* === CONTENT === */}
      <div className="max-w-[1000px] mx-auto px-4 sm:px-8 py-8 pb-16">

        {/* Bio — the character's own introduction, shown above every public tab */}
        {tab !== 'manage' && (character.short_bio || character.long_bio || character.tags) && (
          <div className="mb-10 max-w-3xl space-y-5">
            {character.short_bio && (
              <p className="font-serif text-lg sm:text-xl leading-[1.6] text-ink">{character.short_bio}</p>
            )}
            {character.long_bio && (
              <p className="fic-read fic-ooc whitespace-pre-wrap">{character.long_bio}</p>
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
        {tab === 'timeline' && (
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
                <PostCard
                  key={timelineKey(item, idx)}
                  item={item}
                  character={character}
                  viewer={currentUser}
                  onDeleted={(postId) => {
                    setTimeline((prev) => prev.filter((i) => timelinePostId(i) !== postId));
                    setMentions((prev) => prev.filter((i) => timelinePostId(i) !== postId));
                  }}
                />
              ))
            )}
          </div>
        )}

        {/* Media */}
        {tab === 'media' && (
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
        {tab === 'mentions' && (
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
              <PostCard
                key={timelineKey(item, idx)}
                item={item}
                character={null}
                viewer={currentUser}
                onDeleted={(postId) => {
                  setMentions((prev) => prev.filter((i) => timelinePostId(i) !== postId));
                  setTimeline((prev) => prev.filter((i) => timelinePostId(i) !== postId));
                }}
              />
            ))}
          </div>
        )}

        {/* Manage — owner only. The character's backstage. */}
        {tab === 'manage' && isOwner && (
          <div className="space-y-6 max-w-3xl">
            {/* Profile details + visibility (Polish Phase 5.4). Owner-only by
                the same is_owner gate as the rest of this tab. */}
            <CharacterEditDetails character={character} onSaved={handleDetailsSaved} />

            {/* Avatar & cover (Polish Phase 5.5). The hero's corner buttons
                remain; this is the discoverable, labelled version of the same
                controls plus Remove. Every button opens the ONE picker or the
                ONE remove dialog — no second write path. */}
            <section
              aria-labelledby="manage-media-heading"
              className="rounded-2xl p-5 bg-surface border border-edge space-y-4"
            >
              <h3 id="manage-media-heading" className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3">
                Profile picture &amp; cover
              </h3>

              <div className="flex flex-wrap items-start gap-4">
                <div
                  className="w-20 h-20 rounded-xl overflow-hidden border border-edge-md bg-surface-elevated flex-shrink-0"
                  data-testid="manage-avatar-preview"
                >
                  {character.avatar_url ? (
                    <img
                      src={character.avatar_url}
                      alt={`${character.name}'s profile picture`}
                      className="w-full h-full object-cover"
                      style={avatarTransformStyle(avatarScale, avatarPosX, avatarPosY)}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center font-serif text-2xl font-semibold text-gem bg-gem-soft" aria-label="No profile picture">
                      {character.name.charAt(0).toUpperCase()}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  <p className="text-sm font-medium text-ink">Profile picture</p>
                  <p className="text-xs text-ink-3">
                    {character.avatar_url
                      ? 'Shown wherever this character appears.'
                      : 'Choose one of this character\u2019s images — canon face cards and uploads included.'}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => setPicker({ mode: 'avatar', repositionOnly: false })} className="btn btn-secondary text-xs">
                      {character.avatar_url ? 'Change picture' : 'Choose picture'}
                    </button>
                    {character.avatar_url && (
                      <>
                        <button type="button" onClick={() => setPicker({ mode: 'avatar', repositionOnly: true })} className="btn btn-secondary text-xs">
                          Crop
                        </button>
                        <button type="button" onClick={() => { setRemoveError(''); setRemoveTarget('avatar'); }} className="btn btn-secondary text-xs text-red-400 hover:text-red-300">
                          Remove picture
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-start gap-4">
                <div
                  className="w-32 h-16 rounded-xl overflow-hidden border border-edge-md bg-surface-elevated flex-shrink-0"
                  data-testid="manage-cover-preview"
                >
                  {character.cover_url ? (
                    <img
                      src={character.cover_url}
                      alt={`${character.name}'s cover`}
                      className="w-full h-full object-cover"
                      style={{ objectPosition: coverObjectPosition(coverPosX, coverPosY) }}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-[10px] text-ink-3" aria-label="No cover">
                      No cover
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  <p className="text-sm font-medium text-ink">Cover</p>
                  <p className="text-xs text-ink-3">The banner across the top of the profile.</p>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" onClick={() => setPicker({ mode: 'cover', repositionOnly: false })} className="btn btn-secondary text-xs">
                      {character.cover_url ? 'Change cover' : 'Choose cover'}
                    </button>
                    {character.cover_url && (
                      <>
                        <button type="button" onClick={() => setPicker({ mode: 'cover', repositionOnly: true })} className="btn btn-secondary text-xs">
                          Reposition
                        </button>
                        <button type="button" onClick={() => { setRemoveError(''); setRemoveTarget('cover'); }} className="btn btn-secondary text-xs text-red-400 hover:text-red-300">
                          Remove cover
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            </section>

            {/* Character images (Polish Phase 5.6). One door to the Image
                Library, opened on this character. This card was "Character
                Tools" — a development-era grab-bag holding this button, the
                canon launcher and a note about avatar-setting that the card
                above has since made redundant. */}
            <section
              aria-labelledby="manage-images-heading"
              className="rounded-2xl p-5 bg-surface border border-edge space-y-3"
            >
              <h3 id="manage-images-heading" className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3">
                Character images
              </h3>
              <p className="text-xs text-ink-3">
                Generate new images of {character.name} and curate the ones you already have.
                Images of {character.name} appear on the Media tab.
              </p>
              <button
                type="button"
                onClick={() => navigate(`/images?characterId=${character.id}`)}
                className="btn btn-secondary text-xs flex items-center gap-2"
              >
                <ImageIcon className="w-3.5 h-3.5" />
                Generate images
              </button>
            </section>

            {/* Identity Canon (Polish Phase 5.6): the launcher and the
                read-only canon cards were two unrelated blocks; they are one
                subject, so they share one card. Polish Phase 0 (M3): the
                launcher is always offered to the owner. It was gated on
                visual_locked, which left a draft character — the state every
                new character spends its first days in — with no way to reach
                its own body canon, marks or face description. The server
                never required a lock. The Canon Manager's own contents are
                Phase 5.7's. */}
            <section
              aria-labelledby="manage-canon-heading"
              className="rounded-2xl p-5 bg-surface border border-edge space-y-4"
            >
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <h3 id="manage-canon-heading" className="font-mono text-[11px] uppercase tracking-[0.1em] text-ink-3">
                    Identity Canon
                  </h3>
                  {/* Same word the manager shows, from the same definition
                      (canonStatus above). */}
                  <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium ${
                    canonStatus === 'established' ? 'bg-gem-soft text-gem' : 'bg-surface-overlay text-ink-3'
                  }`}>
                    {canonStatusLabel}
                  </span>
                </div>
                <p className="text-xs text-ink-3">
                  The reference images and details that keep {character.name} looking like
                  themselves in every new image.
                </p>
                <button
                  ref={canonLauncherRef}
                  type="button"
                  onClick={() => setShowCanonModal(true)}
                  className="btn btn-secondary text-xs flex items-center gap-2"
                >
                  <Sparkles className="w-3.5 h-3.5" aria-hidden />
                  Manage Character Canon
                </button>
              </div>
              {/* v2 canon pack cards (stored in canon JSON, not the CharacterImage
                  library). Renders nothing until something has been generated. */}
              <ErrorBoundary>
                <IdentityCanonSection characterId={character.id} embedded />
              </ErrorBoundary>
            </section>

            {/* Delete — last, and visibly apart from everything above. The
                heading was "Danger Zone": a hosting-dashboard phrase, not what
                the section does. */}
            <section
              aria-labelledby="manage-delete-heading"
              className="rounded-2xl p-5 bg-red-950/20 border border-red-900/30 space-y-2"
            >
              <h3 id="manage-delete-heading" className="text-sm font-semibold text-red-400">Delete character</h3>
              <p className="text-xs text-ink-3">
                Permanently removes {character.name}. There is no undo.
              </p>
              <button
                type="button"
                className="text-xs text-red-500 hover:text-red-400 transition-colors flex items-center gap-1"
                onClick={openDeleteModal}
              >
                <Trash2 className="w-3 h-3" />
                Delete character
              </button>
            </section>
          </div>
        )}
      </div>

      {/* Post composer */}
      {/* Post composer. Scoped to the character whose page this is: the image
          came from their gallery, and the post is authored by them. */}
      {character && (
        <PostComposer
          open={composerOpen}
          onClose={() => { setComposerOpen(false); setComposerImage(null); }}
          preloadedImage={composerImage}
          characterId={character.id}
          characterName={character.name}
        />
      )}

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
          onKeyDown={(e) => { if (e.key === 'Escape') closeLightbox(); }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Image preview"
            className={`relative max-w-md w-full mx-4 transition-all duration-200 ease-out ${lbVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'}`}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              autoFocus
              aria-label="Close preview"
              className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 z-10"
              onClick={closeLightbox}
            >
              <X className="w-4 h-4" aria-hidden />
            </button>
            <img
              src={resolveImageUrl(galleryImages[lightboxIdx].url)}
              alt={imageKindLabel(galleryImages[lightboxIdx].kind)}
              className="w-full rounded-xl"
            />
            <div className="flex items-center justify-between mt-2">
              <p className="font-mono text-xs text-white/60">
                {imageKindLabel(galleryImages[lightboxIdx].kind)}
              </p>
              {isOwner && (
                <button
                  type="button"
                  className="text-xs px-3 py-1.5 rounded-lg bg-gem hover:bg-gem/90 text-gem-ink font-semibold transition-colors flex items-center gap-1.5"
                  onClick={() => handleUseAsAvatar(galleryImages[lightboxIdx!])}
                >
                  <Camera className="w-3 h-3" />
                  Use as profile picture
                </button>
              )}
            </div>
          </div>
        </div>
      )}
      </ErrorBoundary>

      {/* Manage Character Canon modal — single source of identity truth
          (CanonManager). Gated on isOwner like the picker: the shell must
          not outlive ownership either. */}
      {showCanonModal && isOwner && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
          onKeyDown={(e) => { if (e.key === 'Escape') setShowCanonModal(false); }}
        >
          <div
            ref={canonDialogRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-labelledby="canon-modal-title"
            className="bg-surface-overlay border border-edge-md rounded-2xl w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh] focus:outline-none"
          >

            {/* Header */}
            <div className="flex items-center justify-between gap-3 px-6 pt-6 pb-4 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-gem-soft border border-gem/25 flex items-center justify-center flex-shrink-0">
                  <Sparkles className="w-4 h-4 text-gem" aria-hidden />
                </div>
                <h2 id="canon-modal-title" className="text-sm font-semibold text-ink">Manage Character Canon</h2>
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
                isFounder={isFounder(currentUser)}
                characterName={character.name}
                ownerStatus={canonStatus}
                onEstablished={() => {
                  // The lock routes mirrored visual_locked onto the character;
                  // re-read it (a READ, no provider) so the launcher badge and
                  // the generator's readiness agree with the manager.
                  apiClient.getCharacter(character.id)
                    .then((fresh) => { if (mountedRef.current) setCharacter(fresh); })
                    .catch(() => { /* badge settles on next load */ });
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Delete character — permanent, name typed to confirm (Polish Phase 0, M2) */}
      <ConfirmDialog
        open={showDeleteModal}
        danger
        title="Delete character"
        confirmLabel="Delete character"
        confirmText={character.name}
        busy={deleting}
        error={deleteError || null}
        onConfirm={handleDeleteCharacter}
        onCancel={closeDeleteModal}
      >
        {/* Every line below states what the server actually does (PD-8).
            Images are NOT deleted — the association is dropped and the asset
            stays in the account library (Character.images has no delete
            cascade); the old copy said the opposite. Conversations cascade for
            both characters. Posts and comments keep the account's authorship
            with the character detached. */}
        <p>
          This <strong>permanently deletes</strong> <strong>{character.name}</strong>. There is no
          undo.
        </p>
        <ul className="list-disc list-inside text-ink-3 space-y-1">
          <li>Their profile, bios and identity canon are removed.</li>
          <li>
            Generated images are <strong>not</strong> deleted — they stay in your image library,
            no longer linked to {character.name}.
          </li>
          <li>
            Every conversation {character.name} was part of is removed, with all its messages —
            for the other character too.
          </li>
          <li>Posts and comments {character.name} wrote stay up, but no longer carry their name.</li>
        </ul>
        <CharacterDeleteCooldownNote user={currentUser} />
      </ConfirmDialog>

      {/* Owner image-curation picker — avatar / cover, scoped to this character */}
      {picker && isOwner && (
        <CharacterImagePicker
          characterId={character.id}
          characterName={character.name}
          mode={picker.mode}
          repositionOnly={picker.repositionOnly}
          preselectImageId={picker.preselectImageId}
          currentImageUrl={picker.mode === 'cover' ? character.cover_url : character.avatar_url}
          initialPosX={picker.mode === 'cover' ? coverPosX : avatarPosX}
          initialPosY={picker.mode === 'cover' ? coverPosY : avatarPosY}
          initialScale={picker.mode === 'avatar' ? avatarScale : undefined}
          onCancel={() => setPicker(null)}
          onConfirmed={(result) => {
            // Optimistic, and deliberately limited to the IMAGE. The picker
            // knows which url it set; it does not own the framing, so nothing
            // here manufactures a cover_position_* value.
            setCharacter({
              ...character,
              ...(result.avatar_url ? { avatar_url: result.avatar_url } : {}),
              ...(result.cover_url ? { cover_url: result.cover_url } : {}),
            });
            setPicker(null);
            setCoverToast(picker.mode === 'cover' ? 'Cover updated' : 'Profile picture updated');
            setTimeout(() => { if (mountedRef.current) setCoverToast(''); }, 2500);

            // Then let the SERVER settle it. Repositioning wrote
            // cover_position_x/y through PATCH, but this component's copy of the
            // character still held the pre-drag values, so the hero re-rendered
            // from stale state and the cover visibly snapped back to its old
            // framing the instant the creator pressed Save — the save had
            // succeeded, and the page said otherwise.
            //
            // A refetch rather than a merge, because the server is the only
            // thing that knows what was actually persisted (the cover route may
            // preserve rather than overwrite framing), and manufacturing the
            // value here would put a second, quietly diverging copy of that rule
            // in the UI.
            //
            // This is a READ. It cannot double-save and cannot race the save: the
            // picker has already awaited its own writes before calling this.
            apiClient.getCharacter(character.id)
              .then((fresh) => { if (mountedRef.current) setCharacter(fresh); })
              .catch(() => { /* keep the optimistic image; framing settles on next load */ });
            // The sidebar shows the active character's avatar (Phase 5.5).
            if (picker.mode === 'avatar') refreshAccountQuietly();
          }}
        />
      )}

      {/* Remove avatar / cover — an association, not an image (Phase 5.5) */}
      <ConfirmDialog
        open={removeTarget !== null}
        danger
        title={removeTarget === 'cover' ? 'Remove cover' : 'Remove profile picture'}
        confirmLabel={removeTarget === 'cover' ? 'Remove cover' : 'Remove profile picture'}
        busy={removing}
        error={removeError || null}
        onConfirm={handleRemoveConfirmed}
        onCancel={() => { if (!removing) { setRemoveTarget(null); setRemoveError(''); } }}
      >
        <p>
          {removeTarget === 'cover'
            ? <>{character.name}&apos;s profile will show no cover until you choose another.</>
            : <>{character.name}&apos;s profile will show their initial until you choose another picture.</>}
        </p>
        <p className="text-ink-3">
          The image itself is not deleted — it stays in your image library.
        </p>
      </ConfirmDialog>
    </div>
  );
}

/** The post id a timeline item carries, when it is a post. */
function timelinePostId(item: ProfileTimelineItem): number | undefined {
  const id = (item.payload as { id?: unknown }).id;
  return item.type === 'post' && typeof id === 'number' ? id : undefined;
}

/** A stable React key: the post id, so removing one entry cannot leave its
 *  neighbours rendering each other's state. Index only as a last resort. */
function timelineKey(item: ProfileTimelineItem, idx: number): string {
  const id = timelinePostId(item);
  return id !== undefined ? `post-${id}` : `${item.type}-idx-${idx}`;
}

/** Timeline/mention post card. Attribution is always the authoring CHARACTER
 *  (from the post payload) — never an account. `character` is the profile
 *  being viewed; when the payload has no character of its own (legacy), the
 *  profile character is used for timeline items and "Wanderer" for mentions. */
function PostCard({
  item,
  character,
  viewer,
  onDeleted,
}: {
  item: ProfileTimelineItem;
  character: Character | null;
  viewer: User | null;
  onDeleted: (postId: number) => void;
}) {
  const post = item.payload as {
    id?: number;
    title?: string;
    content?: string;
    image_url?: string;
    character_name?: string;
    character_avatar_url?: string;
    mentions?: import('@/lib/types').PostMention[];
    author_user_id?: number | null;
    comment_count?: number;
  };
  const postId = timelinePostId(item);
  // The serializer keeps `author_user_id` for the author alone, so a match is
  // authorship; admins mirror the Commons/Realm rule. The server re-checks.
  const canDelete =
    postId !== undefined &&
    viewer !== null &&
    ((post.author_user_id != null && post.author_user_id === viewer.id) || !!viewer.is_admin);

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
        {canDelete && postId !== undefined && (
          <PostMenu postId={postId} commentCount={post.comment_count} onDeleted={onDeleted} />
        )}
      </div>
      {post.title && (
        <h3 className="fic-title text-lg font-medium mb-1.5">{post.title}</h3>
      )}
      <p className="fic-read whitespace-pre-wrap">
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
