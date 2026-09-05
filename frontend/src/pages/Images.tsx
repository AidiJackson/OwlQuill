import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Image, X, Check, Trash2, Flag, Sparkles } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage, Character, User } from '@/lib/types';
import ErrorBoundary from '@/components/ErrorBoundary';
import SceneGeneratorPanel from '@/features/images/components/SceneGeneratorPanel';
import { ficDebug } from '@/lib/ficDebug';
import { useObjectPositionDrag } from '@/features/images/useObjectPositionDrag';
import { GALLERY_KINDS, GALLERY_KIND_LABELS, isGalleryKind } from '@/features/images/galleryKinds';

type LbMode = 'view' | 'coverEdit' | 'avatarEdit';

// A character filter is either a specific owned character or the deliberate
// All Characters view (founders/multi-character owners only).
type CharFilter = number | 'all';

export default function Images() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const onboardingCharId = searchParams.get('characterId') ? Number(searchParams.get('characterId')) : undefined;
  const onboardingPrompt = searchParams.get('prompt') ?? undefined;

  // Library
  const [images, setImages] = useState<LibraryImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [myCharacters, setMyCharacters] = useState<Character[]>([]);
  const [currentUser, setCurrentUser] = useState<User | null>(null);

  // Character-first library controls
  const [charFilter, setCharFilter] = useState<CharFilter | null>(null); // null until resolved
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');
  const [kindFilter, setKindFilter] = useState<string>('all'); // 'all' | one of GALLERY_KINDS

  // Founders / multi-character owners may deliberately choose All Characters.
  const isFounder = !!(currentUser?.is_admin || currentUser?.is_seeder);
  const canSeeAllCharacters = isFounder || myCharacters.length > 1;

  type QuotaStatus = {
    used: number;
    limit: number | null;
    remaining: number | null;
    unlimited: boolean;
    reset_at?: string | null;
  };
  const [quota, setQuota] = useState<QuotaStatus | null>(null);

  // Lightbox
  const [lightboxImage, setLightboxImage] = useState<LibraryImage | null>(null);
  const [lbVisible, setLbVisible] = useState(false);
  const [lbMode, setLbMode] = useState<LbMode>('view');

  // Character assignment selector
  const [assignCharId, setAssignCharId] = useState<number | null>(null);

  // Cover editor (drag-to-position only, no zoom) and avatar editor (drag +
  // zoom). Both use the shared hook — the same behaviour the character profile
  // picker uses, so the two surfaces can never drift apart.
  const coverDrag = useObjectPositionDrag({ mode: 'objectPosition', debugLabel: 'Images:coverDrag' });
  const { posX: coverPosX, posY: coverPosY, posXRef: coverPosXRef, posYRef: coverPosYRef } = coverDrag;
  const [coverSaving, setCoverSaving] = useState(false);
  const [coverSaveErr, setCoverSaveErr] = useState('');
  const [coverSaveDone, setCoverSaveDone] = useState(false);

  const avatarDrag = useObjectPositionDrag({ mode: 'scaleTranslate', debugLabel: 'Images:avatarDrag' });
  const {
    posX: avatarPosX, posY: avatarPosY, scale: avatarScale,
    posXRef: avatarPosXRef, posYRef: avatarPosYRef, scaleRef: avatarScaleRef,
  } = avatarDrag;
  const [avatarSaving, setAvatarSaving] = useState(false);
  const [avatarSaveErr, setAvatarSaveErr] = useState('');
  const [avatarSaveDone, setAvatarSaveDone] = useState(false);

  // Delete state
  const [deletingImage, setDeletingImage] = useState(false);
  const [deleteError, setDeleteError] = useState('');

  // Report state
  const [reportStep, setReportStep] = useState<'idle' | 'form' | 'done'>('idle');
  const [reportReason, setReportReason] = useState('');
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportError, setReportError] = useState('');

  // Refs
  const mountedRef = useRef(true);
  const lbCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coverFrameRef = coverDrag.frameRef;
  const avatarFrameRef = avatarDrag.frameRef;

  useEffect(() => {
    mountedRef.current = true;
    ficDebug.mount('Images');
    return () => {
      mountedRef.current = false;
      if (lbCloseTimerRef.current) {
        clearTimeout(lbCloseTimerRef.current);
        lbCloseTimerRef.current = null;
      }
      ficDebug.unmount('Images');
    };
  }, []);

  // Lightbox visibility transition
  useEffect(() => {
    if (!lightboxImage) { setLbVisible(false); return; }
    const id = requestAnimationFrame(() => { if (mountedRef.current) setLbVisible(true); });
    return () => cancelAnimationFrame(id);
  }, [lightboxImage]); // eslint-disable-line react-hooks/exhaustive-deps

  const openLightbox = (image: LibraryImage) => {
    if (lbCloseTimerRef.current) {
      clearTimeout(lbCloseTimerRef.current);
      lbCloseTimerRef.current = null;
      ficDebug.log('Images:lightbox — cancelled stale close timer on re-open');
    }
    ficDebug.modalOpen('Images:lightbox');
    setLightboxImage(image);
    setLbMode('view');
    setDeleteError('');
    setReportStep('idle');
    setReportReason('');
    setReportError('');
  };

  const closeLightbox = () => {
    ficDebug.modalClose('Images:lightbox');
    coverDrag.cleanupDrag();
    avatarDrag.cleanupDrag();
    setLbVisible(false);
    if (lbCloseTimerRef.current) clearTimeout(lbCloseTimerRef.current);
    lbCloseTimerRef.current = setTimeout(() => {
      lbCloseTimerRef.current = null;
      if (!mountedRef.current) return;
      setLightboxImage(null);
      setLbMode('view');
      setAssignCharId(null);
      setCoverSaveErr('');
      setCoverSaveDone(false);
      setAvatarSaveErr('');
      setAvatarSaveDone(false);
      setDeleteError('');
      setReportStep('idle');
      setReportReason('');
      setReportError('');
    }, 200);
  };

  const enterCoverEdit = () => {
    // Cover/avatar assignment always targets the image's OWN character. There is
    // deliberately no myCharacters[0] fallback: an image with no character_id
    // must not be silently pushed onto an unrelated character.
    const charId = lightboxImage?.character_id ?? null;
    setAssignCharId(charId);
    coverDrag.reset(0.5, 0.5, 1.0);
    setCoverSaveErr(charId === null ? "This image isn't linked to a character." : '');
    setCoverSaveDone(false);
    setLbMode('coverEdit');
  };

  const enterAvatarEdit = () => {
    const charId = lightboxImage?.character_id ?? null;
    setAssignCharId(charId);
    avatarDrag.reset(0.5, 0.5, 1.0);
    setAvatarSaveErr(charId === null ? "This image isn't linked to a character." : '');
    setAvatarSaveDone(false);
    setLbMode('avatarEdit');
  };

  // Drag-to-reposition comes from the shared hook (see useObjectPositionDrag):
  //   cover  → object-position pan, works at scale 1
  //   avatar → scale+translate pan, only meaningful once zoomed in
  const startCoverDrag = coverDrag.startDrag;
  const startAvatarDrag = avatarDrag.startDrag;

  const handleSaveCover = async () => {
    if (!lightboxImage || assignCharId === null) return;
    setCoverSaving(true);
    setCoverSaveErr('');
    try {
      await apiClient.setCharacterCover(assignCharId, 'character', lightboxImage.id, coverPosYRef.current, coverPosXRef.current);
      await apiClient.updateCharacter(assignCharId, { cover_scale: 1.0 });
      if (!mountedRef.current) return;
      setCoverSaveDone(true);
      setTimeout(() => { if (mountedRef.current) closeLightbox(); }, 1200);
    } catch (err) {
      if (!mountedRef.current) return;
      setCoverSaveErr(err instanceof Error ? err.message : 'Failed to set cover.');
    } finally {
      if (mountedRef.current) setCoverSaving(false);
    }
  };

  const handleSaveAvatar = async () => {
    if (!lightboxImage || assignCharId === null) return;
    setAvatarSaving(true);
    setAvatarSaveErr('');
    try {
      await apiClient.setCharacterAvatar(assignCharId, 'character', lightboxImage.id);
      await apiClient.updateCharacter(assignCharId, {
        avatar_position_x: avatarPosXRef.current,
        avatar_position_y: avatarPosYRef.current,
        avatar_scale: avatarScaleRef.current,
      });
      if (!mountedRef.current) return;
      setAvatarSaveDone(true);
      setTimeout(() => { if (mountedRef.current) closeLightbox(); }, 1200);
    } catch (err) {
      if (!mountedRef.current) return;
      setAvatarSaveErr(err instanceof Error ? err.message : 'Failed to set avatar.');
    } finally {
      if (mountedRef.current) setAvatarSaving(false);
    }
  };

  const handleDeleteImage = async () => {
    if (!lightboxImage) return;
    setDeletingImage(true);
    setDeleteError('');
    try {
      // An asset with no character has no character-scoped URL to delete
      // through — the account-scoped archive authorises on ownership alone and
      // reaches both kinds. The character-scoped call is kept for associated
      // assets so that route stays exercised and stays association-scoped.
      if (lightboxImage.character_id === null) {
        await apiClient.archiveMyCharacterImage(lightboxImage.id);
      } else {
        await apiClient.deleteCharacterImage(lightboxImage.character_id, lightboxImage.id);
      }
      if (!mountedRef.current) return;
      setImages((prev) => prev.filter((img) => img.id !== lightboxImage.id));
      closeLightbox();
    } catch (err) {
      if (!mountedRef.current) return;
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete image.');
    } finally {
      if (mountedRef.current) setDeletingImage(false);
    }
  };

  const handleSubmitReport = async () => {
    if (!lightboxImage || !reportReason.trim()) return;
    setReportSubmitting(true);
    setReportError('');
    try {
      await apiClient.submitReport('image', String(lightboxImage.id), reportReason.trim());
      if (!mountedRef.current) return;
      setReportStep('done');
    } catch (err) {
      if (!mountedRef.current) return;
      setReportError(err instanceof Error ? err.message : 'Failed to submit report.');
    } finally {
      if (mountedRef.current) setReportSubmitting(false);
    }
  };

  // Bootstrap: characters + current user + quota. The image load is driven
  // separately by the resolved character filter so it can re-run on change.
  useEffect(() => {
    Promise.all([
      apiClient.getCharacters().catch(() => [] as Character[]),
      apiClient.getMe().catch(() => null),
    ]).then(([chars, user]) => {
      if (!mountedRef.current) return;
      setMyCharacters(chars);
      setCurrentUser(user);
      // Resolve the default character filter, character-first:
      //   URL param → active character → sole owned character → All (founders).
      // Never default to All when a specific character is in context.
      const founder = !!(user?.is_admin || user?.is_seeder);
      let resolved: CharFilter;
      if (onboardingCharId != null && chars.some((c) => c.id === onboardingCharId)) {
        resolved = onboardingCharId;
      } else if (user?.active_character?.id && chars.some((c) => c.id === user.active_character!.id)) {
        resolved = user.active_character.id;
      } else if (chars.length === 1) {
        resolved = chars[0].id;
      } else if (chars.length > 1 && !founder) {
        resolved = chars[0].id; // ordinary multi-owner lands on their first character, not a wall
      } else {
        resolved = 'all';
      }
      setCharFilter(resolved);
    });

    apiClient
      .getImageQuota()
      .then((q) => { if (mountedRef.current) setQuota(q); })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load images whenever the character filter / sort changes. Character
  // scoping happens on the SERVER — we never pull the whole archive to filter
  // in the browser.
  useEffect(() => {
    if (charFilter === null) return; // not resolved yet
    setLoading(true);
    setLoadError('');
    const opts = {
      sort: sortOrder,
      ...(charFilter !== 'all' ? { characterId: charFilter } : {}),
    };
    apiClient
      .listMyCharacterImages(opts)
      .then((imgs) => {
        if (!mountedRef.current) return;
        // Keep only shareable library kinds — anchors/face-refs/identity packs
        // are working references, never surfaced here.
        setImages(imgs.filter((img) => isGalleryKind(img.kind)));
      })
      .catch((err) => { if (mountedRef.current) setLoadError(err instanceof Error ? err.message : 'Failed to load'); })
      .finally(() => { if (mountedRef.current) setLoading(false); });
  }, [charFilter, sortOrder]);

  // ── Derived view state ───────────────────────────────────────────────
  const charById = new Map(myCharacters.map((c) => [c.id, c]));
  const selectedChar = typeof charFilter === 'number' ? charById.get(charFilter) ?? null : null;

  // Kind filter is applied client-side over the already-scoped result set.
  const displayedImages = kindFilter === 'all'
    ? images
    : images.filter((img) => img.kind === kindFilter);

  // In All Characters mode, group by character so the wall stays organised.
  // Characterless/admin assets get their own clearly-separated section rather
  // than being silently mixed in.
  const isAllMode = charFilter === 'all';
  const groupedImages: { char: Character | null; images: LibraryImage[] }[] = (() => {
    if (!isAllMode) return [];
    const byChar = new Map<number, LibraryImage[]>();
    const orphans: LibraryImage[] = [];
    for (const img of displayedImages) {
      // character_id is null once the character is deleted (Phase 4C). It was
      // already possible for the lookup to miss — an admin asset on a character
      // this account does not own — so both cases land in the same section.
      const cid = img.character_id;
      const c = cid === null ? undefined : charById.get(cid);
      if (!c || cid === null) { orphans.push(img); continue; }
      if (!byChar.has(cid)) byChar.set(cid, []);
      byChar.get(cid)!.push(img);
    }
    const groups: { char: Character | null; images: LibraryImage[] }[] = myCharacters
      .filter((c) => byChar.has(c.id))
      .map((c) => ({ char: c, images: byChar.get(c.id)! }));
    if (orphans.length) groups.push({ char: null, images: orphans });
    return groups;
  })();

  /** Shared card renderer — one place, used by both single and grouped views. */
  const renderCard = (img: LibraryImage) => (
    <button
      key={img.id}
      className="rounded-lg border border-edge overflow-hidden bg-surface hover:border-edge-md transition-colors cursor-pointer text-left"
      onClick={() => openLightbox(img)}
      title="Click to view or use this image"
    >
      <img
        src={img.url}
        alt={img.prompt_summary || 'Generated image'}
        className="w-full aspect-[2/3] object-cover"
        loading="lazy"
        decoding="async"
      />
      <div className="px-2 py-1.5 flex items-center gap-1.5">
        {/* Role badge — real stored kind, not inferred */}
        {img.kind !== 'generated' && (
          <span className="text-[10px] font-medium uppercase tracking-wide text-gem/80 shrink-0">
            {isGalleryKind(img.kind) ? GALLERY_KIND_LABELS[img.kind] : img.kind}
          </span>
        )}
        {img.prompt_summary && (
          <p className="text-xs text-ink-2 truncate">{img.prompt_summary}</p>
        )}
      </div>
    </button>
  );

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-edge bg-surface">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link to="/" className="text-ink-2 hover:text-ink transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-ink-2">Image Library</span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
        {/* Onboarding nudge — shown when arriving from character creation */}
        {onboardingCharId != null && (
          <div className="bg-gem-soft border border-gem/50 rounded-lg px-4 py-3 space-y-1">
            <p className="text-sm font-semibold text-gem">
              {myCharacters.find((c) => c.id === onboardingCharId)?.name
                ? `Bring ${myCharacters.find((c) => c.id === onboardingCharId)!.name} to life`
                : 'Bring your character to life'}
            </p>
            <p className="text-xs text-ink-2">
              Generate your first image, then set it as a profile picture or cover.
            </p>
          </div>
        )}

        {/* Admin Creator entry point — founder/seeder only, and deliberately a
            plain labelled link rather than a polished promo: it is an internal
            A/B of two creation workflows, not a feature being sold. The Image
            Generator below is unchanged and remains the normal path. */}
        {isFounder && (
          <div className="flex items-center justify-between gap-3 flex-wrap rounded-lg border border-dashed border-edge-md px-4 py-3">
            <div className="min-w-0">
              <p className="text-sm text-ink-2">Admin Creator</p>
              <p className="text-xs text-ink-3">
                Experimental four-reference workflow. Internal testing only.
              </p>
            </div>
            <Link
              to="/admin-creator"
              className="shrink-0 rounded-lg border border-edge-md px-3 py-1.5 text-xs text-ink-2 hover:text-ink hover:border-gem/40 transition-colors"
            >
              Open Admin Creator
            </Link>
          </div>
        )}

        {/* Image generator */}
        {myCharacters.length > 0 && (
          <SceneGeneratorPanel
            characters={myCharacters}
            initialCharacterId={onboardingCharId}
            initialPrompt={onboardingPrompt}
            // Keep the generator on the character the library is showing, so a
            // founder picks a character once rather than twice. 'all' has no
            // single character, so it passes null and the panel keeps its own.
            followCharacterId={typeof charFilter === 'number' ? charFilter : null}
            onGenerated={(image) => {
              setImages((prev) => [image as unknown as LibraryImage, ...prev]);
              setQuota((q) =>
                q && !q.unlimited && q.remaining !== null
                  ? { ...q, used: q.used + 1, remaining: Math.max(0, q.remaining - 1) }
                  : q
              );
            }}
          />
        )}

        {/* 18+ Studio entry point — separate workflow, stronger identity-locking */}
        <div className="border border-fuchsia-800/40 bg-fuchsia-900/10 rounded-lg px-4 py-3 flex items-start gap-3">
          <div className="rounded-lg bg-fuchsia-900/30 border border-fuchsia-800/40 p-2 shrink-0">
            <Sparkles className="w-4 h-4 text-fuchsia-300" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-fuchsia-200">18+ Studio</p>
            <p className="text-xs text-ink-2 mt-0.5">
              Use stronger identity-locking for swimwear, lingerie, underwear, and mature character scenes.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              const studioCharId = onboardingCharId ?? myCharacters[0]?.id;
              navigate(studioCharId != null ? `/studio/18-plus?characterId=${studioCharId}` : '/studio/18-plus');
            }}
            className="btn btn-secondary text-sm shrink-0 self-center"
          >
            Open 18+ Studio
          </button>
        </div>

        {/* Weekly allowance */}
        {quota && !quota.unlimited && (
          quota.remaining === 0 ? (
            <div className="space-y-0.5">
              <p className="text-xs text-amber-400">
                You've used all {quota.limit} images for this week.
              </p>
              <p className="text-xs text-ink-3">
                {quota.reset_at
                  ? `Your allowance resets ${formatResetTime(quota.reset_at)}.`
                  : 'Your allowance resets weekly.'}
              </p>
            </div>
          ) : (
            <p className="text-xs text-ink-3">
              {quota.remaining} of {quota.limit} image{quota.limit !== 1 ? 's' : ''} remaining this week
            </p>
          )
        )}

        {loadError && (
          <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2">
            {loadError}
          </p>
        )}

        {/* Character-first library controls */}
        {myCharacters.length > 0 && charFilter !== null && (
          <div className="flex flex-wrap items-center gap-3 pb-1">
            {/* Selected-character identity — name + avatar, so the workspace
                always announces whose images these are */}
            {selectedChar && (
              <div className="flex items-center gap-2 mr-1">
                <div className="w-8 h-8 rounded-lg overflow-hidden bg-surface-elevated shrink-0 flex items-center justify-center">
                  {selectedChar.avatar_url ? (
                    <img src={selectedChar.avatar_url} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <span className="font-serif text-sm text-gem">{selectedChar.name.charAt(0)}</span>
                  )}
                </div>
                <span className="text-sm font-medium text-ink">{selectedChar.name}</span>
              </div>
            )}
            {isAllMode && (
              <span className="text-sm font-medium text-ink mr-1">All Characters</span>
            )}

            {/* Character filter */}
            <label className="flex items-center gap-1.5 text-xs text-ink-3">
              Character
              <select
                value={String(charFilter)}
                onChange={(e) => setCharFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))}
                className="bg-surface border border-edge rounded-lg px-2 py-1 text-sm text-ink"
              >
                {myCharacters.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
                {canSeeAllCharacters && <option value="all">All Characters</option>}
              </select>
            </label>

            {/* Sort */}
            <label className="flex items-center gap-1.5 text-xs text-ink-3">
              Sort
              <select
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value as 'newest' | 'oldest')}
                className="bg-surface border border-edge rounded-lg px-2 py-1 text-sm text-ink"
              >
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
              </select>
            </label>

            {/* Source/type — real stored kinds only */}
            <label className="flex items-center gap-1.5 text-xs text-ink-3">
              Type
              <select
                value={kindFilter}
                onChange={(e) => setKindFilter(e.target.value)}
                className="bg-surface border border-edge rounded-lg px-2 py-1 text-sm text-ink"
              >
                <option value="all">All types</option>
                {GALLERY_KINDS.map((k) => (
                  <option key={k} value={k}>{GALLERY_KIND_LABELS[k]}</option>
                ))}
              </select>
            </label>
          </div>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-16 text-ink-2">Loading...</div>
        ) : displayedImages.length === 0 ? (
          <EmptyState
            message={
              myCharacters.length === 0
                ? 'Images belong to characters. Create a character to generate images.'
                : selectedChar
                ? `${selectedChar.name} has no images yet. Use the generator above to create the first.`
                : kindFilter !== 'all'
                ? 'No images of this type.'
                : 'No images yet. Use the generator above to create your first image.'
            }
            primaryAction={
              myCharacters.length === 0
                ? { label: 'Create character', onClick: () => navigate('/characters/new') }
                : undefined
            }
            secondaryAction={
              myCharacters.length === 0
                ? { label: 'Go to Characters', onClick: () => navigate('/characters') }
                : undefined
            }
          />
        ) : isAllMode ? (
          /* All Characters — grouped, each image visibly identifies its character */
          <div className="space-y-8">
            {groupedImages.map((group) => (
              <div key={group.char?.id ?? 'orphans'} className="space-y-3">
                <div className="flex items-center gap-2 border-b border-edge pb-2">
                  {group.char ? (
                    <>
                      <div className="w-6 h-6 rounded-md overflow-hidden bg-surface-elevated shrink-0 flex items-center justify-center">
                        {group.char.avatar_url ? (
                          <img src={group.char.avatar_url} alt="" className="w-full h-full object-cover" />
                        ) : (
                          <span className="font-serif text-xs text-gem">{group.char.name.charAt(0)}</span>
                        )}
                      </div>
                      <span className="text-sm font-medium text-ink">{group.char.name}</span>
                    </>
                  ) : (
                    <span className="text-sm font-medium text-ink-3">Unassigned assets</span>
                  )}
                  <span className="text-xs text-ink-3">· {group.images.length}</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  {group.images.map(renderCard)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          /* Single character — imagery first, no repeated character label */
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {displayedImages.map(renderCard)}
          </div>
        )}
      </div>

      {/* Lightbox — view + avatar modes only (cover editor is a separate overlay below) */}
      <ErrorBoundary>
        {lightboxImage && lbMode !== 'coverEdit' && (
          <div
            className={`fixed inset-0 z-50 overflow-y-auto bg-black/80 sm:backdrop-blur-sm transition-opacity duration-200 ${lbVisible ? 'opacity-100' : 'opacity-0'}`}
            onClick={closeLightbox}
          >
            <div className="flex min-h-full items-center justify-center p-4">
              <div
                className={`relative max-w-2xl w-full transition-all duration-200 ease-out ${lbVisible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'}`}
                onClick={(e) => e.stopPropagation()}
              >
                {/* Close button */}
                <button
                  className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 z-10"
                  onClick={closeLightbox}
                >
                  <X className="w-4 h-4" />
                </button>

                {/* ── VIEW MODE ── */}
                {lbMode === 'view' && (
                  <div>
                    <img
                      src={lightboxImage.url}
                      alt="Full size"
                      className="w-full rounded-lg max-h-[70vh] object-contain"
                    />

                    {/* Character association — name the character these actions
                        affect, with a link to its profile. Removes any ambiguity
                        about which character "Set as cover" targets. */}
                    {lightboxImage.character_id != null && charById.get(lightboxImage.character_id) && (
                      <div className="mt-3 flex items-center justify-between gap-2">
                        <span className="text-xs text-ink-3">
                          {charById.get(lightboxImage.character_id)!.name}
                        </span>
                        <Link
                          to={`/characters/${lightboxImage.character_id}`}
                          className="text-xs text-gem hover:underline"
                        >
                          View character profile
                        </Link>
                      </div>
                    )}

                    {/* Primary actions */}
                    {myCharacters.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          className="text-xs px-3 py-1.5 rounded bg-gem hover:bg-gem/90 text-gem-ink transition-colors"
                          onClick={enterCoverEdit}
                        >
                          Set as cover
                        </button>
                        <button
                          className="text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white transition-colors"
                          onClick={enterAvatarEdit}
                        >
                          Set as profile picture
                        </button>
                      </div>
                    )}

                    {/* Delete / Report */}
                    <div className="mt-2 space-y-2">
                      {deleteError && (
                        <p className="text-xs text-red-400">{deleteError}</p>
                      )}
                      <div className="flex items-center justify-between">
                        <button
                          className="text-xs text-ink-2 hover:text-ink transition-colors flex items-center gap-1"
                          onClick={() => setReportStep(reportStep === 'form' ? 'idle' : 'form')}
                        >
                          <Flag className="w-3 h-3" />
                          Report issue
                        </button>
                        <button
                          className="text-xs px-3 py-1.5 rounded bg-red-900/60 hover:bg-red-800 text-red-300 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                          disabled={deletingImage}
                          onClick={handleDeleteImage}
                        >
                          <Trash2 className="w-3 h-3" />
                          {deletingImage ? 'Deleting…' : 'Delete'}
                        </button>
                      </div>

                      {reportStep === 'form' && (
                        <div className="border border-edge-md rounded-lg p-3 space-y-2 bg-surface">
                          <p className="text-xs font-medium text-ink-2">Report this image</p>
                          <textarea
                            className="textarea w-full text-sm"
                            rows={2}
                            maxLength={200}
                            placeholder="Describe the issue…"
                            value={reportReason}
                            onChange={(e) => setReportReason(e.target.value)}
                          />
                          {reportError && <p className="text-xs text-red-400">{reportError}</p>}
                          <div className="flex gap-2 justify-end">
                            <button
                              className="text-xs text-ink-2 hover:text-ink transition-colors"
                              onClick={() => setReportStep('idle')}
                            >
                              Cancel
                            </button>
                            <button
                              className="text-xs px-3 py-1.5 rounded bg-surface-overlay hover:bg-surface-overlay text-ink transition-colors disabled:opacity-50"
                              disabled={reportSubmitting || !reportReason.trim()}
                              onClick={handleSubmitReport}
                            >
                              {reportSubmitting ? 'Submitting…' : 'Submit'}
                            </button>
                          </div>
                        </div>
                      )}

                      {reportStep === 'done' && (
                        <p className="text-xs text-gem">Report submitted. Thank you.</p>
                      )}
                    </div>
                  </div>
                )}

                {/* ── AVATAR EDIT MODE ── drag + zoom */}
                {lbMode === 'avatarEdit' && (
                  <div className="space-y-3 bg-surface rounded-lg p-4">
                    <p className="text-sm font-medium text-ink">Set as profile picture</p>

                    {/* Character selector */}
                    {myCharacters.length > 1 && (
                      <div className="flex items-center gap-2">
                        <label className="text-xs text-ink-2 shrink-0">For character</label>
                        <select
                          className="flex-1 bg-surface-elevated border border-edge-md rounded-md text-sm text-ink px-3 py-1.5 focus:outline-none"
                          value={assignCharId ?? ''}
                          onChange={(e) => setAssignCharId(e.target.value ? Number(e.target.value) : null)}
                        >
                          <option value="">Select character…</option>
                          {myCharacters.map((c) => (
                            <option key={c.id} value={c.id}>{c.name}</option>
                          ))}
                        </select>
                      </div>
                    )}

                    {/* Avatar frame preview */}
                    <div className="flex flex-col items-center gap-3">
                      <div
                        ref={avatarFrameRef}
                        className="relative w-40 h-40 rounded-full overflow-hidden border-2 border-edge-md select-none"
                        style={{ cursor: avatarScale > 1.001 ? 'grab' : 'default', touchAction: 'none' }}
                        onMouseDown={(e) => { e.preventDefault(); startAvatarDrag(e.clientX, e.clientY); }}
                        onTouchStart={(e) => { e.preventDefault(); startAvatarDrag(e.touches[0].clientX, e.touches[0].clientY); }}
                      >
                        <img
                          src={lightboxImage.url}
                          alt="Avatar preview"
                          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                          style={{
                            transformOrigin: 'center center',
                            transform: `scale(${avatarScale}) translate(${(0.5 - avatarPosX) * (avatarScale - 1) / avatarScale * 100}%, ${(0.5 - avatarPosY) * (avatarScale - 1) / avatarScale * 100}%)`,
                          }}
                          draggable={false}
                        />
                      </div>

                      {/* Zoom slider — avatar only */}
                      <div className="flex items-center gap-2 w-48">
                        <span className="text-xs text-ink-2 shrink-0">Zoom</span>
                        <input
                          type="range"
                          min="1"
                          max="3"
                          step="0.01"
                          value={avatarScale}
                          onChange={(e) => avatarDrag.setScale(parseFloat(e.target.value))}
                          className="flex-1 accent-[rgb(var(--gem))]"
                          onMouseDown={(e) => e.stopPropagation()}
                          onTouchStart={(e) => e.stopPropagation()}
                        />
                        <span className="text-xs text-ink-2 w-7 shrink-0">{avatarScale.toFixed(1)}×</span>
                      </div>
                    </div>

                    {avatarSaveErr && <p className="text-xs text-red-400">{avatarSaveErr}</p>}

                    <div className="flex items-center gap-2 justify-end">
                      <button
                        className="text-xs px-3 py-1.5 rounded bg-surface-overlay hover:bg-surface-overlay text-ink transition-colors disabled:opacity-50"
                        onClick={() => setLbMode('view')}
                        disabled={avatarSaving}
                      >
                        Cancel
                      </button>
                      <button
                        className="text-xs px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-50 flex items-center gap-1.5"
                        disabled={avatarSaving || assignCharId === null}
                        onClick={handleSaveAvatar}
                      >
                        {avatarSaveDone
                          ? <><Check className="w-3 h-3" />Saved</>
                          : avatarSaving ? 'Saving…' : 'Save avatar'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── COVER EDIT OVERLAY ──
            Rendered outside the max-w-2xl lightbox so its frame matches the profile
            banner geometry exactly: max-w-[1000px] + px-4/sm:px-8 = same usable width. */}
        {lightboxImage && lbMode === 'coverEdit' && (
          <div
            className={`fixed inset-0 z-50 overflow-y-auto bg-[#0F1419]/95 sm:backdrop-blur-sm transition-opacity duration-200 ${lbVisible ? 'opacity-100' : 'opacity-0'}`}
          >
            <div className="max-w-[1000px] mx-auto px-4 sm:px-8 py-6 space-y-4">
              {/* Header */}
              <div className="flex items-center justify-between">
                <p className="text-sm font-medium text-ink">Set as cover</p>
                <button
                  className="p-1.5 rounded-full bg-black/40 text-white hover:bg-black/60"
                  onClick={() => setLbMode('view')}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Character selector */}
              {myCharacters.length > 1 && (
                <div className="flex items-center gap-2">
                  <label className="text-xs text-ink-2 shrink-0">For character</label>
                  <select
                    className="flex-1 bg-surface-elevated border border-edge-md rounded-md text-sm text-ink px-3 py-1.5 focus:outline-none"
                    value={assignCharId ?? ''}
                    onChange={(e) => setAssignCharId(e.target.value ? Number(e.target.value) : null)}
                  >
                    <option value="">Select character…</option>
                    {myCharacters.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* Banner preview — same dimensions as profile banner (WYSIWYG) */}
              <div
                ref={coverFrameRef}
                className="relative w-full h-[260px] sm:h-[320px] md:h-[360px] rounded-2xl overflow-hidden select-none"
                style={{ cursor: 'grab', touchAction: 'none' }}
                onMouseDown={(e) => { e.preventDefault(); startCoverDrag(e.clientX, e.clientY); }}
                onTouchStart={(e) => { e.preventDefault(); startCoverDrag(e.touches[0].clientX, e.touches[0].clientY); }}
              >
                <img
                  src={lightboxImage.url}
                  alt="Cover preview"
                  className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                  style={{ objectPosition: `${coverPosX * 100}% ${coverPosY * 100}%` }}
                  draggable={false}
                />
                <div className="absolute inset-0 flex items-start justify-center pt-2 pointer-events-none">
                  <span className="text-[10px] text-white/60 bg-black/50 px-2 py-0.5 rounded select-none">
                    Drag to reposition
                  </span>
                </div>
              </div>

              {coverSaveErr && <p className="text-xs text-red-400">{coverSaveErr}</p>}

              <div className="flex items-center gap-2 justify-end">
                <button
                  className="text-xs px-3 py-1.5 rounded bg-surface-overlay hover:bg-surface-overlay text-ink transition-colors disabled:opacity-50"
                  onClick={() => setLbMode('view')}
                  disabled={coverSaving}
                >
                  Cancel
                </button>
                <button
                  className="text-xs px-3 py-1.5 rounded bg-gem hover:bg-gem/90 text-gem-ink transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  disabled={coverSaving || assignCharId === null}
                  onClick={handleSaveCover}
                >
                  {coverSaveDone
                    ? <><Check className="w-3 h-3" />Saved</>
                    : coverSaving ? 'Saving…' : 'Save cover'}
                </button>
              </div>
            </div>
          </div>
        )}
      </ErrorBoundary>
    </div>
  );
}

/** Human-readable label for when the weekly image allowance resets. */
function formatResetTime(resetAt: string): string {
  const reset = new Date(resetAt);
  const now = new Date();
  const diffMs = reset.getTime() - now.getTime();
  if (diffMs <= 0) return 'very soon';
  const diffHours = Math.ceil(diffMs / (1000 * 60 * 60));
  if (diffHours <= 1) return 'in about an hour';
  if (diffHours < 24) return `in about ${diffHours} hours`;
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 1) return 'tomorrow';
  return `in ${diffDays} days`;
}

interface EmptyStateProps {
  message: string;
  primaryAction?: { label: string; onClick: () => void };
  secondaryAction?: { label: string; onClick: () => void };
}

function EmptyState({ message, primaryAction, secondaryAction }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center text-center py-16 space-y-4">
      <div className="w-14 h-14 rounded-full bg-gem-soft border border-gem/50 flex items-center justify-center">
        <Image className="w-7 h-7 text-gem" />
      </div>
      <h2 className="text-lg font-semibold text-ink">No images yet</h2>
      <p className="text-sm text-ink-2 max-w-sm">{message}</p>
      {(primaryAction || secondaryAction) && (
        <div className="flex items-center gap-2 pt-1">
          {primaryAction && (
            <button onClick={primaryAction.onClick} className="btn btn-primary text-sm">
              {primaryAction.label}
            </button>
          )}
          {secondaryAction && (
            <button onClick={secondaryAction.onClick} className="btn btn-secondary text-sm">
              {secondaryAction.label}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
