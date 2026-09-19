/**
 * CanonManager — the single UI for managing a character's identity canon.
 *
 * Character Canon is the persistent visual identity the owner establishes for
 * a character: face and body reference images, permanent marks, and the
 * accessories the character can be asked to wear. New images are guided by
 * it; images already generated are never rewritten by an edit here.
 *
 * Four sections only:
 *   A. Face             — face reference images (+ written notes)
 *   B. Body             — body reference images, marked-skin declarations,
 *                         permanent marks (tattoos, scars, birthmarks)
 *   C. Accessories      — signature removable items, keyword-triggered
 *   D. Scene Images     — output only, never canon. FOUNDER-ONLY (Phase 5.2,
 *                         PD-3): ordinary owners generate scenes through the
 *                         product's scene-image surface, not from here.
 *
 * Two audiences share these sections (Polish Phase 5.7). The ordinary owner
 * sees the reference imagery that exists, the details they can change, and
 * one status word; the founder additionally sees every reference slot with
 * upload/replace, the lock controls, and the technical lock state. Gating is
 * capability-based inside the shared components, never a second manager.
 *
 * What "locked" does in this repository (traced, Phase 5.7): the lock routes
 * set face_locked / body_locked (+ timestamps); once both are set the canon
 * status becomes "locked" and Character.visual_locked is mirrored true, which
 * is what the image generator's readiness guard and the legacy scene route
 * read. NOTHING is refused after a lock — descriptions, marks, accessories,
 * declarations and slot uploads all stay writable server-side. So "locked"
 * means "established and guiding new images", not "immutable", and the copy
 * here says exactly that (PD-B).
 *
 * Gating here is a UI affordance only. The scene-generation endpoint is
 * owner-authorised and metered by the weekly image allowance on the server,
 * so hiding this tab is a product decision, not the cost control.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Lock, Image, Plus, Trash2, CheckCircle2, AlertCircle,
  Loader2, Upload, ChevronDown, ChevronRight, Shield
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

// ── Types ─────────────────────────────────────────────────────────────

interface PermanentBodyMark {
  id: string;
  label: string;
  type: 'tattoo' | 'scar' | 'birthmark' | 'mole' | 'body_marking' | 'other';
  body_region: string;
  side: 'left' | 'right' | 'centre' | 'bilateral';
  description: string;
  reference_image_url: string | null;
  detail_crop_url: string | null;
  locked: boolean;
}

interface FaceCanon {
  face_front_image_url: string | null;
  face_left_3q_image_url: string | null;
  face_right_3q_image_url: string | null;
  face_profile_image_url: string | null;   // v2 (S24AK)
  face_expression_image_url: string | null;
  face_description: string | null;
  locked: boolean;
}

interface CardCoverage {
  coverage_type: string;
  visible_skin_regions: string[];
}

interface BodyCanon {
  body_front_image_url: string | null;
  body_left_image_url: string | null;
  body_right_image_url: string | null;
  body_back_image_url: string | null;
  body_map_image_url: string | null;
  final_character_card_image_url: string | null;
  torso_front_image_url: string | null;        // v2 (S24AK)
  torso_side_image_url: string | null;         // v2 (S24AK)
  standing_relaxed_image_url: string | null;   // v2 (S24AK)
  seated_relaxed_image_url: string | null;     // v2 (S24AK)
  height: string | null;
  build: string | null;
  skin_tone: string | null;
  body_description: string | null;
  permanent_body_marks: PermanentBodyMark[];
  // Per-card depicted skin coverage (PERMANENT-MARK CANON sprint).
  card_coverage?: Record<string, CardCoverage> | null;
  // Mark-location declaration: null/undefined = undeclared (legacy),
  // [] = explicitly unmarked, [...] = marks confined to these regions.
  marked_regions?: string[] | null;
  locked: boolean;
}

interface RemovableAccessory {
  id: string;
  label: string;
  type: string;
  description: string;
  trigger_keywords: string[];
  design_anchor_image_url: string | null;
  fit_anchor_image_url: string | null;
  locked: boolean;
}

interface CharacterCanon {
  id: number;
  character_id: number;
  status: 'draft' | 'locked';
  face_canon: FaceCanon | null;
  body_canon: BodyCanon | null;
  accessories: RemovableAccessory[];
  face_locked: boolean;
  body_locked: boolean;
  created_at: string;
  updated_at: string;
  locked_at: string | null;
}

interface Props {
  characterId: number;
  isOwner: boolean;
  /** Founder tier (admin OR seeder) — see `isFounder` in `@/lib/entitlements`.
   *  Gates the image-upload and lock controls. This was `isAdmin`, fed from the
   *  raw `is_admin` flag, which hid every upload control from the seeding
   *  account even though the server's image-ingress boundary admits it. A UI
   *  affordance only: the canon upload routes enforce the same predicate. */
  isFounder: boolean;
  characterName?: string;
  /** The owner-facing status as CharacterDetail knows it from the character
   *  row (Phase 5.7 addendum, B). One definition, shared with the launcher:
   *  'established' = visual_locked && has_identity_canon — the state in which
   *  the image generator's readiness guard admits the character AND the
   *  server has canon content to ground on; 'legacy' = visual_locked with no
   *  v2 canon (pre-canon character); 'unfinished' = everything else. When
   *  absent, the manager derives it from the canon alone. */
  ownerStatus?: OwnerStatus;
  /** Called once the owner has established the canon (both lock routes
   *  succeeded and the refreshed canon confirms it), so the page can re-read
   *  the character and its launcher agrees. */
  onEstablished?: () => void;
}

export type OwnerStatus = 'established' | 'unfinished' | 'legacy';

// ── Sub-components ────────────────────────────────────────────────────

/** Per-section lock flag — founders only, because for them the lock is a
 *  control they operate. Owners read ONE status word at the top of the
 *  manager (Phase 5.7 addendum, B): a per-section word could disagree with
 *  it in a partially-bridged legacy canon. Icon + word, never colour alone. */
