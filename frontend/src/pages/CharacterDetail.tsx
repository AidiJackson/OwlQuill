import { useState, useEffect, useRef } from 'react';
import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom';
import { ArrowLeft, Globe, Users, Lock, Feather, RefreshCw, MessageSquare, UserPlus, UserCheck, Trash2, X, Check, Sparkles, ChevronLeft, ShieldCheck, AlertTriangle, Image as ImageIcon, CheckCircle2, AlertCircle, Loader2, Library } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character, User, BodyMarkingRead, MarkingAnchorStatus, BodySlotEntry, BodySlotStatus, PackStages, IdentityHealth } from '@/lib/types';
import { listCharacterImages, resolveImageUrl, setCharacterAvatar } from '@/features/characterCreation/shared/api';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import ImageGrid from '@/features/images/components/ImageGrid';
import type { BodyAnchorOption } from '@/features/images/components/ImageCard';
import PostComposer from '@/features/posts/components/PostComposer';
import ErrorBoundary from '@/components/ErrorBoundary';
import SignatureAccessoryPanel from '@/features/characterCreation/components/SignatureAccessoryPanel';
import StyleShopsPanel from '@/components/StyleShopsPanel';
import BodyCanonPanel from '@/components/BodyCanonPanel';

const VISIBILITY_ICONS = {
  public: Globe,
  friends: Users,
  private: Lock,
} as const;

