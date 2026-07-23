/**
 * CanonManager — the single UI for managing a character's locked identity canon.
 *
 * Four sections only:
 *   A. Face Canon        — face identity lock (images + description)
 *   B. Body Canon        — anatomy + permanent body marks
 *   C. Removable Accessories — mask, jewellery, weapons etc.
 *   D. Scene Images      — output only, never canon
 *
 * Permanent tattoos and scars appear in Body Canon, not accessories.
 * Accessories only appear when the scene prompt requests them.
 * Scene images do not update canon.
 */
import { useState, useEffect, useCallback } from 'react';
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
  isAdmin: boolean;
  characterName?: string;
}

// ── Sub-components ────────────────────────────────────────────────────

function LockBadge({ locked }: { locked: boolean }) {
  if (locked) {
    return (
      <span className="flex items-center gap-1 text-xs text-gem font-medium">
        <CheckCircle2 className="w-3 h-3" />
        Locked
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-amber-400">
      <AlertCircle className="w-3 h-3" />
      Draft
    </span>
  );
}

function CanonImageSlot({
  label,
  url,
  slot,
  characterId,
  isAdmin,
  onUploaded,
}: {
  label: string;
  url: string | null;
  slot: string;
  characterId: number;
  isAdmin: boolean;
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
          <div className="flex flex-col items-center gap-2 text-ink-3">
            <Image className="w-6 h-6" />
            <span className="text-xs">Empty</span>
          </div>
        )}
        {busy && (
          <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-ink animate-spin" />
          </div>
        )}
      </div>
      {isAdmin && (
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
// canon for a permanent marking. Admin can upload/replace even after the body
// is locked (locked body truth still permits canon-edit corrections).
function MarkImageSlot({
  mark,
  characterId,
  isAdmin,
  onUploaded,
}: {
  mark: PermanentBodyMark;
  characterId: number;
  isAdmin: boolean;
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
      {isAdmin && (
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
  isAdmin,
  onRefresh,
}: {
  canon: CharacterCanon;
  characterId: number;
  isAdmin: boolean;
  onRefresh: () => void;
}) {
  const face = canon.face_canon;
  const [locking, setLocking] = useState(false);
  const [lockError, setLockError] = useState('');
  const [description, setDescription] = useState(face?.face_description ?? '');
  const [savingDesc, setSavingDesc] = useState(false);

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
    try {
      await apiClient.patchFaceCanon(characterId, { face_description: description });
      onRefresh();
    } finally {
      setSavingDesc(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-ink">Core Face Identity</h3>
          <p className="text-xs text-ink-3 mt-0.5">
            Face Canon controls the character&apos;s face identity. Scene images cannot change this.
          </p>
        </div>
        <LockBadge locked={canon.face_locked} />
      </div>

      {/* Face image slots */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: 'Front Face', slot: 'face_front', url: face?.face_front_image_url ?? null },
          { label: 'Left ¾', slot: 'face_left_3q', url: face?.face_left_3q_image_url ?? null },
          { label: 'Right ¾', slot: 'face_right_3q', url: face?.face_right_3q_image_url ?? null },
          { label: 'Profile', slot: 'face_profile', url: face?.face_profile_image_url ?? null },
          { label: 'Expression (optional)', slot: 'face_expression', url: face?.face_expression_image_url ?? null },
        ].map(({ label, slot, url }) => (
          <CanonImageSlot
            key={slot}
            label={label}
            url={url}
            slot={slot}
            characterId={characterId}
            isAdmin={isAdmin}
            onUploaded={onRefresh}
          />
        ))}
      </div>

      {/* Face description */}
      <div className="space-y-1.5">
        <label className="text-xs text-ink-2">Face description (for prompt)</label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          rows={2}
          disabled={canon.face_locked && !isAdmin}
          className="w-full text-xs bg-surface-elevated border border-edge-md rounded-lg px-3 py-2 text-ink resize-none focus:outline-none focus:ring-1 focus:ring-gem/40 disabled:opacity-50"
          placeholder="e.g. sharp angular jaw, dark brown eyes, olive skin"
        />
        <button
          onClick={saveDescription}
          disabled={savingDesc}
          className="text-xs text-ink-2 hover:text-ink transition-colors"
        >
          {savingDesc ? 'Saving…' : 'Save description'}
        </button>
      </div>

      {/* Lock button */}
      {!canon.face_locked && isAdmin && (
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
            <p className="text-xs text-ink-3 mt-1">Upload a front face image first.</p>
          )}
        </div>
      )}

      {canon.face_locked && (
        <div className="flex items-center gap-2 text-xs text-gem bg-gem-soft px-3 py-2 rounded-lg border border-gem/30">
          <Shield className="w-3 h-3" />
          Face Canon is locked. Scene images cannot alter this.
        </div>
      )}
    </div>
  );
}

// ── Section B: Body Canon ─────────────────────────────────────────────

function BodyCanonSection({
  canon,
  characterId,
  isAdmin,
  onRefresh,
}: {
  canon: CharacterCanon;
  characterId: number;
  isAdmin: boolean;
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
    // (for admins) the marking image, which is the primary visual truth.
    const missing: string[] = [];
    if (!markForm.label.trim()) missing.push('label');
    if (!markForm.body_region.trim()) missing.push('body region');
    if (isAdmin && !markFile) missing.push('marking image');
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
    try {
      await apiClient.removeCanonBodyMark(characterId, markId);
      onRefresh();
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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-ink">Body Canon</h3>
          <p className="text-xs text-ink-3 mt-0.5">
            Body Canon controls anatomy, proportions, scars, birthmarks, tattoos, and permanent body markings.
          </p>
        </div>
        <LockBadge locked={canon.body_locked} />
      </div>

      {/* Body image slots */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: 'Body Front', slot: 'body_front', url: body?.body_front_image_url ?? null },
          { label: 'Body Left', slot: 'body_left', url: body?.body_left_image_url ?? null },
          { label: 'Body Right', slot: 'body_right', url: body?.body_right_image_url ?? null },
          { label: 'Body Back', slot: 'body_back', url: body?.body_back_image_url ?? null },
          { label: 'Body Map', slot: 'body_map', url: body?.body_map_image_url ?? null },
          { label: 'Final Card (opt.)', slot: 'final_character_card', url: body?.final_character_card_image_url ?? null },
          { label: 'Torso Front', slot: 'torso_front', url: body?.torso_front_image_url ?? null },
          { label: 'Torso Side', slot: 'torso_side', url: body?.torso_side_image_url ?? null },
          { label: 'Standing Relaxed', slot: 'standing_relaxed', url: body?.standing_relaxed_image_url ?? null },
          { label: 'Seated Relaxed', slot: 'seated_relaxed', url: body?.seated_relaxed_image_url ?? null },
        ].map(({ label, slot, url }) => (
          <CanonImageSlot
            key={slot}
            label={label}
            url={url}
            slot={slot}
            characterId={characterId}
            isAdmin={isAdmin}
            onUploaded={onRefresh}
          />
        ))}
      </div>

      {/* Permanent body marks */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-ink">Permanent Body Markings</p>
          <p className="text-xs text-gem/80">Locked body truth — not accessories</p>
        </div>

        {(!body?.permanent_body_marks || body.permanent_body_marks.length === 0) && (
          <p className="text-xs text-ink-3">
            No permanent markings yet. Tattoos, scars, and birthmarks added here are locked body truth.
          </p>
        )}

        {body?.permanent_body_marks?.map(mark => (
          <div key={mark.id} className="border border-edge-md rounded-lg bg-surface-elevated overflow-hidden">
            <button
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
                <div className="pt-2">
                  <MarkImageSlot
                    mark={mark}
                    characterId={characterId}
                    isAdmin={isAdmin}
                    onUploaded={onRefresh}
                  />
                </div>
                {mark.description && mark.description !== mark.label && (
                  <p className="text-xs text-ink-2">{mark.description}</p>
                )}
                <p className="text-xs text-ink-3">Region: {mark.body_region}</p>
                {!canon.body_locked && (
                  <button
                    onClick={() => handleRemoveMark(mark.id)}
                    disabled={removingMark === mark.id}
                    className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300"
                  >
                    {removingMark === mark.id
                      ? <Loader2 className="w-3 h-3 animate-spin" />
                      : <Trash2 className="w-3 h-3" />
                    }
                    Remove
                  </button>
                )}
              </div>
            )}
          </div>
        ))}

        {/* Add mark — always available; marking edits are not gated by the
            body anatomy lock (only anatomy editing is). */}
        <div>
          {!showAddMark ? (
              <button
                onClick={() => { resetMarkForm(); setMarkError(''); setShowAddMark(true); }}
                className="flex items-center gap-1 text-xs text-ink-2 hover:text-ink transition-colors"
              >
                <Plus className="w-3 h-3" /> Add permanent marking
              </button>
            ) : (
              <div className="border border-edge-md rounded-lg p-3 space-y-2 bg-surface-elevated">
                <p className="text-xs font-medium text-ink">Add Permanent Body Mark</p>
                <input
                  value={markForm.label}
                  onChange={e => setMarkForm(f => ({ ...f, label: e.target.value }))}
                  placeholder="Label (e.g. Left gothic script sleeve)"
                  className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none focus:ring-1 focus:ring-gem/40"
                />
                <div className="grid grid-cols-2 gap-2">
                  <select
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
                <input
                  value={markForm.body_region}
                  onChange={e => setMarkForm(f => ({ ...f, body_region: e.target.value }))}
                  placeholder="Body region (e.g. left_full_arm)"
                  className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none"
                />
                {/* Image is the primary truth for the marking. */}
                {isAdmin && (
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
                <textarea
                  value={markForm.description}
                  onChange={e => setMarkForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="Notes (optional) — the uploaded image is the primary truth"
                  rows={2}
                  className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink resize-none focus:outline-none"
                />
                <p className="text-xs text-ink-3">
                  Required: label, body region{isAdmin ? ', marking image' : ''}.
                </p>
                {markError && <p className="text-xs text-red-400">{markError}</p>}
                <div className="flex gap-2">
                  {/* Always clickable (except while saving) so missing-field
                      validation is shown inline instead of failing silently. */}
                  <button
                    onClick={handleAddMark}
                    disabled={addingMark}
                    className="text-xs btn btn-primary"
                  >
                    {addingMark ? 'Adding…' : 'Add Mark'}
                  </button>
                  <button
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
      {!canon.body_locked && isAdmin && (
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
            <p className="text-xs text-ink-3 mt-1">Upload a body front image first.</p>
          )}
        </div>
      )}

      {canon.body_locked && (
        <div className="flex items-center gap-2 text-xs text-gem bg-gem-soft px-3 py-2 rounded-lg border border-gem/30">
          <Shield className="w-3 h-3" />
          Body Canon is locked. Permanent markings are anatomical truth.
        </div>
      )}
    </div>
  );
}

// ── Section C: Removable Accessories ─────────────────────────────────

function AccessoriesSection({
  canon,
  characterId,
  onRefresh,
}: {
  canon: CharacterCanon;
  characterId: number;
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
    try {
      await apiClient.removeCanonAccessory(characterId, id);
      onRefresh();
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Removable Accessories</h3>
        <p className="text-xs text-ink-3 mt-0.5">
          Accessories only appear when requested. They are not body canon.
        </p>
      </div>

      {canon.accessories.length === 0 && !showAdd && (
        <p className="text-xs text-ink-3">
          No accessories. Add mask, chain, jewellery, weapons, etc. — they only appear when the scene prompt requests them.
        </p>
      )}

      {canon.accessories.map(acc => (
        <div key={acc.id} className="border border-edge-md rounded-lg bg-surface-elevated p-2.5 space-y-1.5">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-xs font-medium text-ink">{acc.label}</span>
              <span className="ml-2 text-xs text-ink-3">{acc.type}</span>
            </div>
            <button
              onClick={() => handleRemove(acc.id)}
              disabled={removing === acc.id}
              className="text-ink-3 hover:text-red-400 transition-colors"
            >
              {removing === acc.id
                ? <Loader2 className="w-3 h-3 animate-spin" />
                : <Trash2 className="w-3 h-3" />
              }
            </button>
          </div>
          <p className="text-xs text-ink-2">{acc.description}</p>
          {acc.trigger_keywords.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {acc.trigger_keywords.map(kw => (
                <span key={kw} className="text-xs bg-surface-overlay text-ink-2 px-1.5 py-0.5 rounded">
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}

      {!showAdd ? (
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1 text-xs text-ink-2 hover:text-ink transition-colors"
        >
          <Plus className="w-3 h-3" /> Add accessory
        </button>
      ) : (
        <div className="border border-edge-md rounded-lg p-3 space-y-2 bg-surface-elevated">
          <p className="text-xs font-medium text-ink">Add Removable Accessory</p>
          <input
            value={form.label}
            onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
            placeholder="Label (e.g. Venetian mask)"
            className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none"
          />
          <select
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
            value={form.description}
            onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            placeholder="Prompt description (injected when triggered)"
            rows={2}
            className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink resize-none focus:outline-none"
          />
          <input
            value={form.trigger_keywords}
            onChange={e => setForm(f => ({ ...f, trigger_keywords: e.target.value }))}
            placeholder="Trigger keywords (comma-separated, e.g. mask, masked)"
            className="w-full text-xs bg-surface-elevated border border-edge-md rounded px-2.5 py-1.5 text-ink focus:outline-none"
          />
          {err && <p className="text-xs text-red-400">{err}</p>}
          <div className="flex gap-2">
            <button
              onClick={handleAdd}
              disabled={adding || !form.label || !form.description}
              className="text-xs btn btn-primary"
            >
              {adding ? 'Adding…' : 'Add Accessory'}
            </button>
            <button onClick={() => setShowAdd(false)} className="text-xs text-ink-3 hover:text-ink">
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

  const canGenerate = canon.face_locked || canon.body_locked;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">Scene Images</h3>
        <p className="text-xs text-ink-3 mt-0.5">
          Scene images are outputs only. They do not change canon.
        </p>
      </div>

      {!canGenerate && (
        <div className="text-xs text-amber-400 bg-amber-900/20 px-3 py-2 rounded-lg border border-amber-800/40">
          Lock at least Face Canon or Body Canon before generating scenes.
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

export default function CanonManager({ characterId, isOwner, isAdmin }: Props) {
  const [canon, setCanon] = useState<CharacterCanon | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('face');

  const load = useCallback(async () => {
    if (!isOwner) return;
    setLoading(true);
    setError('');
    try {
      const data = await apiClient.getIdentityCanon(characterId);
      setCanon(data as unknown as CharacterCanon);
    } catch {
      setError('Could not load character canon.');
    } finally {
      setLoading(false);
    }
  }, [characterId, isOwner]);

  useEffect(() => { load(); }, [load]);

  if (!isOwner) return null;

  const TABS: { id: Tab; label: string }[] = [
    { id: 'face', label: 'Face Canon' },
    { id: 'body', label: 'Body Canon' },
    { id: 'accessories', label: 'Accessories' },
    { id: 'scenes', label: 'Scene Images' },
  ];

  return (
    <div className="space-y-4">
      {/* Status bar */}
      {canon && (
        <div className="flex items-center gap-3 text-xs">
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
      )}

      {/* Tab nav */}
      <div className="flex gap-1 border-b border-edge-md pb-0">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-xs font-medium transition-colors rounded-t-lg ${
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
        <div className="flex items-center gap-2 text-xs text-ink-3 py-4">
          <Loader2 className="w-3 h-3 animate-spin" /> Loading canon…
        </div>
      )}
      {error && <p className="text-xs text-red-400">{error}</p>}

      {canon && (
        <div className="pt-2">
          {tab === 'face' && (
            <FaceCanonSection canon={canon} characterId={characterId} isAdmin={isAdmin} onRefresh={load} />
          )}
          {tab === 'body' && (
            <BodyCanonSection canon={canon} characterId={characterId} isAdmin={isAdmin} onRefresh={load} />
          )}
          {tab === 'accessories' && (
            <AccessoriesSection canon={canon} characterId={characterId} onRefresh={load} />
          )}
          {tab === 'scenes' && (
            <SceneImagesSection canon={canon} characterId={characterId} onRefresh={load} />
          )}
        </div>
      )}
    </div>
  );
}