function LockBadge({ locked, isFounder }: { locked: boolean; isFounder: boolean }) {
  if (!isFounder) return null;
  if (locked) {
    return (
      <span className="flex items-center gap-1 text-xs text-gem font-medium">
        <CheckCircle2 className="w-3 h-3" aria-hidden />
        Locked
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-amber-400">
      <AlertCircle className="w-3 h-3" aria-hidden />
      Draft
    </span>
  );
}

/** Reference slots an ordinary owner sees: only the ones that hold an image.
 *  An empty slot is a founder upload target; to an owner it is a box that
 *  says "Empty" and offers nothing (Phase 5.7). */
function visibleSlots<T extends { url: string | null }>(slots: T[], isFounder: boolean): T[] {
  return isFounder ? slots : slots.filter((s) => s.url !== null);
}

function CanonImageSlot({
  label,
  url,
  slot,
  characterId,
  isFounder,
  onUploaded,
}: {
  label: string;
  url: string | null;
  slot: string;
  characterId: number;
  isFounder: boolean;
  onUploaded: (url: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('slot', slot);
      const result = await apiClient.uploadCanonSlot(characterId, form);
      onUploaded(result.url as string);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setBusy(false);
      e.target.value = '';
    }
  }

  return (
    <div className="space-y-1.5">
      <p className="text-xs text-ink-2">{label}</p>
      <div className="rounded-lg border border-edge-md bg-surface-elevated overflow-hidden aspect-square flex items-center justify-center relative">
        {url ? (
          <img src={url} alt={label} className="w-full h-full object-cover" />
        ) : (
          /* Only a founder ever sees this: owners get populated slots only
             (visibleSlots). */
          <div className="flex flex-col items-center gap-2 text-ink-3">
            <Image className="w-6 h-6" aria-hidden />
            <span className="text-xs">Empty</span>
          </div>
        )}
        {busy && (
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-ink animate-spin" />
          </div>
        )}
      </div>
      {isFounder && (
        <label className="flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink cursor-pointer transition-colors">
          <Upload className="w-3 h-3" />
          {url ? 'Replace' : 'Upload'}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={handleFileChange}
            disabled={busy}
          />
        </label>
      )}
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

// Per-mark visual truth. The uploaded image — not prose — is the primary
// canon for a permanent marking. A founder can upload/replace even after the body
// is locked (locked body truth still permits canon-edit corrections).
function MarkImageSlot({
  mark,
  characterId,
  isFounder,
  onUploaded,
}: {
  mark: PermanentBodyMark;
  characterId: number;
  isFounder: boolean;
  onUploaded: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const url = mark.detail_crop_url || mark.reference_image_url;

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('slot', 'reference');
      await apiClient.uploadCanonMarkImage(characterId, mark.id, form);
      onUploaded();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setBusy(false);
      e.target.value = '';
    }
  }

  return (
    <div className="space-y-1.5">
      <div className="rounded-lg border border-edge-md bg-surface-elevated overflow-hidden aspect-square w-32 flex items-center justify-center relative">
        {url ? (
          <img src={url} alt={`${mark.label} marking`} className="w-full h-full object-cover" />
        ) : (
          <div className="flex flex-col items-center gap-1.5 text-ink-3">
            <Image className="w-5 h-5" />
            <span className="text-xs">No image</span>
          </div>
        )}
        {busy && (
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-ink animate-spin" />
          </div>
        )}
      </div>
      {isFounder && (
        <label className="flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink cursor-pointer transition-colors">
          <Upload className="w-3 h-3" />
          {url ? 'Replace marking image' : 'Upload marking image'}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={handleFileChange}
            disabled={busy}
          />
        </label>
      )}
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

// ── Section A: Face Canon ─────────────────────────────────────────────

function FaceCanonSection({
  canon,
  characterId,
  characterName,
  isFounder,
  onRefresh,
}: {
  canon: CharacterCanon;
  characterId: number;
  characterName: string;
  isFounder: boolean;
  onRefresh: () => void;
}) {
  const face = canon.face_canon;
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState('');
  const [description, setDescription] = useState(face?.face_description ?? '');
  const [savingDesc, setSavingDesc] = useState(false);
  const [descError, setDescError] = useState('');
  const [descSaved, setDescSaved] = useState(false);

  async function handleLock() {
    setLocking(true);
    setLockError('');
    try {
      await apiClient.lockFaceCanon(characterId);
      onRefresh();
    } catch (err: unknown) {
      setLockError(err instanceof Error ? err.message : 'Lock failed');
    } finally {
      setLocking(false);
    }
  }

  async function saveDescription() {
    setSavingDesc(true);
    setDescError('');
    setDescSaved(false);
    try {
      await apiClient.patchFaceCanon(characterId, { face_description: description });
      setDescSaved(true);
      onRefresh();
    } catch (err: unknown) {
      setDescError(err instanceof Error ? err.message : 'Could not save the notes.');
    } finally {
      setSavingDesc(false);
    }
  }

  const slots = visibleSlots([
    { label: 'Front', slot: 'face_front', url: face?.face_front_image_url ?? null },
    { label: 'Left ¾', slot: 'face_left_3q', url: face?.face_left_3q_image_url ?? null },
    { label: 'Right ¾', slot: 'face_right_3q', url: face?.face_right_3q_image_url ?? null },
    { label: 'Profile', slot: 'face_profile', url: face?.face_profile_image_url ?? null },
    { label: 'Expression', slot: 'face_expression', url: face?.face_expression_image_url ?? null },
  ], isFounder);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">Face</h3>
          <p className="text-xs text-ink-3 mt-0.5">
            The reference images that keep {characterName}&apos;s face consistent in new
            images. New images never change them.
          </p>
        </div>
        <LockBadge locked={canon.face_locked} isFounder={isFounder} />
      </div>

      {/* Face reference images. Owners see what exists; founders see every
          slot with upload/replace. */}
      {slots.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {slots.map(({ label, slot, url }) => (
            <CanonImageSlot
              key={slot}
              label={label}
              url={url}
              slot={slot}
              characterId={characterId}
              isFounder={isFounder}
              onUploaded={onRefresh}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-ink-3">
          No face references yet. They are made when {characterName}&apos;s setup is finished.
        </p>
      )}

      {/* Written face notes. Editable by the owner whatever the lock state —
          the server has never refused this field (patch_face_canon). Honest
          about reach: the image generator is guided by the reference images
          above; these notes feed the reference-set builder, not scene
          prompts (canon_compiler emits no canon prose). */}
      <div className="space-y-1.5">
        <label htmlFor={`face-notes-${characterId}`} className="block text-xs text-ink-2">
          Face notes
        </label>
        <textarea
          id={`face-notes-${characterId}`}
          value={description}
          onChange={e => { setDescription(e.target.value); setDescSaved(false); }}
          rows={2}
          className="w-full text-xs bg-surface-elevated border border-edge-md rounded-lg px-3 py-2 text-ink resize-none focus:outline-none focus:ring-1 focus:ring-gem/40"
          placeholder="e.g. sharp angular jaw, dark brown eyes, olive skin"
        />
        <p className="text-xs text-ink-3">
          Written notes kept with the reference set. New images are guided by the reference
          images above.
        </p>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={saveDescription}
            disabled={savingDesc}
            className="text-xs text-ink-2 hover:text-ink transition-colors"
          >
            {savingDesc ? 'Saving…' : 'Save notes'}
          </button>
          {descSaved && <span className="text-xs text-gem" role="status">Saved.</span>}
        </div>
        {descError && <p className="text-xs text-red-400" role="alert">{descError}</p>}
      </div>

      {/* Lock button */}
      {!canon.face_locked && isFounder && (
        <div className="pt-1">
          {lockError && <p className="text-xs text-red-400 mb-2">{lockError}</p>}
          <button
            onClick={handleLock}
            disabled={locking || !face?.face_front_image_url}
            className="flex items-center gap-2 text-xs btn btn-primary"
          >
            {locking ? <Loader2 className="w-3 h-3 animate-spin" /> : <Lock className="w-3 h-3" />}
            Lock Face Canon
          </button>
          {!face?.face_front_image_url && (
            <p className="text-xs text-ink-3 mt-1">Upload a front face image first (the server requires it).</p>
          )}
        </div>
      )}

      {/* Founder-only lock explainer. Says what the flag does (established;
          guides new images) and what it does not (freeze anything — every
          field stays writable, cf. canon_service). Owners get the one status
          line at the top of the manager instead of a repeat per section. */}
      {canon.face_locked && isFounder && (
        <div className="flex items-start gap-2 text-xs text-gem bg-gem-soft px-3 py-2 rounded-lg border border-gem/30">
          <Shield className="w-3 h-3 mt-0.5 shrink-0" aria-hidden />
          <span>
            Face is locked: it counts as established and guides new images. Slots and notes stay
            editable; edits affect future images only. Generated scenes never write back to it.
          </span>
        </div>
      )}
    </div>
  );
}

// ── Skin & Markings truth (PERMANENT-MARK CANON sprint) ───────────────
// Two simple declarations that give the Canon engine authoritative data:
//   1. marked_regions — WHERE this character's permanent marks exist at all
//      (everything else is clean skin the generator must not tattoo).
//   2. card_coverage — what skin each reference card actually shows, so a
//      bare-skinned card can never contaminate a clothed scene.
// Deliberately not an anatomy form: one checkbox row + one preset per card.

const MARKED_REGION_OPTIONS: { key: string; label: string }[] = [
  { key: 'torso',      label: 'Chest / torso' },
  { key: 'back',       label: 'Back' },
  { key: 'upper_arms', label: 'Upper arms' },
  { key: 'forearms',   label: 'Forearms' },
  { key: 'neck',       label: 'Neck' },
  { key: 'hands',      label: 'Hands / fingers' },
  { key: 'face',       label: 'Face' },
  { key: 'legs',       label: 'Legs' },
];

/** The human label for a marked-region key; unknown keys fall back to the key. */
function regionLabel(key: string): string {
  return MARKED_REGION_OPTIONS.find((o) => o.key === key)?.label ?? key;
}

const COVERAGE_PRESET_OPTIONS: { key: string; label: string }[] = [
  { key: '',              label: 'Not set' },
  { key: 'fully_clothed', label: 'Fully clothed' },
  { key: 'short_sleeves', label: 'Short sleeves' },
  { key: 'sleeveless',    label: 'Sleeveless' },
  { key: 'bare_torso',    label: 'Bare torso' },
  { key: 'shorts',        label: 'Shorts' },
  { key: 'swimwear',      label: 'Swimwear' },
];

// One label per body slot, shared by the reference grid and the coverage
// rows so an image is called the same thing everywhere. Matches the wording
// the read-only canon cards on CharacterDetail use (V2_SLOT_LABELS).
const BODY_SLOTS: { slot: string; label: string; field: keyof BodyCanon }[] = [
  { slot: 'body_front',           label: 'Body front',   field: 'body_front_image_url' },
  { slot: 'body_left',            label: 'Body left',    field: 'body_left_image_url' },
  { slot: 'body_right',           label: 'Body right',   field: 'body_right_image_url' },
  { slot: 'body_back',            label: 'Body back',    field: 'body_back_image_url' },
  { slot: 'body_map',             label: 'Body map',     field: 'body_map_image_url' },
  { slot: 'final_character_card', label: 'Character card', field: 'final_character_card_image_url' },
  { slot: 'torso_front',          label: 'Torso front',  field: 'torso_front_image_url' },
  { slot: 'torso_side',           label: 'Torso side',   field: 'torso_side_image_url' },
  { slot: 'standing_relaxed',     label: 'Standing',     field: 'standing_relaxed_image_url' },
  { slot: 'seated_relaxed',       label: 'Seated',       field: 'seated_relaxed_image_url' },
];

function SkinTruthSection({
  body,
  characterId,
  onRefresh,
}: {
  body: BodyCanon;
  characterId: number;
  onRefresh: () => void;
}) {
  const declared = body.marked_regions ?? null;
  const [regions, setRegions] = useState<Set<string>>(new Set(declared ?? []));
  const [declaring, setDeclaring] = useState(false);
  const [declareError, setDeclareError] = useState('');
  const [coverage, setCoverage] = useState<Record<string, string>>(() => {
    const out: Record<string, string> = {};
    for (const [slot, cov] of Object.entries(body.card_coverage ?? {})) {
      out[slot] = cov.coverage_type;
    }
    return out;
  });
  const [savingCoverage, setSavingCoverage] = useState(false);
  const [coverageError, setCoverageError] = useState('');
  const [expanded, setExpanded] = useState(false);

  // Resync local edit state whenever the SERVER value changes.
  //
  // Without this the checkboxes were initialised once and never again (a
  // useState initialiser does not re-run on prop change), while the collapsed
  // summary below always rendered the server value. The two could therefore
  // disagree — a region shown ticked while the summary omitted it, which is
  // exactly the "Hands/Fingers checked but missing from the summary" report.
  // The summary was right and the tick was a local, unsaved edit.
  const declaredKey = JSON.stringify(declared);
  const coverageKey = JSON.stringify(body.card_coverage ?? {});
  useEffect(() => {
    setRegions(new Set(declared ?? []));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [declaredKey]);
  useEffect(() => {
    const out: Record<string, string> = {};
    for (const [slot, cov] of Object.entries(body.card_coverage ?? {})) {
      out[slot] = cov.coverage_type;
    }
    setCoverage(out);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [coverageKey]);

  // Unsaved-change detection. This panel has two independent Save buttons, so
  // an edited-but-unsaved checkbox is easy to lose by saving the other block
  // or collapsing the panel — the likely path by which the hands declaration
  // was never persisted. Surface it instead of failing silently.
  const regionsDirty =
    declared === null
      ? regions.size > 0
      : JSON.stringify([...regions].sort()) !== JSON.stringify([...declared].sort());

  async function saveRegions() {
    setDeclaring(true);
    setDeclareError('');
    try {
      await apiClient.patchBodyCanon(characterId, {
        marked_regions: Array.from(regions),
      });
      onRefresh();
    } catch (err: unknown) {
      setDeclareError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setDeclaring(false);
    }
  }

  async function saveCoverage() {
    setSavingCoverage(true);
    setCoverageError('');
    try {
      const dict: Record<string, { coverage_type: string }> = {};
      for (const [slot, preset] of Object.entries(coverage)) {
        if (preset) dict[slot] = { coverage_type: preset };
      }
      await apiClient.patchBodyCanon(characterId, { card_coverage: dict });
      onRefresh();
    } catch (err: unknown) {
      setCoverageError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSavingCoverage(false);
    }
  }

  // Only offer coverage rows for reference images that exist.
  const presentSlots = BODY_SLOTS.filter(({ field }) => {
    const url = body[field];
    return typeof url === 'string' && url.length > 0;
  });

  return (
    <div className="border border-edge-md rounded-lg bg-surface-elevated">
      <button
        type="button"
        aria-expanded={expanded}
        className="w-full flex items-center justify-between p-2.5 text-left hover:bg-surface-overlay"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="min-w-0">
          <p className="text-xs font-medium text-ink">Where marks appear</p>
          <p className="text-xs text-ink-3 mt-0.5 break-words">
            {declared === null
              ? 'Not set — new images may put marks on any skin.'
              : declared.length === 0
                ? 'No permanent marks anywhere.'
                : `Marks only on: ${declared.map(regionLabel).join(', ')}`}
          </p>
        </div>
        {expanded
          ? <ChevronDown className="w-3 h-3 text-ink-3 shrink-0" />
          : <ChevronRight className="w-3 h-3 text-ink-3 shrink-0" />}
      </button>

      {expanded && (
        <div className="px-2.5 pb-2.5 space-y-3 border-t border-edge-md">
          {/* Marked regions declaration */}
          <div className="pt-2 space-y-1.5">
            <p className="text-xs font-medium text-ink">
              Where does this character have permanent marks?
            </p>
            <p className="text-xs text-ink-3">
              Anywhere you leave unticked is treated as clear skin in new images. Tick nothing
              to say the character has no permanent marks.
            </p>
            <div className="grid grid-cols-2 gap-1">
              {MARKED_REGION_OPTIONS.map(({ key, label }) => (
                <label key={key} className="flex items-center gap-1.5 text-xs text-ink-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={regions.has(key)}
                    onChange={e => {
                      const s = new Set(regions);
                      e.target.checked ? s.add(key) : s.delete(key);
                      setRegions(s);
                    }}
                  />
                  {label}
                </label>
              ))}
            </div>
            {declared === null && regions.size === 0 && (
              <p className="text-xs text-ink-3">
                Saving with nothing ticked records that this character has no permanent
                marks anywhere — different from leaving it unset.
              </p>
            )}
            {regionsDirty && (
              <p className="text-xs text-amber-400" role="status">
                Unsaved changes — press Save mark regions to apply them.
              </p>
            )}
            {declareError && <p className="text-xs text-red-400" role="alert">{declareError}</p>}
            <button
              type="button"
              onClick={saveRegions}
              disabled={declaring}
              className="text-xs btn btn-primary"
            >
              {declaring ? 'Saving…' : regionsDirty ? 'Save mark regions *' : 'Save mark regions'}
            </button>
          </div>

          {/* Per-card coverage */}
          {presentSlots.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-ink">
                What does each reference image show?
              </p>
              <p className="text-xs text-ink-3">
                Saying what each reference wears helps new images keep bare-skin references
                out of clothed scenes, and the other way round.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                {presentSlots.map(({ slot, label }) => (
                  <label key={slot} className="flex items-center justify-between gap-2 text-xs text-ink-2">
                    <span className="truncate">{label}</span>
                    <select
                      value={coverage[slot] ?? ''}
                      onChange={e => setCoverage(c => ({ ...c, [slot]: e.target.value }))}
                      className="text-xs bg-surface-elevated border border-edge-md rounded px-1.5 py-1 text-ink"
                    >
                      {COVERAGE_PRESET_OPTIONS.map(({ key, label: l }) => (
                        <option key={key} value={key}>{l}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              {coverageError && <p className="text-xs text-red-400" role="alert">{coverageError}</p>}
              <button
                type="button"
                onClick={saveCoverage}
                disabled={savingCoverage}
                className="text-xs btn btn-primary"
              >
                {savingCoverage ? 'Saving…' : 'Save what references show'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Section B: Body Canon ─────────────────────────────────────────────

function BodyCanonSection({
  canon,
  characterId,
  characterName,
  isFounder,
  onRefresh,
}: {
  canon: CharacterCanon;
  characterId: number;
  characterName: string;
  isFounder: boolean;
  onRefresh: () => void;
}) {
  const body = canon.body_canon;
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState('');
  const [showAddMark, setShowAddMark] = useState(false);
  const [markForm, setMarkForm] = useState({
    label: '', type: 'tattoo', body_region: '', side: 'left', description: '',
  });
  const [markFile, setMarkFile] = useState<File | null>(null);
  const [addingMark, setAddingMark] = useState(false);
  const [markError, setMarkError] = useState('');
  const [removingMark, setRemovingMark] = useState<string | null>(null);
  const [expandedMarks, setExpandedMarks] = useState<Set<string>>(new Set());

  async function handleLock() {
    setLocking(true);
    setLockError('');
    try {
      await apiClient.lockBodyCanon(characterId);
      onRefresh();
    } catch (err: unknown) {
      setLockError(err instanceof Error ? err.message : 'Lock failed');
    } finally {
      setLocking(false);
    }
  }

  function resetMarkForm() {
    setMarkForm({ label: '', type: 'tattoo', body_region: '', side: 'left', description: '' });
    setMarkFile(null);
  }

  async function handleAddMark() {
    // Inline validation — never silently fail. Required: label, region, and
    // (for founders) the marking image, which is the primary visual truth.
    const missing: string[] = [];
    if (!markForm.label.trim()) missing.push('label');
    if (!markForm.body_region.trim()) missing.push('body region');
    if (isFounder && !markFile) missing.push('marking image');
    if (missing.length > 0) {
      setMarkError(`Please add: ${missing.join(', ')}.`);
      return;
    }

    // Snapshot this submission's image so a later edit to the shared form state
    // cannot reassign it to a different mark — each mark owns its own image.
    const fileForThisMark = markFile;
    setAddingMark(true);
    setMarkError('');
    try {
      // The image is the primary truth; notes are optional. Fall back to the
      // label so the description field (which backend requires) is never prose-heavy.
      const payload = {
        ...markForm,
        description: markForm.description.trim() || markForm.label.trim(),
      };
      const result = await apiClient.addCanonBodyMark(characterId, payload);
      // Create-then-upload: the upload endpoint needs the new mark's id.
      const mark = (result as { mark?: { id?: string } }).mark;
      if (!mark?.id) {
        throw new Error('Mark was not created — no id returned.');
      }
      if (fileForThisMark) {
        const form = new FormData();
        form.append('file', fileForThisMark);
        form.append('slot', 'reference');
        await apiClient.uploadCanonMarkImage(characterId, mark.id, form);
      }
      resetMarkForm();
      setShowAddMark(false);
      onRefresh();
    } catch (err: unknown) {
      setMarkError(err instanceof Error ? err.message : 'Failed to add mark');
    } finally {
      setAddingMark(false);
    }
  }

  async function handleRemoveMark(markId: string) {
    setRemovingMark(markId);
    setMarkError('');
    try {
      await apiClient.removeCanonBodyMark(characterId, markId);
      onRefresh();
    } catch (err: unknown) {
      setMarkError(err instanceof Error ? err.message : 'Could not remove the mark.');
    } finally {
      setRemovingMark(null);
    }
  }

  const TYPE_LABELS: Record<string, string> = {
    tattoo: 'Tattoo', scar: 'Scar', birthmark: 'Birthmark',
    mole: 'Mole', body_marking: 'Body Marking', other: 'Other',
  };
  const SIDE_LABELS: Record<string, string> = {
    left: 'Left side', right: 'Right side', centre: 'Centre', bilateral: 'Bilateral',
  };

  const slots = visibleSlots(
    BODY_SLOTS.map(({ slot, label, field }) => ({ slot, label, url: body?.[field] as string | null ?? null })),
    isFounder,
  );

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-ink">Body</h3>
          <p className="text-xs text-ink-3 mt-0.5">
            {characterName}&apos;s body references, plus permanent marks such as tattoos, scars
            and birthmarks.
          </p>
        </div>
        <LockBadge locked={canon.body_locked} isFounder={isFounder} />
      </div>

      {/* Body reference images. Owners see what exists; founders see every
          slot with upload/replace. */}
      {slots.length > 0 ? (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {slots.map(({ label, slot, url }) => (
            <CanonImageSlot
              key={slot}
              label={label}
              url={url}
              slot={slot}
              characterId={characterId}
              isFounder={isFounder}
              onUploaded={onRefresh}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-ink-3">
          No body references yet. They are made when {characterName}&apos;s setup is finished.
        </p>
      )}

      {/* Marked-skin declarations — where marks may appear, and what each
          reference wears. Owner-editable; both feed the compiled prompt
          (canon_compiler occlusion / clean-skin clauses). */}
      {body && (
        <SkinTruthSection
          body={body}
          characterId={characterId}
          onRefresh={onRefresh}
        />
      )}

      {/* Permanent marks. Owner-managed: add, inspect, remove. The
          consequence sentence lives here, once, where an edit is made. */}
      <div className="space-y-2">
        <div>
          <p className="text-xs font-medium text-ink">Permanent marks</p>
          <p className="text-xs text-ink-3 mt-0.5">
            Tattoos, scars, birthmarks — persistent details that guide new images of {characterName}.
            Changes here affect future images only; images already made are not altered.
          </p>
        </div>

        {(!body?.permanent_body_marks || body.permanent_body_marks.length === 0) && (
          <p className="text-xs text-ink-3">No permanent marks yet.</p>
        )}

        {body?.permanent_body_marks?.map(mark => (
          <div key={mark.id} className="border border-edge-md rounded-lg bg-surface-elevated overflow-hidden">
            <button
              type="button"
              aria-expanded={expandedMarks.has(mark.id)}
              className="w-full flex items-center justify-between p-2.5 text-left hover:bg-surface-overlay"
              onClick={() => {
                const s = new Set(expandedMarks);
                s.has(mark.id) ? s.delete(mark.id) : s.add(mark.id);
                setExpandedMarks(s);
              }}
            >
              <div className="flex items-center gap-2 min-w-0">
                {(mark.detail_crop_url || mark.reference_image_url) ? (
                  <img
                    src={mark.detail_crop_url || mark.reference_image_url || ''}
                    alt=""
                    className="w-6 h-6 rounded object-cover border border-edge-md shrink-0"
                  />
                ) : (
                  <span className="w-6 h-6 rounded bg-surface-overlay flex items-center justify-center shrink-0">
                    <Image className="w-3 h-3 text-ink-3" />
                  </span>
                )}
                <span className="text-xs font-medium bg-surface-overlay text-ink-2 px-1.5 py-0.5 rounded shrink-0">
                  {TYPE_LABELS[mark.type] ?? mark.type}
                </span>
                <span className="text-xs text-ink truncate">{mark.label}</span>
                <span className="text-xs text-ink-3 shrink-0">{SIDE_LABELS[mark.side]}</span>
              </div>
              <div className="flex items-center gap-2">
                {expandedMarks.has(mark.id)
                  ? <ChevronDown className="w-3 h-3 text-ink-3" />
                  : <ChevronRight className="w-3 h-3 text-ink-3" />
                }
              </div>
            </button>
            {expandedMarks.has(mark.id) && (
              <div className="px-2.5 pb-2.5 space-y-2 border-t border-edge-md">
                {/* The mark's image: shown when it exists; the empty slot is
                    a founder upload target and is hidden from owners. */}
                {(isFounder || mark.detail_crop_url || mark.reference_image_url) && (
                  <div className="pt-2">
                    <MarkImageSlot
                      mark={mark}
                      characterId={characterId}
                      isFounder={isFounder}
                      onUploaded={onRefresh}
                    />
                  </div>
                )}
                {mark.description && mark.description !== mark.label && (
                  <p className="text-xs text-ink-2 break-words">{mark.description}</p>
                )}
                <p className="text-xs text-ink-3">Region: {mark.body_region.replace(/_/g, ' ')}</p>
                {/* Remove is offered whatever the lock state: the server has
                    never refused it (delete_mark), and every finished
                    character is locked — gating this on the lock left owners
                    able to add a mark but never to take one back. */}
                <button
                  type="button"
                  onClick={() => handleRemoveMark(mark.id)}
                  disabled={removingMark === mark.id}
                  className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300"
                >
                  {removingMark === mark.id
                    ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden />
                    : <Trash2 className="w-3 h-3" aria-hidden />
                  }
                  Remove {mark.label}
                </button>
              </div>
            )}
          </div>
        ))}

        {/* Add mark — always available; mark edits are not gated by the
            lock (nothing is, server-side). */}
        <div>
          {markError && !showAddMark && <p className="text-xs text-red-400 mb-2" role="alert">{markError}</p>}
          {!showAddMark ? (
              <button
                type="button"
                onClick={() => { resetMarkForm(); setMarkError(''); setShowAddMark(true); }}
                className="flex items-center gap-1 text-xs text-ink-2 hover:text-ink transition-colors"
              >
                <Plus className="w-3 h-3" aria-hidden /> Add permanent mark
              </button>
            ) : (
              <div className="border border-edge-md rounded-lg p-3 space-y-2 bg-surface-elevated">
                <p className="text-xs font-medium text-ink">Add permanent mark</p>
                <input
                  aria-label="Mark name"
                  value={markForm.label}
                  onChange={e => setMarkForm(f => ({ ...f, label: e.target.value }))}
                  placeholder="Name (e.g. Left gothic script sleeve)"
                  className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none focus:ring-1 focus:ring-gem/40"
                />
                <div className="grid grid-cols-2 gap-2">
                  <select
                    aria-label="Mark type"
                    value={markForm.type}
                    onChange={e => setMarkForm(f => ({ ...f, type: e.target.value }))}
                    className="text-xs bg-surface-elevated border border-edge-md rounded px-2 py-1.5 text-ink"
                  >
                    <option value="tattoo">Tattoo</option>
                    <option value="scar">Scar</option>
                    <option value="birthmark">Birthmark</option>
                    <option value="mole">Mole</option>
                    <option value="body_marking">Body Marking</option>
                    <option value="other">Other</option>
                  </select>
                  <select
                    aria-label="Side"
                    value={markForm.side}
                    onChange={e => setMarkForm(f => ({ ...f, side: e.target.value }))}
                    className="text-xs bg-surface-elevated border border-edge-md rounded px-2 py-1.5 text-ink"
                  >
                    <option value="left">Left side</option>
                    <option value="right">Right side</option>
                    <option value="centre">Centre</option>
                    <option value="bilateral">Bilateral</option>
                  </select>
                </div>
                {/* Canonical regions only — free text here was how unmappable
                    regions entered canon and silently disabled routing and
                    clean-skin authority for the whole character. */}
                <select
                  aria-label="Body region"
                  value={markForm.body_region}
                  onChange={e => setMarkForm(f => ({ ...f, body_region: e.target.value }))}
                  className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none"
                >
                  <option value="">Body region…</option>
                  <optgroup label="Torso">
                    <option value="chest">Chest</option>
                    <option value="sternum">Sternum</option>
                    <option value="abdomen">Abdomen</option>
                    <option value="ribs">Ribs</option>
                    <option value="back">Back</option>
                  </optgroup>
                  <optgroup label="Arms">
                    <option value="left_full_arm">Left full arm (sleeve)</option>
                    <option value="right_full_arm">Right full arm (sleeve)</option>
                    <option value="left_upper_arm">Left upper arm</option>
                    <option value="right_upper_arm">Right upper arm</option>
                    <option value="left_forearm">Left forearm</option>
                    <option value="right_forearm">Right forearm</option>
                  </optgroup>
                  <optgroup label="Neck & head">
                    <option value="neck">Neck</option>
                    <option value="throat">Throat</option>
                    <option value="left_cheek">Left cheek</option>
                    <option value="right_cheek">Right cheek</option>
                    <option value="forehead">Forehead</option>
                    <option value="jaw">Jaw</option>
                  </optgroup>
                  <optgroup label="Hands">
                    <option value="left_hand">Left hand</option>
                    <option value="right_hand">Right hand</option>
                    <option value="knuckles">Knuckles</option>
                  </optgroup>
                  <optgroup label="Legs">
                    <option value="left_thigh">Left thigh</option>
                    <option value="right_thigh">Right thigh</option>
                    <option value="left_calf">Left calf</option>
                    <option value="right_calf">Right calf</option>
                  </optgroup>
                </select>
                {/* Image is the primary truth for the marking. */}
                {isFounder && (
                  <label className="flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink cursor-pointer border border-dashed border-edge-md rounded px-2.5 py-2 transition-colors">
                    <Upload className="w-3 h-3 shrink-0" />
                    <span className="truncate">
                      {markFile ? markFile.name : 'Marking image (required) — the visual truth'}
                    </span>
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="hidden"
                      onChange={e => setMarkFile(e.target.files?.[0] ?? null)}
                    />
                  </label>
                )}
                {/* For an owner the description IS what guides new images (no
                    image travels with the mark — add_mark docstring); for a
                    founder the uploaded image leads. Say the true thing to each. */}
                <textarea
                  aria-label="Mark description"
                  value={markForm.description}
                  onChange={e => setMarkForm(f => ({ ...f, description: e.target.value }))}
                  placeholder={isFounder
                    ? 'Notes (optional) — the uploaded image is the primary truth'
                    : 'Describe it (recommended — this is what guides new images)'}
                  rows={2}
                  className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink resize-none focus:outline-none"
                />
                <p className="text-xs text-ink-3">
                  Required: name, body region{isFounder ? ', marking image' : ''}.
                </p>
                {markError && <p className="text-xs text-red-400" role="alert">{markError}</p>}
                <div className="flex gap-2">
                  {/* Always clickable (except while saving) so missing-field
                      validation is shown inline instead of failing silently. */}
                  <button
                    type="button"
                    onClick={handleAddMark}
                    disabled={addingMark}
                    className="text-xs btn btn-primary"
                  >
                    {addingMark ? 'Adding…' : 'Add mark'}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setShowAddMark(false); resetMarkForm(); setMarkError(''); }}
                    className="text-xs text-ink-3 hover:text-ink"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
        </div>
      </div>

      {/* Lock button */}
      {!canon.body_locked && isFounder && (
        <div className="pt-1">
          {lockError && <p className="text-xs text-red-400 mb-2">{lockError}</p>}
          <button
            onClick={handleLock}
            disabled={locking || !body?.body_front_image_url}
            className="flex items-center gap-2 text-xs btn btn-primary"
          >
            {locking ? <Loader2 className="w-3 h-3 animate-spin" /> : <Lock className="w-3 h-3" />}
            Lock Body Canon
          </button>
          {!body?.body_front_image_url && (
            <p className="text-xs text-ink-3 mt-1">Upload a body front image first (the server requires it).</p>
          )}
        </div>
      )}

      {/* Founder-only lock explainer — see the Face section note. */}
      {canon.body_locked && isFounder && (
        <div className="flex items-start gap-2 text-xs text-gem bg-gem-soft px-3 py-2 rounded-lg border border-gem/30">
          <Shield className="w-3 h-3 mt-0.5 shrink-0" aria-hidden />
          <span>
            Body is locked: it counts as established and guides new images. Slots, marks and
            declarations stay editable; edits affect future images only.
          </span>
        </div>
      )}
    </div>
  );
}

// ── Section C: Removable Accessories ─────────────────────────────────

function AccessoriesSection({
  canon,
  characterId,
  characterName,
  onRefresh,
}: {
  canon: CharacterCanon;
  characterId: number;
  characterName: string;
  onRefresh: () => void;
}) {
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    label: '', type: 'mask', description: '', trigger_keywords: '',
  });
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [err, setErr] = useState('');

  async function handleAdd() {
    setAdding(true);
    setErr('');
    try {
      const keywords = form.trigger_keywords.split(',').map(k => k.trim()).filter(Boolean);
      await apiClient.addCanonAccessory(characterId, {
        label: form.label,
        type: form.type,
        description: form.description,
        trigger_keywords: keywords,
      });
      setForm({ label: '', type: 'mask', description: '', trigger_keywords: '' });
      setShowAdd(false);
      onRefresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed');
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(id: string) {
    setRemoving(id);
    setErr('');
    try {
      await apiClient.removeCanonAccessory(characterId, id);
      onRefresh();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Could not remove the accessory.');
    } finally {
      setRemoving(null);
    }
  }

  const TYPE_LABELS: Record<string, string> = {
    mask: 'Mask', jewellery: 'Jewellery', weapon: 'Weapon',
    glasses: 'Glasses', clothing: 'Clothing item', other: 'Other',
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Accessories</h3>
        {/* True to the data model: RemovableAccessory carries trigger
            keywords and a description; canon_compiler adds "wearing …" only
            when a keyword appears in the prompt. Not a wardrobe, and never
            guaranteed in every image. */}
        <p className="text-xs text-ink-3 mt-0.5">
          Signature items {characterName} can wear — a mask, glasses, jewellery, a weapon. One
          appears in a new image only when your prompt uses one of its keywords.
        </p>
      </div>

      {canon.accessories.length === 0 && !showAdd && (
        <p className="text-xs text-ink-3">No accessories yet.</p>
      )}

      {canon.accessories.map(acc => (
        <div key={acc.id} className="border border-edge-md rounded-lg bg-surface-elevated p-2.5 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <span className="text-xs font-medium text-ink break-words">{acc.label}</span>
              <span className="ml-2 text-xs text-ink-3">{TYPE_LABELS[acc.type] ?? acc.type}</span>
            </div>
            <button
              type="button"
              aria-label={`Remove ${acc.label}`}
              onClick={() => handleRemove(acc.id)}
              disabled={removing === acc.id}
              className="text-ink-3 hover:text-red-400 transition-colors shrink-0"
            >
              {removing === acc.id
                ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden />
                : <Trash2 className="w-3 h-3" aria-hidden />
              }
            </button>
          </div>
          <p className="text-xs text-ink-2 break-words">{acc.description}</p>
          {acc.trigger_keywords.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-xs text-ink-3">Appears when you write:</span>
              {acc.trigger_keywords.map(kw => (
                <span key={kw} className="text-xs bg-surface-overlay text-ink-2 px-1.5 py-0.5 rounded">
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}

      {err && !showAdd && <p className="text-xs text-red-400" role="alert">{err}</p>}

      {!showAdd ? (
        <button
          type="button"
          onClick={() => { setErr(''); setShowAdd(true); }}
          className="flex items-center gap-1 text-xs text-ink-2 hover:text-ink transition-colors"
        >
          <Plus className="w-3 h-3" aria-hidden /> Add accessory
        </button>
      ) : (
        <div className="border border-edge-md rounded-lg p-3 space-y-2 bg-surface-elevated">
          <p className="text-xs font-medium text-ink">Add accessory</p>
          <input
            aria-label="Accessory name"
            value={form.label}
            onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
            placeholder="Name (e.g. Venetian mask)"
            className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none"
          />
          <select
            aria-label="Accessory type"
            value={form.type}
            onChange={e => setForm(f => ({ ...f, type: e.target.value }))}
            className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2 py-1.5 text-ink"
          >
            <option value="mask">Mask</option>
            <option value="jewellery">Jewellery</option>
            <option value="weapon">Weapon</option>
            <option value="glasses">Glasses</option>
            <option value="clothing">Clothing item</option>
            <option value="other">Other</option>
          </select>
          <textarea
            aria-label="How it looks"
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="How it looks (e.g. gold filigree Venetian half-mask)"
            rows={2}
            className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink resize-none focus:outline-none"
          />
          <input
            aria-label="Keywords that bring it in"
            value={form.trigger_keywords}
            onChange={e => setForm(f => ({ ...f, trigger_keywords: e.target.value }))}
            placeholder="Words that bring it in, comma-separated (e.g. mask, masked)"
            className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none"
          />
          {err && <p className="text-xs text-red-400" role="alert">{err}</p>}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={handleAdd}
              disabled={adding || !form.label || !form.description}
              className="text-xs btn btn-primary"
            >
              {adding ? 'Adding…' : 'Add accessory'}
            </button>
            <button type="button" onClick={() => setShowAdd(false)} className="text-xs text-ink-3 hover:text-ink">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Section D: Scene Images ───────────────────────────────────────────

function SceneImagesSection({
  canon,
  characterId,
  onRefresh,
}: {
  canon: CharacterCanon;
  characterId: number;
  onRefresh: () => void;
}) {
  const [prompt, setPrompt] = useState('');
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState('');
  const [lastImage, setLastImage] = useState<{ url: string; id: number } | null>(null);

  async function handleGenerate() {
    if (!prompt.trim()) return;
    setGenerating(true);
    setGenError('');
    setLastImage(null);
    try {
      const result = await apiClient.generateCanonScene(characterId, { prompt });
      setLastImage({ url: result.url as string, id: result.id as number });
      onRefresh();
    } catch (err: unknown) {
      setGenError(err instanceof Error ? err.message : 'Generation failed');
    } finally {
      setGenerating(false);
    }
  }

  // Neither section locked. This is information, not a gate: the server has
  // never required a lock on this route — it grounds on whatever face/body
  // content exists, locked or draft, and runs the prompt alone when there is
  // none. The old banner ("Lock at least Face Canon or Body Canon before
  // generating scenes") described a rule nothing enforced, so it is gone.
  const nothingLocked = !canon.face_locked && !canon.body_locked;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Scene Images</h3>
        <p className="text-xs text-ink-3 mt-0.5">
          Founder tool. Scene images are outputs only. They do not change canon.
        </p>
      </div>

      {nothingLocked && (
        <div className="text-xs text-amber-400 bg-amber-900/20 px-3 py-2 rounded-lg border border-amber-800/40">
          Face Canon and Body Canon are both still draft. Scenes will still generate — they use whatever canon content exists so far, and the prompt alone if there is none.
        </div>
      )}

      <div className="space-y-2">
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          rows={2}
          placeholder='e.g. "Leonardo standing on a beach in daylight"'
          className="w-full text-xs bg-surface-elevated border border-edge-md rounded-lg px-3 py-2 text-ink resize-none focus:outline-none focus:ring-1 focus:ring-gem/40"
        />
        <button
          onClick={handleGenerate}
          disabled={generating || !prompt.trim()}
          className="flex items-center gap-2 text-xs btn btn-primary"
        >
          {generating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Image className="w-3 h-3" />}
          Generate Scene
        </button>
        {genError && <p className="text-xs text-red-400">{genError}</p>}
      </div>

      {lastImage && (
        <div className="rounded-lg overflow-hidden border border-edge-md">
          <img src={lastImage.url} alt="Generated scene" className="w-full" />
          <div className="px-3 py-2 bg-surface-elevated text-xs text-ink-2">
            Scene image #{lastImage.id} — not canon
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main CanonManager ─────────────────────────────────────────────────

type Tab = 'face' | 'body' | 'accessories' | 'scenes';

/** Tabs every owner sees. `scenes` is appended for founders only (PD-3). */
const OWNER_TABS: { id: Tab; label: string }[] = [
  { id: 'face', label: 'Face' },
  { id: 'body', label: 'Body' },
  { id: 'accessories', label: 'Accessories' },
];
const FOUNDER_TABS: { id: Tab; label: string }[] = [
  ...OWNER_TABS,
  { id: 'scenes', label: 'Scene Images' },
];
const DEFAULT_TAB: Tab = 'face';

/** A fully-locked canon. Locking both sections is what mirrors
 *  Character.visual_locked true (canon_service._maybe_lock_full_canon), and
 *  a lock requires the front image — so this implies the character-row
 *  definition of established, and is the manager's own evidence for it in
 *  the moment after the owner establishes, before the page has re-read the
 *  character. */
function canonFullyLocked(canon: CharacterCanon): boolean {
  return canon.face_locked && canon.body_locked;
}

/**
 * The owner's status line, and — in exactly one state — the action that
 * changes it (Phase 5.7 addendum, A).
 *
 * "Establish Character Canon" is offered when the canon holds what the two
 * owner-authorised lock routes require (face_front and body_front images,
 * the routes' only precondition: lock_face_canon / lock_body_canon raise
 * 409 without them) and is not yet fully locked. It calls those same
 * routes, one per section still unlocked, then re-reads the canon and
 * reports from THAT — never from the fact that a call returned. A lock is
 * idempotent server-side, so a retry after a partial failure only repeats
 * the section that failed. No provider is involved: a lock writes flags.
 *
 * Every other not-established state gets a truthful line and the path
 * that actually exists — nothing here invents a recovery.
 */
function OwnerStatusLine({
  canon,
  characterId,
  name,
  ownerStatus,
  onRefresh,
  onEstablished,
}: {
  canon: CharacterCanon;
  characterId: number;
  name: string;
  ownerStatus: OwnerStatus;
  onRefresh: () => Promise<void>;
  onEstablished?: () => void;
}) {
  const [establishing, setEstablishing] = useState(false);
  const [establishError, setEstablishError] = useState('');
  const established = ownerStatus === 'established' || canonFullyLocked(canon);
  const hasFaceFront = !!canon.face_canon?.face_front_image_url;
  const hasBodyFront = !!canon.body_canon?.body_front_image_url;
  const canEstablish = !established && ownerStatus !== 'legacy' && hasFaceFront && hasBodyFront;

  async function establish() {
    if (establishing) return;
    setEstablishing(true);
    setEstablishError('');
    const failures: string[] = [];
    // Only the sections still unlocked, in the creation flow's order.
    if (!canon.face_locked) {
      try { await apiClient.lockFaceCanon(characterId); }
      catch (err: unknown) { failures.push(`face: ${err instanceof Error ? err.message : 'failed'}`); }
    }
    if (!canon.body_locked) {
      try { await apiClient.lockBodyCanon(characterId); }
      catch (err: unknown) { failures.push(`body: ${err instanceof Error ? err.message : 'failed'}`); }
    }
    // The server's state is the report, whatever the calls said.
    await onRefresh();
    setEstablishing(false);
    if (failures.length > 0) {
      setEstablishError(`Could not establish ${name}'s canon (${failures.join('; ')}). Try again.`);
      return;
    }
    onEstablished?.();
  }

  const word = established ? 'Established' : ownerStatus === 'legacy' ? 'Needs attention' : 'In progress';
  const tone = established ? 'bg-gem-soft text-gem' : 'bg-surface-overlay text-ink-2';

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs">
        <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full font-medium ${tone}`}>
          {established
            ? <CheckCircle2 className="w-3 h-3" aria-hidden />
            : <AlertCircle className="w-3 h-3" aria-hidden />}
          {word}
        </span>
      </div>

      {established && (
        <p className="text-xs text-ink-3">
          {name}&apos;s Character Canon guides every new image. You can still change what is here;
          changes affect future images, not ones already made.
        </p>
      )}

      {!established && ownerStatus === 'legacy' && (
        /* Pre-canon character: visual_locked without a v2 canon. The lock
           routes need a face_front image this canon does not hold, and the
           image generator needs canon content the server does not have, so
           there is no self-serve step. Say so; do not call it established. */
        <p className="text-xs text-ink-3">
          {name} was set up before Character Canon existed and has no reference images here, so
          Ficshon can&apos;t generate new images of them until their canon is rebuilt. Contact
          Ficshon and we&apos;ll sort it out.
        </p>
      )}

      {!established && ownerStatus !== 'legacy' && canEstablish && (
        <div className="rounded-lg border border-gem/30 bg-gem-soft/40 p-3 space-y-2">
          <p className="text-xs text-ink">
            {name}&apos;s reference images are ready, but their Character Canon isn&apos;t established
            yet, so images of them can&apos;t be generated.
          </p>
          <p className="text-xs text-ink-3">
            Establishing it makes {name}&apos;s current visual identity ready to guide new images.
            You can still edit the canon afterwards; changes affect future images only.
          </p>
          <button
            type="button"
            onClick={establish}
            disabled={establishing}
            className="text-xs btn btn-primary flex items-center gap-2"
          >
            {establishing ? <Loader2 className="w-3 h-3 animate-spin" aria-hidden /> : <CheckCircle2 className="w-3 h-3" aria-hidden />}
            {establishing ? 'Establishing…' : 'Establish Character Canon'}
          </button>
          {establishError && <p className="text-xs text-red-400" role="alert">{establishError}</p>}
        </div>
      )}

      {!established && ownerStatus !== 'legacy' && !canEstablish && hasFaceFront && (
        /* The pack wrote the face but stopped before the body front image,
           which the body lock route requires. No route rebuilds one card. */
        <p className="text-xs text-ink-3">
          {name}&apos;s reference set is incomplete — their face was made but their body reference
          wasn&apos;t — so their Character Canon can&apos;t be established yet and images of them
          can&apos;t be generated. Contact Ficshon and we&apos;ll finish it.
        </p>
      )}

      {!established && ownerStatus !== 'legacy' && !hasFaceFront && (
        <p className="text-xs text-ink-3">
          {name}&apos;s Character Canon isn&apos;t established yet, so images of them can&apos;t be
          generated. Finish their setup from the Characters page.
        </p>
      )}
    </div>
  );
}

export default function CanonManager({
  characterId, isOwner, isFounder, characterName, ownerStatus, onEstablished,
}: Props) {
  const [canon, setCanon] = useState<CharacterCanon | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedTab, setSelectedTab] = useState<Tab>(DEFAULT_TAB);
  const name = characterName || 'this character';

  // Every fetch carries a sequence number; only the newest may land. Without
  // this, character A's canon (slow) could arrive after character B's (fast)
  // and be shown under B's name (Phase 5.7).
  const loadSeq = useRef(0);
  const load = useCallback(async () => {
    if (!isOwner) return;
    const seq = ++loadSeq.current;
    setLoading(true);
    setError('');
    try {
      const data = await apiClient.getIdentityCanon(characterId);
      if (seq !== loadSeq.current) return;
      setCanon(data as unknown as CharacterCanon);
    } catch {
      if (seq !== loadSeq.current) return;
      setError('Could not load character canon.');
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, [characterId, isOwner]);

  // A new character (or lost ownership) drops the previous canon at once —
  // nothing of character A is on screen while B loads.
  useEffect(() => {
    setCanon(null);
    setError('');
  }, [characterId, isOwner]);

  useEffect(() => { load(); }, [load]);

  if (!isOwner) return null;

  const TABS = isFounder ? FOUNDER_TABS : OWNER_TABS;
  // The rendered tab is derived, never trusted from state alone: if the
  // selection names a tab this viewer cannot see (a founder-only tab held in
  // state when `isFounder` flips, or any future stale value) the view falls
  // back to the default owner section instead of rendering hidden content.
  const tab: Tab = TABS.some(t => t.id === selectedTab) ? selectedTab : DEFAULT_TAB;
  const panelId = `canon-panel-${characterId}`;

  return (
    <div className="space-y-4">
      {/* Status. Owner: one word plus what it means. Founder: the lock flags
          themselves, since the founder operates them. */}
      {canon && (isFounder ? (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`px-2 py-0.5 rounded-full font-medium ${
            canon.status === 'locked'
              ? 'bg-gem-soft text-gem'
              : 'bg-surface-overlay text-ink-2'
          }`}>
            Canon: {canon.status}
          </span>
          <span className={`px-2 py-0.5 rounded-full ${
            canon.face_locked ? 'bg-gem-soft text-gem' : 'bg-surface-overlay text-ink-3'
          }`}>
            Face: {canon.face_locked ? 'locked' : 'draft'}
          </span>
          <span className={`px-2 py-0.5 rounded-full ${
            canon.body_locked ? 'bg-gem-soft text-gem' : 'bg-surface-overlay text-ink-3'
          }`}>
            Body: {canon.body_locked ? 'locked' : 'draft'}
          </span>
        </div>
      ) : (
        <OwnerStatusLine
          key={characterId}
          canon={canon}
          characterId={characterId}
          name={name}
          ownerStatus={ownerStatus ?? (canonFullyLocked(canon) ? 'established' : 'unfinished')}
          onRefresh={load}
          onEstablished={onEstablished}
        />
      ))}

      {/* Tab nav */}
      <div role="tablist" aria-label="Character Canon sections" className="flex gap-1 border-b border-edge-md pb-0 overflow-x-auto">
        {TABS.map(t => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`canon-tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={panelId}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setSelectedTab(t.id)}
            className={`px-3 py-2 text-xs font-medium whitespace-nowrap transition-colors rounded-t-lg ${
              tab === t.id
                ? 'text-ink border-b-2 border-gem/50 -mb-px'
                : 'text-ink-3 hover:text-ink-2'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-ink-3 py-4" role="status">
          <Loader2 className="w-3 h-3 animate-spin" aria-hidden /> Loading canon…
        </div>
      )}
      {error && <p className="text-xs text-red-400" role="alert">{error}</p>}

      {/* Sections are keyed by character so their local edit state (a notes
          draft, a half-filled mark form) never carries from one character to
          the next. */}
      {canon && (
        <div id={panelId} role="tabpanel" aria-labelledby={`canon-tab-${tab}`} className="pt-2">
          {tab === 'face' && (
            <FaceCanonSection key={characterId} canon={canon} characterId={characterId} characterName={name} isFounder={isFounder} onRefresh={load} />
          )}
          {tab === 'body' && (
            <BodyCanonSection key={characterId} canon={canon} characterId={characterId} characterName={name} isFounder={isFounder} onRefresh={load} />
          )}
          {tab === 'accessories' && (
            <AccessoriesSection key={characterId} canon={canon} characterId={characterId} characterName={name} onRefresh={load} />
          )}
          {/* Belt and braces with the tab fallback above: the founder check is
              repeated at the render site so no tab-state path can mount this. */}
          {tab === 'scenes' && isFounder && (
            <SceneImagesSection key={characterId} canon={canon} characterId={characterId} onRefresh={load} />
          )}
        </div>
      )}
    </div>
  );
}