export default function CharacterDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [character, setCharacter] = useState<Character | null>(null);
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const justCreated = searchParams.get('created') === '1';

  const [following, setFollowing] = useState(false);
  const [showEvolveModal, setShowEvolveModal] = useState(false);

  // Evolve identity slot replacement state
  type EvolveView = 'slots' | 'pick' | 'confirm';
  type CandidateSlotRead = {
    id: number; character_id: number; slot: string; image_url: string;
    status: string; validation_status: string; validation_notes: string | null; created_at: string;
  };
  const [evolveView, setEvolveView] = useState<EvolveView>('slots');
  const [evolveSlot, setEvolveSlot] = useState<string | null>(null);
  const [evolveCandidate, setEvolveCandidate] = useState<CandidateSlotRead | null>(null);
  const [evolveCreating, setEvolveCreating] = useState(false);
  const [evolveValidating, setEvolveValidating] = useState(false);
  const [evolvePromoting, setEvolvePromoting] = useState(false);
  const [evolveRejecting, setEvolveRejecting] = useState(false);
  const [evolveError, setEvolveError] = useState('');
  const [evolveSuccess, setEvolveSuccess] = useState('');

  // Body canon state (loaded when evolve modal opens)
  const [bodyMarkings, setBodyMarkings] = useState<BodyMarkingRead[]>([]);
  const [bodyMarkingsLoading, setBodyMarkingsLoading] = useState(false);
  const [bodyMarkingsError, setBodyMarkingsError] = useState('');
  const [bodyAnchorBusy, setBodyAnchorBusy] = useState<Record<string, 'generate' | 'lock' | 'replace'>>({});

  // Body identity slot state (loaded when evolve modal opens)
  const [bodySlots, setBodySlots] = useState<BodySlotEntry[]>([]);
  const [bodySlotsLoading, setBodySlotsLoading] = useState(false);
  const [bodySlotsError, setBodySlotsError] = useState('');
  const [bodySlotBusy, setBodySlotBusy] = useState<Record<string, 'generate' | 'lock' | 'replace' | 'use-existing'>>({});

  // Body slot library picker (inside evolve modal — slot key or null)
  const [bodySlotLibraryTarget, setBodySlotLibraryTarget] = useState<string | null>(null);
  const [bodySlotLibraryBusy, setBodySlotLibraryBusy] = useState(false);

  // Body canon library picker (inside evolve modal — marking ID or null)
  const [bodyCanonLibraryTarget, setBodyCanonLibraryTarget] = useState<string | null>(null);
  const [bodyCanonLibraryBusy, setBodyCanonLibraryBusy] = useState(false);

  // Pack stages (derived from identity_anchor_json.pack_stages)
  const [packStages, setPackStages] = useState<PackStages | null>(null);

  // Admin canon import state (body_front / tattoo_layout upload)
  // Identity OS Beta: extended to all canon import slots
  type AdminCanonSlot = 'face_front' | 'face_three_quarter_left' | 'face_three_quarter_right'
    | 'body_front' | 'body_left' | 'body_right' | 'body_back' | 'body_map'
    | 'final_character_card' | 'accessory_design' | 'accessory_fit' | 'tattoo_layout';
  const [adminImportSlot, setAdminImportSlot] = useState<AdminCanonSlot | null>(null);
  const [adminImportBusy, setAdminImportBusy] = useState(false);
  const [adminImportError, setAdminImportError] = useState('');

  // Body canon anchor picker (triggered from gallery "Anchor" dropdown — image selected first, then pick marking)
  const [anchorPickImage, setAnchorPickImage] = useState<CharacterImageRead | null>(null);
  const [anchorPickBusy, setAnchorPickBusy] = useState<string | null>(null);

  const [galleryImages, setGalleryImages] = useState<CharacterImageRead[]>([]);
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

  // ── Evolve identity helpers ────────────────────────────────────────────────

  const SLOT_LABELS: Record<string, string> = {
    front: 'Front Portrait',
    three_quarter: 'Three-Quarter',
    torso: 'Torso',
    full_body: 'Full Body',
  };
  const ALL_SLOTS = ['front', 'three_quarter', 'torso', 'full_body'];

  function parseSlotUrl(slot: string): string | null {
    if (!character?.identity_anchor_json) return null;
    try {
      const data = JSON.parse(character.identity_anchor_json);
      return data?.anchors?.[slot]?.url ?? null;
    } catch {
      return null;
    }
  }

  async function openEvolveModal() {
    setEvolveView('slots');
    setEvolveSlot(null);
    setEvolveCandidate(null);
    setEvolveError('');
    setEvolveSuccess('');
    setBodyMarkings([]);
    setBodyMarkingsError('');
    setBodySlots([]);
    setBodySlotsError('');
    setShowEvolveModal(true);
    if (character) {
      // Derive pack stages from identity_anchor_json if present
      try {
        const anchorData = character.identity_anchor_json ? JSON.parse(character.identity_anchor_json) : {};
        if (anchorData.pack_stages) setPackStages(anchorData.pack_stages as PackStages);
      } catch { /* ignore */ }

      // Load body markings and body slots in parallel
      setBodyMarkingsLoading(true);
      setBodySlotsLoading(true);
      Promise.all([
        apiClient.getBodyMarkings(character.id).then(data => {
          if (mountedRef.current) setBodyMarkings(data.markings);
        }).catch(() => {
          if (mountedRef.current) setBodyMarkingsError('Could not load body markings.');
        }).finally(() => {
          if (mountedRef.current) setBodyMarkingsLoading(false);
        }),
        apiClient.getBodySlots(character.id).then(data => {
          if (mountedRef.current) setBodySlots(data.slots);
        }).catch(() => {
          if (mountedRef.current) setBodySlotsError('Could not load body identity slots.');
        }).finally(() => {
          if (mountedRef.current) setBodySlotsLoading(false);
        }),
      ]);
    }
  }

  function closeEvolveModal() {
    setShowEvolveModal(false);
    setEvolveView('slots');
    setEvolveSlot(null);
    setEvolveCandidate(null);
    setEvolveError('');
    setEvolveSuccess('');
    setBodyMarkings([]);
    setBodyMarkingsError('');
    setBodyAnchorBusy({});
    setBodySlots([]);
    setBodySlotsError('');
    setBodySlotBusy({});
    setBodySlotLibraryTarget(null);
    setBodyCanonLibraryTarget(null);
  }

  async function handleBodyAnchorAction(
    marking: BodyMarkingRead,
    action: 'generate' | 'lock' | 'replace',
  ) {
    if (!character) return;
    setBodyAnchorBusy(prev => ({ ...prev, [marking.id]: action }));
    try {
      let resp;
      if (action === 'generate') resp = await apiClient.generateBodyAnchor(character.id, marking.id);
      else if (action === 'lock') resp = await apiClient.lockBodyAnchor(character.id, marking.id);
      else resp = await apiClient.replaceBodyAnchor(character.id, marking.id);
      if (mountedRef.current) {
        setBodyMarkings(prev => prev.map(m => m.id === resp.marking.id ? resp.marking : m));
      }
    } catch {
      // action failure is silent — button re-enables
    } finally {
      if (mountedRef.current) {
        setBodyAnchorBusy(prev => { const n = { ...prev }; delete n[marking.id]; return n; });
      }
    }
  }

  async function handleBodySlotAction(
    slot: BodySlotEntry,
    action: 'generate' | 'lock' | 'replace',
  ) {
    if (!character) return;
    setBodySlotBusy(prev => ({ ...prev, [slot.key]: action }));
    try {
      let resp;
      if (action === 'generate') resp = await apiClient.generateBodySlot(character.id, slot.key);
      else if (action === 'lock') resp = await apiClient.lockBodySlot(character.id, slot.key);
      else resp = await apiClient.replaceBodySlot(character.id, slot.key);
      if (mountedRef.current) {
        setBodySlots(resp.slots);
      }
    } catch {
      // action failure is silent — button re-enables
    } finally {
      if (mountedRef.current) {
        setBodySlotBusy(prev => { const n = { ...prev }; delete n[slot.key]; return n; });
      }
    }
  }

  // Use an existing gallery image for a body identity slot (from within modal library picker)
  async function handleBodySlotUseExisting(slotKey: string, img: CharacterImageRead) {
    if (!character) return;
    setBodySlotLibraryBusy(true);
    try {
      const resp = await apiClient.useExistingBodySlot(character.id, slotKey, img.id);
      if (mountedRef.current) {
        setBodySlots(resp.slots);
        setBodySlotLibraryTarget(null);
      }
    } catch {
      // silent
    } finally {
      if (mountedRef.current) setBodySlotLibraryBusy(false);
    }
  }

  // Assign an existing gallery image to a body canon marking anchor (from modal library picker)
  async function handleBodyCanonLibraryAssign(img: CharacterImageRead) {
    if (!character || !bodyCanonLibraryTarget) return;
    setBodyCanonLibraryBusy(true);
    try {
      const resp = await apiClient.useExistingBodyAnchor(character.id, bodyCanonLibraryTarget, img.id);
      if (mountedRef.current) {
        setBodyMarkings(prev => prev.map(m => m.id === resp.marking.id ? resp.marking : m));
        setBodyCanonLibraryTarget(null);
      }
    } catch {
      // silent
    } finally {
      if (mountedRef.current) setBodyCanonLibraryBusy(false);
    }
  }

  // Use an existing gallery image as a body slot anchor (from image card dropdown)
  async function handleBodyAnchorAssign(img: CharacterImageRead, value: string) {
    if (!character) return;
    if (value === 'body_canon_anchor') {
      // Open marking picker
      setAnchorPickImage(img);
      return;
    }
    // Body identity slot targets
    try {
      const resp = await apiClient.useExistingBodySlot(character.id, value, img.id);
      if (mountedRef.current) setBodySlots(resp.slots);
    } catch {
      // silent
    }
  }

  // Admin canon import — file upload for body_front or tattoo_layout
  async function handleAdminCanonImport(slot: 'body_front' | 'tattoo_layout', file: File, sourceNote?: string) {
    if (!character) return;
    setAdminImportBusy(true);
    setAdminImportError('');
    try {
      const resp = await apiClient.adminCanonImport(character.id, slot, file, sourceNote);
      if (mountedRef.current) {
        setPackStages(resp.pack_stages);
        // Refresh body slots to reflect new locked state
        const slotsResp = await apiClient.getBodySlots(character.id);
        if (mountedRef.current) setBodySlots(slotsResp.slots);
        setAdminImportSlot(null);
      }
    } catch (err: unknown) {
      if (mountedRef.current) setAdminImportError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      if (mountedRef.current) setAdminImportBusy(false);
    }
  }

  // Assign picked image to a specific body canon marking anchor
  async function handleAnchorPickConfirm(markingId: string) {
    if (!character || !anchorPickImage) return;
    setAnchorPickBusy(markingId);
    try {
      const resp = await apiClient.useExistingBodyAnchor(character.id, markingId, anchorPickImage.id);
      if (mountedRef.current) {
        setBodyMarkings(prev => prev.map(m => m.id === resp.marking.id ? resp.marking : m));
        setAnchorPickImage(null);
      }
    } catch {
      // silent
    } finally {
      if (mountedRef.current) setAnchorPickBusy(null);
    }
  }

  async function handleSelectCandidate(img: CharacterImageRead) {
    if (!character || !evolveSlot) return;
    setEvolveCreating(true);
    setEvolveError('');
    try {
      const imageUrl = resolveImageUrl(img.url);
      const candidate = await apiClient.createCandidateSlot(character.id, {
        slot: evolveSlot,
        image_url: imageUrl,
      });
      // Auto-validate after creation
      setEvolveValidating(true);
      const validated = await apiClient.validateCandidateSlot(character.id, candidate.id);
      setEvolveCandidate(validated);
      setEvolveView('confirm');
    } catch (err) {
      setEvolveError(err instanceof Error ? err.message : 'Failed to create candidate.');
    } finally {
      setEvolveCreating(false);
      setEvolveValidating(false);
    }
  }

  async function handlePromote() {
    if (!character || !evolveCandidate) return;
    setEvolvePromoting(true);
    setEvolveError('');
    try {
      const result = await apiClient.promoteCandidateSlot(character.id, evolveCandidate.id);
      setEvolveCandidate(result.candidate);
      setEvolveSuccess(
        `${SLOT_LABELS[evolveCandidate.slot] ?? evolveCandidate.slot} promoted to canon. ` +
        `Snapshot #${result.snapshot.id} saved — rollback available.`
      );
      // Refresh character to get updated identity_anchor_json
      const updated = await apiClient.getCharacter(character.id).catch(() => null);
      if (updated && mountedRef.current) setCharacter(updated);
      setEvolveView('slots');
    } catch (err) {
      setEvolveError(err instanceof Error ? err.message : 'Promotion failed.');
    } finally {
      setEvolvePromoting(false);
    }
  }

  async function handleReject() {
    if (!character || !evolveCandidate) return;
    setEvolveRejecting(true);
    setEvolveError('');
    try {
      await apiClient.rejectCandidateSlot(character.id, evolveCandidate.id);
      setEvolveView('slots');
      setEvolveSlot(null);
      setEvolveCandidate(null);
    } catch (err) {
      setEvolveError(err instanceof Error ? err.message : 'Rejection failed.');
    } finally {
      setEvolveRejecting(false);
    }
  }

  // ─────────────────────────────────────────────────────────────────────────

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
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Character not found'))
      .finally(() => setLoading(false));
  }, [id]);

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

  const VisIcon = VISIBILITY_ICONS[character.visibility] || Globe;

  return (
    <div className="min-h-screen">
      {/* Top bar */}
      <div className="border-b border-gray-800 bg-gray-900/50">
        <div className="max-w-2xl mx-auto px-4 py-3 flex items-center gap-3">
          <Link
            to="/characters"
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <span className="text-sm font-medium text-gray-300 truncate">
            {character.name}
          </span>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-6 space-y-6">
        {/* Arrival banner */}
        {justCreated && (
          <div className="bg-emerald-600/10 border border-emerald-600/20 rounded-lg px-4 py-4 space-y-3">
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
              <button
                onClick={() => navigate('/')}
                className="btn btn-primary text-sm"
              >
                Post to The Commons
              </button>
              <button
                onClick={() => navigate('/storylab')}
                className="btn btn-secondary text-sm"
              >
                Open StoryLab
              </button>
            </div>
          </div>
        )}

        {/* Header */}
        <div className="flex gap-5 items-start">
          <Link
            to={`/characters/${character.id}`}
            className="flex-shrink-0 group"
          >
            {character.avatar_url ? (
              <img
                src={character.avatar_url}
                alt={character.name}
                className="w-28 h-28 rounded-lg object-cover border border-gray-800 group-hover:border-gray-600 transition-colors"
              />
            ) : (
              <div className="w-28 h-28 rounded-lg bg-gray-800 border border-gray-700 group-hover:border-gray-600 flex items-center justify-center transition-colors">
                <Feather className="w-8 h-8 text-gray-600" />
              </div>
            )}
          </Link>
          <div className="min-w-0 space-y-1.5">
            <h1 className="text-2xl font-bold text-gray-100 truncate">
              <Link
                to={`/characters/${character.id}`}
                className="hover:text-emerald-300 transition-colors"
              >
                {character.name}
              </Link>
            </h1>
            {(character.species || character.role || character.era) && (
              <p className="text-sm text-gray-400">
                {[character.species, character.role, character.era].filter(Boolean).join(' · ')}
              </p>
            )}
            <div className="flex items-center gap-1.5 text-xs text-gray-500">
              <VisIcon className="w-3.5 h-3.5" />
              <span className="capitalize">{character.visibility}</span>
              {character.owner_username && (character.visibility === 'public' || (currentUser && (character.owner_id === currentUser.id))) && (
                <>
                  <span className="text-gray-600">·</span>
                  <Link
                    to={`/u/${encodeURIComponent(character.owner_username)}`}
                    className="text-gray-400 hover:text-emerald-300 hover:underline transition-colors"
                  >
                    @{character.owner_username}
                  </Link>
                </>
              )}
              {character.visual_locked && (
                <>
                  <span className="text-gray-600">·</span>
                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-900/30 border border-emerald-800/40 text-emerald-400/80">
                    <Lock className="w-3 h-3" />
                    Identity locked
                  </span>
                </>
              )}
            </div>
            <div className="flex items-center gap-2 mt-2">
              {currentUser && character.owner_id === currentUser.id ? (
                <button
                  className="btn btn-secondary text-sm flex items-center gap-2 opacity-50 cursor-not-allowed"
                  disabled
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  Message
                </button>
              ) : (
                <button
                  className="btn btn-secondary text-sm flex items-center gap-2"
                  onClick={() => navigate(`/messages/new?characterId=${id}`)}
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  Message
                </button>
              )}
              <button
                className={`text-sm flex items-center gap-2 ${
                  following
                    ? 'btn btn-secondary'
                    : 'btn btn-primary'
                }`}
                onClick={() => setFollowing((prev) => !prev)}
              >
                {following ? (
                  <><UserCheck className="w-3.5 h-3.5" />Collaborating</>
                ) : (
                  <><UserPlus className="w-3.5 h-3.5" />Collaborate</>
                )}
              </button>
            </div>
            {following && (
              <p className="text-xs text-gray-500 mt-1">Collaboration features coming soon.</p>
            )}
            {currentUser && character.owner_id === currentUser.id && (
              <p className="text-xs text-gray-500 mt-1">You can't message your own character.</p>
            )}
            {currentUser && character.owner_id === currentUser.id && (
              <button
                onClick={() => navigate(`/images?characterId=${character.id}`)}
                className="text-sm flex items-center gap-2 btn btn-secondary mt-1"
              >
                <ImageIcon className="w-3.5 h-3.5" />
                Generate Images
              </button>
            )}
            {currentUser && character.owner_id === currentUser.id && character.visual_locked && (
              <button
                onClick={openEvolveModal}
                className="text-sm flex items-center gap-2 btn btn-secondary mt-1"
              >
                <Sparkles className="w-3.5 h-3.5" />
                Manage Character Canon
              </button>
            )}
            {currentUser && character.owner_id === currentUser.id && (
              <button
                className="text-xs text-red-500 hover:text-red-400 transition-colors mt-2 flex items-center gap-1"
                onClick={openDeleteModal}
              >
                <Trash2 className="w-3 h-3" />
                Reset Character Identity
              </button>
            )}
          </div>
        </div>

        {/* Bio */}
        {character.short_bio && (
          <p className="text-gray-300">{character.short_bio}</p>
        )}
        {character.long_bio && (
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{character.long_bio}</p>
          </div>
        )}

        {/* Tags */}
        {character.tags && (
          <div className="flex flex-wrap gap-2">
            {character.tags.split(',').map((tag, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-emerald-900 text-emerald-300 text-xs rounded"
              >
                {tag.trim()}
              </span>
            ))}
          </div>
        )}

        {/* Style Shops — owner only */}
        {currentUser && character.owner_id === currentUser.id && (
          <div className="border-t border-gray-800 pt-6">
            <StyleShopsPanel
              characterId={character.id}
              isOwner={true}
            />
          </div>
        )}

        {/* Body Canon — owner only, separate from Style Shops */}
        {currentUser && character.owner_id === currentUser.id && (
          <div className="border-t border-gray-800 pt-6">
            <BodyCanonPanel
              characterId={character.id}
              isOwner={true}
            />
          </div>
        )}

        {/* Signature Accessory — owner only, locked characters only */}
        {currentUser && character.owner_id === currentUser.id && character.visual_locked && (
          <SignatureAccessoryPanel
            character={character}
            onSaved={(updatedJson) => setCharacter({ ...character, identity_anchor_json: updatedJson })}
          />
        )}

        {/* Image gallery */}
        {galleryImages.length > 0 && (
          <div className="border-t border-gray-800 pt-6 space-y-3">
            <h2 className="text-sm font-medium text-gray-300">Images</h2>
            <ErrorBoundary>
              {(() => {
                const isOwner = !!(currentUser && character.owner_id === currentUser.id);
                const anchorOpts: BodyAnchorOption[] = isOwner ? [
                  { value: 'body_front', label: 'Use as Body Front Reference' },
                  { value: 'body_three_quarter', label: 'Use as Body 3/4 Reference' },
                  { value: 'tattoo_layout', label: 'Use as Tattoo Layout Reference' },
                  { value: 'body_back', label: 'Use as Body Back Reference' },
                  ...(bodyMarkings.length > 0 ? [{ value: 'body_canon_anchor', label: 'Use as Body Canon Anchor…' }] : []),
                ] : [];
                return (
                  <ImageGrid
                    images={galleryImages}
                    onImageClick={(idx) => setLightboxIdx(idx)}
                    onUseInPost={isOwner ? handleUseInPost : undefined}
                    onSetAsCover={isOwner ? handleSetAsCover : undefined}
                    bodyAnchorOptions={isOwner ? anchorOpts : undefined}
                    onBodyAnchorAssign={isOwner ? handleBodyAnchorAssign : undefined}
                  />
                );
              })()}
            </ErrorBoundary>
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
              {currentUser && character.owner_id === currentUser.id && (
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

      {/* Body Canon Anchor picker — triggered from gallery image "Anchor" dropdown */}
      {anchorPickImage && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-sm shadow-2xl">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700/60">
              <h2 className="text-sm font-semibold text-white">Assign as Body Canon Anchor</h2>
              <button onClick={() => setAnchorPickImage(null)} className="p-1 rounded-lg hover:bg-gray-800 text-gray-400 hover:text-white transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 space-y-3">
              <img
                src={resolveImageUrl(anchorPickImage.url)}
                alt="Selected"
                className="w-full max-h-40 object-cover rounded-lg"
              />
              <p className="text-xs text-gray-400">Which marking should use this image as its reference anchor?</p>
              {bodyMarkings.length === 0 && (
                <p className="text-xs text-gray-500">No body markings loaded. Open the Evolve Identity modal first to load markings.</p>
              )}
              <div className="space-y-1.5">
                {bodyMarkings.map((m) => {
                  const isBusy = anchorPickBusy === m.id;
                  return (
                    <button
                      key={m.id}
                      disabled={!!anchorPickBusy}
                      onClick={() => handleAnchorPickConfirm(m.id)}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-left transition-colors disabled:opacity-50"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-xs text-gray-300 font-medium capitalize">{m.type}</span>
                        <span className="text-xs text-gray-500 truncate">{m.placement.replace(/_/g, ' ')}</span>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {m.anchor_status === 'locked' && <CheckCircle2 className="w-3 h-3 text-emerald-400" />}
                        {isBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin text-violet-400" /> : (
                          <span className="text-xs text-violet-400">Use</span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Manage Character Canon modal — slot replacement */}
      {showEvolveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-lg shadow-2xl flex flex-col max-h-[90vh]">

            {/* Header */}
            <div className="flex items-center justify-between gap-3 px-6 pt-6 pb-4 flex-shrink-0">
              <div className="flex items-center gap-2.5">
                {evolveView !== 'slots' && (
                  <button
                    onClick={() => {
                      setEvolveView(evolveView === 'confirm' ? 'pick' : 'slots');
                      setEvolveError('');
                    }}
                    className="text-gray-400 hover:text-gray-200 transition-colors mr-1"
                    aria-label="Back"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                )}
                <div className="w-8 h-8 rounded-lg bg-emerald-900/40 border border-emerald-700/40 flex items-center justify-center flex-shrink-0">
                  <Sparkles className="w-4 h-4 text-emerald-400" />
                </div>
                <h2 className="text-sm font-semibold text-white">
                  {evolveView === 'slots' && 'Manage Character Canon'}
                  {evolveView === 'pick' && `Replace ${SLOT_LABELS[evolveSlot ?? ''] ?? evolveSlot}`}
                  {evolveView === 'confirm' && `Confirm Replacement`}
                </h2>
              </div>
              <button
                onClick={closeEvolveModal}
                className="text-gray-500 hover:text-gray-300 transition-colors p-1 flex-shrink-0"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body — scrollable */}
            <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-4 min-h-0">

              {/* Error banner */}
              {evolveError && (
                <div className="text-xs text-red-400 bg-red-400/10 rounded-lg px-3 py-2 border border-red-400/20">
                  {evolveError}
                </div>
              )}

              {/* Success banner */}
              {evolveSuccess && (
                <div className="text-xs text-emerald-400 bg-emerald-400/10 rounded-lg px-3 py-2 border border-emerald-400/20 flex items-start gap-2">
                  <ShieldCheck className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                  <span>{evolveSuccess}</span>
                </div>
              )}

              {/* ── Slots view ─────────────────────────────────────── */}
              {evolveView === 'slots' && (
                <>
                  <p className="text-xs text-gray-400 leading-relaxed">
                    Manage your character&apos;s locked canon. Face and body identity are separate layers.
                    Permanent tattoos and markings are locked body truth. Scene images do not change
                    canon unless explicitly promoted.
                  </p>

                  {/* Identity health status cards */}
                  {character?.identity_health && (() => {
                    const h = character.identity_health as IdentityHealth;
                    return (
                      <div className="grid grid-cols-3 gap-2">
                        {(['face', 'body', 'tattoos'] as const).map((domain) => {
                          const isStale = h[domain] === 'stale';
                          return (
                            <div
                              key={domain}
                              className={`rounded-lg px-2.5 py-2 border text-center ${
                                isStale
                                  ? 'bg-amber-900/20 border-amber-800/40'
                                  : 'bg-emerald-900/20 border-emerald-800/40'
                              }`}
                            >
                              <p className="text-xs text-gray-400 capitalize mb-1">{domain}</p>
                              {isStale ? (
                                <span className="flex items-center justify-center gap-1 text-xs text-amber-400 font-medium">
                                  <AlertTriangle className="w-3 h-3" />
                                  Refresh recommended
                                </span>
                              ) : (
                                <span className="flex items-center justify-center gap-1 text-xs text-emerald-400 font-medium">
                                  <CheckCircle2 className="w-3 h-3" />
                                  Current
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })()}

                  {/* Section 1: Core Face Identity */}
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold text-white">Core Face Identity</h3>
                    <span className="text-xs text-gray-500">Face &amp; portrait anchors</span>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    {ALL_SLOTS.map((slot) => {
                      const url = parseSlotUrl(slot);
                      return (
                        <div
                          key={slot}
                          className="rounded-xl border border-gray-700/60 bg-gray-800/40 overflow-hidden"
                        >
                          <div className="aspect-square bg-gray-800 relative">
                            {url ? (
                              <img
                                src={resolveImageUrl(url)}
                                alt={SLOT_LABELS[slot]}
                                className="w-full h-full object-cover"
                              />
                            ) : (
                              <div className="w-full h-full flex items-center justify-center">
                                <Feather className="w-6 h-6 text-gray-600" />
                              </div>
                            )}
                          </div>
                          <div className="px-2.5 py-2 space-y-1.5">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-xs text-gray-400 truncate">{SLOT_LABELS[slot]}</span>
                              <button
                                onClick={() => {
                                  setEvolveSlot(slot);
                                  setEvolveView('pick');
                                  setEvolveError('');
                                  setEvolveSuccess('');
                                }}
                                className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors whitespace-nowrap flex-shrink-0"
                              >
                                Replace
                              </button>
                            </div>
                            {character?.identity_health?.slots?.[slot]?.stale && (
                              <span className="flex items-center gap-1 text-xs text-amber-400">
                                <AlertTriangle className="w-3 h-3 flex-shrink-0" />
                                Refresh recommended
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="flex items-start gap-2 rounded-lg bg-gray-800/40 border border-gray-700/40 px-3 py-2.5">
                    <Lock className="w-3.5 h-3.5 text-emerald-500/70 flex-shrink-0 mt-0.5" />
                    <p className="text-xs text-gray-500 leading-relaxed">
                      Face geometry, species, and body morphology are always preserved.
                      Only the selected slot image changes.
                    </p>
                  </div>

                  {/* ── Section 2: Body Canon ──────────────────────── */}
                  <div className="pt-2 border-t border-gray-700/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-white">Body Canon</h3>
                        {packStages && (
                          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                            packStages.body === 'locked' ? 'bg-emerald-900/40 text-emerald-400' :
                            packStages.body === 'partial' ? 'bg-amber-900/40 text-amber-400' :
                            'bg-gray-700/60 text-gray-500'
                          }`}>
                            {packStages.body}
                          </span>
                        )}
                      </div>
                      {bodySlotLibraryTarget ? (
                        <button
                          onClick={() => setBodySlotLibraryTarget(null)}
                          className="text-xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
                        >
                          <ChevronLeft className="w-3 h-3" />Back
                        </button>
                      ) : (
                        <span className="text-xs text-gray-500">Morphology &amp; tattoo layout</span>
                      )}
                    </div>

                    {/* Helper text */}
                    {!bodySlotLibraryTarget && (
                      <div className="space-y-1.5">
                        <p className="text-xs text-gray-500 leading-relaxed">
                          Generation can create a new reference, but choosing a proven image from your library is the most reliable way to lock body canon.
                        </p>
                        <p className="text-xs text-emerald-600/80 leading-relaxed">
                          Permanent tattoos and markings are locked body truth. Scene images do not change canon unless explicitly promoted. Accessories only appear when requested.
                        </p>
                      </div>
                    )}

                    {bodySlotsLoading && (
                      <div className="flex items-center gap-2 py-3 text-xs text-gray-500">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Loading body slots…
                      </div>
                    )}

                    {bodySlotsError && (
                      <p className="text-xs text-red-400">{bodySlotsError}</p>
                    )}

                    {/* Library picker sub-view */}
                    {bodySlotLibraryTarget && !bodySlotsLoading && (
                      <>
                        {galleryImages.length === 0 ? (
                          <p className="text-xs text-gray-500">No gallery images yet. Generate character images first.</p>
                        ) : bodySlotLibraryBusy ? (
                          <div className="flex items-center gap-2 py-3 text-xs text-gray-500">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                            Assigning…
                          </div>
                        ) : (
                          <div className="grid grid-cols-3 gap-2">
                            {galleryImages.map((img) => (
                              <button
                                key={img.id}
                                type="button"
                                onClick={() => handleBodySlotUseExisting(bodySlotLibraryTarget, img)}
                                className="rounded-lg overflow-hidden border border-gray-700 hover:border-violet-500 transition-colors"
                              >
                                <img
                                  src={resolveImageUrl(img.url)}
                                  alt=""
                                  className="w-full aspect-[2/3] object-cover"
                                />
                              </button>
                            ))}
                          </div>
                        )}
                      </>
                    )}

                    {/* Slot cards */}
                    {!bodySlotLibraryTarget && !bodySlotsLoading && !bodySlotsError && (
                      <div className="grid grid-cols-2 gap-3">
                        {(bodySlots.length > 0 ? bodySlots : [
                          { key: 'body_front', label: 'Body Front Reference', url: null, status: 'missing' as BodySlotStatus, prompt: null },
                          { key: 'body_three_quarter', label: 'Body 3/4 Reference', url: null, status: 'missing' as BodySlotStatus, prompt: null },
                          { key: 'body_back', label: 'Body Back Reference', url: null, status: 'missing' as BodySlotStatus, prompt: null },
                          { key: 'tattoo_layout', label: 'Tattoo / Marking Layout', url: null, status: 'missing' as BodySlotStatus, prompt: null },
                        ] as BodySlotEntry[]).map((bslot) => {
                          const slotBusy = bodySlotBusy[bslot.key];
                          const slotStatusNode = (s: BodySlotStatus) => {
                            if (s === 'locked') return (
                              <span className="flex items-center gap-1 text-xs text-emerald-400">
                                <CheckCircle2 className="w-3 h-3" />Locked
                              </span>
                            );
                            if (s === 'generated') return (
                              <span className="flex items-center gap-1 text-xs text-amber-400">
                                <AlertCircle className="w-3 h-3" />Generated
                              </span>
                            );
                            return (
                              <span className="flex items-center gap-1 text-xs text-gray-500">
                                <AlertCircle className="w-3 h-3" />Missing
                              </span>
                            );
                          };
                          return (
                            <div
                              key={bslot.key}
                              className="rounded-xl border border-gray-700/60 bg-gray-800/40 overflow-hidden"
                            >
                              <div className="aspect-square bg-gray-800 relative">
                                {bslot.url ? (
                                  <img
                                    src={resolveImageUrl(bslot.url)}
                                    alt={bslot.label}
                                    className="w-full h-full object-cover"
                                  />
                                ) : (
                                  <div className="w-full h-full flex items-center justify-center">
                                    <ImageIcon className="w-6 h-6 text-gray-600" />
                                  </div>
                                )}
                              </div>
                              <div className="px-2.5 py-2 space-y-1.5">
                                <div className="flex items-center justify-between gap-1">
                                  <span className="text-xs text-gray-400 truncate">{bslot.label}</span>
                                  {slotStatusNode(bslot.status)}
                                </div>
                                {character?.identity_health?.slots?.[bslot.key]?.stale && (
                                  <div className="flex items-start gap-1.5">
                                    <AlertTriangle className="w-3 h-3 text-amber-400 flex-shrink-0 mt-0.5" />
                                    <div>
                                      <p className="text-xs text-amber-400 font-medium leading-tight">Refresh recommended</p>
                                      <p className="text-xs text-gray-500 leading-tight">Character canon changed after this reference was created.</p>
                                    </div>
                                  </div>
                                )}
                                <div className="flex gap-1.5 flex-wrap">
                                  {/* Choose from Library — always available */}
                                  <button
                                    disabled={!!slotBusy}
                                    onClick={() => setBodySlotLibraryTarget(bslot.key)}
                                    className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-violet-700/30 text-violet-300 hover:bg-violet-700/50 disabled:opacity-50 transition-colors"
                                  >
                                    <Library className="w-3 h-3" />
                                    Library
                                  </button>
                                  {bslot.status === 'missing' && (
                                    <button
                                      disabled={!!slotBusy}
                                      onClick={() => handleBodySlotAction(bslot, 'generate')}
                                      className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-emerald-700/30 text-emerald-400 hover:bg-emerald-700/50 disabled:opacity-50 transition-colors"
                                    >
                                      {slotBusy === 'generate' ? <Loader2 className="w-3 h-3 animate-spin" /> : <ImageIcon className="w-3 h-3" />}
                                      Generate
                                    </button>
                                  )}
                                  {bslot.status === 'generated' && (
                                    <>
                                      <button
                                        disabled={!!slotBusy}
                                        onClick={() => handleBodySlotAction(bslot, 'lock')}
                                        className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-emerald-700/30 text-emerald-400 hover:bg-emerald-700/50 disabled:opacity-50 transition-colors"
                                      >
                                        {slotBusy === 'lock' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                                        Lock
                                      </button>
                                      <button
                                        disabled={!!slotBusy}
                                        onClick={() => handleBodySlotAction(bslot, 'replace')}
                                        className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-gray-700/60 text-gray-400 hover:bg-gray-600/60 disabled:opacity-50 transition-colors"
                                      >
                                        {slotBusy === 'replace' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                                        Regenerate
                                      </button>
                                    </>
                                  )}
                                  {bslot.status === 'locked' && (
                                    <button
                                      disabled={!!slotBusy}
                                      onClick={() => handleBodySlotAction(bslot, 'replace')}
                                      className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-gray-700/60 text-gray-400 hover:bg-gray-600/60 disabled:opacity-50 transition-colors"
                                    >
                                      {slotBusy === 'replace' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                                      Replace
                                    </button>
                                  )}
                                  {/* Admin-only import button for body_front and tattoo_layout */}
                                  {currentUser?.is_admin && (bslot.key === 'body_front' || bslot.key === 'tattoo_layout') && (
                                    <label className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-orange-900/30 text-orange-400 hover:bg-orange-900/50 cursor-pointer transition-colors">
                                      {adminImportBusy && adminImportSlot === bslot.key
                                        ? <Loader2 className="w-3 h-3 animate-spin" />
                                        : <ShieldCheck className="w-3 h-3" />}
                                      Import
                                      <input
                                        type="file"
                                        accept="image/png,image/jpeg,image/webp"
                                        className="hidden"
                                        onChange={(e) => {
                                          const f = e.target.files?.[0];
                                          if (f && (bslot.key === 'body_front' || bslot.key === 'tattoo_layout')) {
                                            setAdminImportSlot(bslot.key);
                                            handleAdminCanonImport(bslot.key, f);
                                          }
                                          e.target.value = '';
                                        }}
                                      />
                                    </label>
                                  )}
                                </div>
                                {adminImportError && adminImportSlot === bslot.key && (
                                  <p className="text-xs text-red-400">{adminImportError}</p>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  {/* ── Section 3: Body Canon ────────────────────────── */}
                  <div className="pt-2 border-t border-gray-700/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-white">Body Canon</h3>
                        {packStages && (
                          <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${
                            packStages.marks === 'locked' ? 'bg-emerald-900/40 text-emerald-400' :
                            packStages.marks === 'partial' ? 'bg-amber-900/40 text-amber-400' :
                            'bg-gray-700/60 text-gray-500'
                          }`}>
                            {packStages.marks}
                          </span>
                        )}
                      </div>
                      {bodyCanonLibraryTarget ? (
                        <button
                          onClick={() => setBodyCanonLibraryTarget(null)}
                          className="text-xs text-gray-400 hover:text-white flex items-center gap-1 transition-colors"
                        >
                          <ChevronLeft className="w-3 h-3" />Back
                        </button>
                      ) : (
                        <span className="text-xs text-gray-500">Locked tattoos, scars &amp; markings</span>
                      )}
                    </div>

                    {/* Body Canon library picker sub-view */}
                    {bodyCanonLibraryTarget && (
                      <>
                        <p className="text-xs text-gray-400">Select an image to use as the anchor for this marking.</p>
                        {galleryImages.length === 0 ? (
                          <p className="text-xs text-gray-500">No gallery images yet.</p>
                        ) : bodyCanonLibraryBusy ? (
                          <div className="flex items-center gap-2 py-3 text-xs text-gray-500">
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />Assigning…
                          </div>
                        ) : (
                          <div className="grid grid-cols-3 gap-2">
                            {galleryImages.map((img) => (
                              <button
                                key={img.id}
                                type="button"
                                onClick={() => handleBodyCanonLibraryAssign(img)}
                                className="rounded-lg overflow-hidden border border-gray-700 hover:border-violet-500 transition-colors"
                              >
                                <img src={resolveImageUrl(img.url)} alt="" className="w-full aspect-[2/3] object-cover" />
                              </button>
                            ))}
                          </div>
                        )}
                      </>
                    )}

                    {!bodyCanonLibraryTarget && bodyMarkingsLoading && (
                      <div className="flex items-center gap-2 py-3 text-xs text-gray-500">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        Loading markings…
                      </div>
                    )}

                    {!bodyCanonLibraryTarget && bodyMarkingsError && (
                      <p className="text-xs text-red-400">{bodyMarkingsError}</p>
                    )}

                    {!bodyCanonLibraryTarget && !bodyMarkingsLoading && !bodyMarkingsError && bodyMarkings.length === 0 && (
                      <p className="text-xs text-gray-500 leading-relaxed">
                        No permanent body markings yet. Tattoos and scars added from Style Shops will appear here as locked body truth.
                      </p>
                    )}

                    {!bodyCanonLibraryTarget && bodyMarkings.length > 0 && (
                      <div className="space-y-2">
                        {bodyMarkings.map((marking) => {
                          const busy = bodyAnchorBusy[marking.id];
                          const PLACEMENT_LABELS: Record<string, string> = {
                            left_upper_arm: 'Left Upper Arm', left_forearm: 'Left Forearm',
                            left_full_arm: 'Left Arm (Sleeve)', right_upper_arm: 'Right Upper Arm',
                            right_forearm: 'Right Forearm', right_full_arm: 'Right Arm (Sleeve)',
                            chest: 'Chest', upper_back: 'Upper Back', lower_back: 'Lower Back',
                            full_back: 'Full Back', neck: 'Neck', throat: 'Throat',
                          };
                          const TYPE_LABELS: Record<string, string> = {
                            tattoo: 'Tattoo', scar: 'Scar', burn: 'Burn', birthmark: 'Birthmark',
                          };
                          const anchorStatusNode = (status: MarkingAnchorStatus) => {
                            if (status === 'locked') return (
                              <span className="flex items-center gap-1 text-xs text-emerald-400">
                                <CheckCircle2 className="w-3 h-3" />Locked
                              </span>
                            );
                            if (status === 'generated') return (
                              <span className="flex items-center gap-1 text-xs text-amber-400">
                                <AlertCircle className="w-3 h-3" />Not locked
                              </span>
                            );
                            return (
                              <span className="flex items-center gap-1 text-xs text-gray-500">
                                <AlertCircle className="w-3 h-3" />No anchor
                              </span>
                            );
                          };
                          return (
                            <div
                              key={marking.id}
                              className="rounded-xl border border-gray-700/60 bg-gray-800/40 overflow-hidden"
                            >
                              {/* Anchor image */}
                              {marking.anchor_image_url && (
                                <div className="aspect-[3/1] bg-gray-800 overflow-hidden">
                                  <img
                                    src={marking.anchor_image_url}
                                    alt={PLACEMENT_LABELS[marking.placement] ?? marking.placement}
                                    className="w-full h-full object-cover"
                                  />
                                </div>
                              )}
                              {!marking.anchor_image_url && (
                                <div className="h-12 bg-gray-800/60 flex items-center justify-center">
                                  <ImageIcon className="w-5 h-5 text-gray-600" />
                                </div>
                              )}

                              {/* Info row */}
                              <div className="px-2.5 py-2 space-y-1.5">
                                <div className="flex items-center justify-between gap-2">
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    <span className="text-xs font-medium text-gray-300 bg-gray-700/60 px-1.5 py-0.5 rounded shrink-0">
                                      {TYPE_LABELS[marking.type] ?? marking.type}
                                    </span>
                                    <span className="text-xs text-gray-400 truncate">
                                      {PLACEMENT_LABELS[marking.placement] ?? marking.placement.replace(/_/g, ' ')}
                                    </span>
                                  </div>
                                  {anchorStatusNode(marking.anchor_status)}
                                </div>

                                <p className="text-xs text-gray-500 truncate">{marking.style}</p>

                                {/* Action buttons */}
                                <div className="flex gap-1.5 flex-wrap">
                                  {/* Choose from Library — always available */}
                                  <button
                                    disabled={!!busy}
                                    onClick={() => setBodyCanonLibraryTarget(marking.id)}
                                    className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-violet-700/30 text-violet-300 hover:bg-violet-700/50 disabled:opacity-50 transition-colors"
                                  >
                                    <Library className="w-3 h-3" />
                                    Library
                                  </button>
                                  {marking.anchor_status === 'missing' && (
                                    <button
                                      disabled={!!busy}
                                      onClick={() => handleBodyAnchorAction(marking, 'generate')}
                                      className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-emerald-700/30 text-emerald-400 hover:bg-emerald-700/50 disabled:opacity-50 transition-colors"
                                    >
                                      {busy === 'generate' ? <Loader2 className="w-3 h-3 animate-spin" /> : <ImageIcon className="w-3 h-3" />}
                                      Generate Anchor
                                    </button>
                                  )}
                                  {marking.anchor_status === 'generated' && (
                                    <>
                                      <button
                                        disabled={!!busy}
                                        onClick={() => handleBodyAnchorAction(marking, 'lock')}
                                        className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-emerald-700/30 text-emerald-400 hover:bg-emerald-700/50 disabled:opacity-50 transition-colors"
                                      >
                                        {busy === 'lock' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                                        Lock
                                      </button>
                                      <button
                                        disabled={!!busy}
                                        onClick={() => handleBodyAnchorAction(marking, 'replace')}
                                        className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-gray-700/60 text-gray-400 hover:bg-gray-600/60 disabled:opacity-50 transition-colors"
                                      >
                                        {busy === 'replace' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                                        Regenerate
                                      </button>
                                    </>
                                  )}
                                  {marking.anchor_status === 'locked' && (
                                    <button
                                      disabled={!!busy}
                                      onClick={() => handleBodyAnchorAction(marking, 'replace')}
                                      className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-gray-700/60 text-gray-400 hover:bg-gray-600/60 disabled:opacity-50 transition-colors"
                                    >
                                      {busy === 'replace' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                                      Replace
                                    </button>
                                  )}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* ── Pick view ──────────────────────────────────────── */}
              {evolveView === 'pick' && (
                <>
                  <p className="text-xs text-gray-400">
                    Select a candidate from your character's image gallery.
                  </p>

                  {evolveCreating || evolveValidating ? (
                    <div className="flex items-center justify-center py-10 text-gray-500 text-xs gap-2">
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      {evolveCreating ? 'Creating candidate…' : 'Validating…'}
                    </div>
                  ) : galleryImages.length === 0 ? (
                    <div className="text-center py-10 text-xs text-gray-500">
                      No images in gallery yet. Generate character images first.
                    </div>
                  ) : (
                    <div className="grid grid-cols-3 gap-2">
                      {galleryImages.map((img) => (
                        <button
                          key={img.id}
                          onClick={() => handleSelectCandidate(img)}
                          className="aspect-square rounded-lg overflow-hidden border border-gray-700 hover:border-emerald-500 transition-colors focus:outline-none focus:border-emerald-400"
                        >
                          <img
                            src={resolveImageUrl(img.url)}
                            alt={img.kind?.replace(/_/g, ' ') ?? ''}
                            className="w-full h-full object-cover"
                          />
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}

              {/* ── Confirm view ───────────────────────────────────── */}
              {evolveView === 'confirm' && evolveCandidate && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <p className="text-xs text-gray-500 text-center">Current</p>
                      <div className="aspect-square rounded-lg overflow-hidden bg-gray-800 border border-gray-700">
                        {parseSlotUrl(evolveCandidate.slot) ? (
                          <img
                            src={resolveImageUrl(parseSlotUrl(evolveCandidate.slot)!)}
                            alt="Current"
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center">
                            <Feather className="w-6 h-6 text-gray-600" />
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      <p className="text-xs text-emerald-400 text-center">Candidate</p>
                      <div className="aspect-square rounded-lg overflow-hidden bg-gray-800 border border-emerald-700/60">
                        <img
                          src={resolveImageUrl(evolveCandidate.image_url)}
                          alt="Candidate"
                          className="w-full h-full object-cover"
                        />
                      </div>
                    </div>
                  </div>

                  {/* Validation status */}
                  <div className={`rounded-lg px-3 py-2.5 border text-xs flex items-start gap-2 ${
                    evolveCandidate.validation_status === 'invalid'
                      ? 'bg-red-400/10 border-red-400/20 text-red-400'
                      : evolveCandidate.validation_status === 'warning'
                      ? 'bg-amber-400/10 border-amber-400/20 text-amber-300'
                      : 'bg-emerald-400/10 border-emerald-400/20 text-emerald-400'
                  }`}>
                    {evolveCandidate.validation_status === 'invalid' ? (
                      <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                    ) : evolveCandidate.validation_status === 'warning' ? (
                      <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                    ) : (
                      <ShieldCheck className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
                    )}
                    <div className="space-y-0.5">
                      <p className="font-medium capitalize">{evolveCandidate.validation_status}</p>
                      {evolveCandidate.validation_notes && (
                        <p className="opacity-80 leading-relaxed">{evolveCandidate.validation_notes}</p>
                      )}
                    </div>
                  </div>

                  {/* Rollback safety note */}
                  <div className="flex items-start gap-2 rounded-lg bg-gray-800/40 border border-gray-700/40 px-3 py-2.5">
                    <Lock className="w-3.5 h-3.5 text-emerald-500/70 flex-shrink-0 mt-0.5" />
                    <p className="text-xs text-gray-500 leading-relaxed">
                      Before promotion, your current identity state is automatically snapshotted.
                      Rollback is always available from the snapshots list.
                    </p>
                  </div>

                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={handleReject}
                      disabled={evolveRejecting || evolvePromoting}
                      className="flex-1 btn btn-secondary text-sm disabled:opacity-50"
                    >
                      {evolveRejecting ? (
                        <span className="flex items-center justify-center gap-1.5">
                          <RefreshCw className="w-3 h-3 animate-spin" /> Rejecting…
                        </span>
                      ) : 'Reject'}
                    </button>
                    <button
                      onClick={handlePromote}
                      disabled={
                        evolvePromoting || evolveRejecting ||
                        evolveCandidate.validation_status === 'invalid'
                      }
                      className="flex-1 btn btn-primary text-sm disabled:opacity-50"
                    >
                      {evolvePromoting ? (
                        <span className="flex items-center justify-center gap-1.5">
                          <RefreshCw className="w-3 h-3 animate-spin" /> Promoting…
                        </span>
                      ) : 'Promote to Canon'}
                    </button>
                  </div>
                </>
              )}

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
                    <li>All generated images (identity pack, moments)</li>
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
