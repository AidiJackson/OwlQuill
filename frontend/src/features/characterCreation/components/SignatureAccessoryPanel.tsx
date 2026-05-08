import { useState, useMemo } from 'react';
import { Lock, ChevronDown, Pencil, Image as ImageIcon } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { Character } from '@/lib/types';

// ── Types ─────────────────────────────────────────────────────────────

interface Accessory {
  id: string;
  type: string;
  name: string;
  description: string;
  visual_rules: string[];
  anchor_image_url?: string | null;
  anchor_status?: 'none' | 'generated' | 'locked';
  anchor_prompt?: string | null;
  anchor_created_at?: string | null;
  fit_anchor_image_url?: string | null;
  fit_anchor_status?: 'none' | 'generated' | 'locked';
  fit_anchor_prompt?: string | null;
  locked: boolean;
}

const ACCESSORY_TYPES = [
  { value: 'mask',      label: 'Mask' },
  { value: 'tattoo',    label: 'Tattoo' },
  { value: 'jewellery', label: 'Jewellery' },
  { value: 'weapon',    label: 'Weapon' },
  { value: 'scar',      label: 'Scar' },
  { value: 'other',     label: 'Other' },
] as const;

// ── Helpers ───────────────────────────────────────────────────────────

function parseAccessories(identityAnchorJson: string | null | undefined): Accessory[] {
  if (!identityAnchorJson) return [];
  try {
    const data = JSON.parse(identityAnchorJson);
    return Array.isArray(data.accessories) ? data.accessories : [];
  } catch {
    return [];
  }
}

function resolveImageUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  return `/${url.replace(/^\//, '')}`;
}

function patchAccessoryInJson(
  identityAnchorJson: string | null | undefined,
  updatedAccessory: Record<string, unknown>,
): string {
  const base = identityAnchorJson ? JSON.parse(identityAnchorJson) : {};
  const accessories: Accessory[] = Array.isArray(base.accessories) ? base.accessories : [];
  const idx = accessories.findIndex((a) => a.id === updatedAccessory.id);
  if (idx >= 0) {
    accessories[idx] = updatedAccessory as unknown as Accessory;
  }
  return JSON.stringify({ ...base, accessories });
}

// ── Component ─────────────────────────────────────────────────────────

interface Props {
  character: Character;
  onSaved: (updatedJson: string) => void;
}

export default function SignatureAccessoryPanel({ character, onSaved }: Props) {
  const accessories = useMemo(
    () => parseAccessories(character.identity_anchor_json),
    [character.identity_anchor_json],
  );

  const [editing, setEditing] = useState(false);
  const [type, setType] = useState<string>('mask');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [visualRulesRaw, setVisualRulesRaw] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  // v2 object anchor state
  const [generatingAnchorId, setGeneratingAnchorId] = useState<string | null>(null);
  const [lockingAnchorId, setLockingAnchorId] = useState<string | null>(null);
  const [anchorError, setAnchorError] = useState<Record<string, string>>({});

  // v2 fit anchor state
  const [generatingFitAnchorId, setGeneratingFitAnchorId] = useState<string | null>(null);
  const [lockingFitAnchorId, setLockingFitAnchorId] = useState<string | null>(null);
  const [fitAnchorError, setFitAnchorError] = useState<Record<string, string>>({});

  const showForm = accessories.length === 0 || editing;

  const handleStartEdit = (acc: Accessory) => {
    setType(acc.type);
    setName(acc.name);
    setDescription(acc.description);
    setVisualRulesRaw(acc.visual_rules.join('\n'));
    setEditing(true);
    setError('');
    setSuccess(false);
  };

  const handleSave = async () => {
    const trimmedName = name.trim();
    const trimmedDesc = description.trim();
    if (!trimmedName || !trimmedDesc) {
      setError('Name and description are required.');
      return;
    }
    const visual_rules = visualRulesRaw
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);

    setSaving(true);
    setError('');
    try {
      const result = await apiClient.saveIdentityAccessory(character.id, {
        type,
        name: trimmedName,
        description: trimmedDesc,
        visual_rules,
      });
      // Rebuild the anchor JSON client-side so the parent can update without a re-fetch
      const existing = character.identity_anchor_json
        ? JSON.parse(character.identity_anchor_json)
        : {};
      const updatedJson = JSON.stringify({ ...existing, accessories: result.accessories });
      onSaved(updatedJson);
      setEditing(false);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save accessory.');
    } finally {
      setSaving(false);
    }
  };

  const handleGenerateAnchor = async (accId: string) => {
    setGeneratingAnchorId(accId);
    setAnchorError((prev) => ({ ...prev, [accId]: '' }));
    try {
      const result = await apiClient.generateAccessoryAnchor(character.id, accId);
      const updatedJson = patchAccessoryInJson(character.identity_anchor_json, result.accessory);
      onSaved(updatedJson);
    } catch (err) {
      setAnchorError((prev) => ({
        ...prev,
        [accId]: err instanceof Error ? err.message : 'Failed to generate anchor.',
      }));
    } finally {
      setGeneratingAnchorId(null);
    }
  };

  const handleLockAnchor = async (accId: string) => {
    setLockingAnchorId(accId);
    setAnchorError((prev) => ({ ...prev, [accId]: '' }));
    try {
      const result = await apiClient.lockAccessoryAnchor(character.id, accId);
      const updatedJson = patchAccessoryInJson(character.identity_anchor_json, result.accessory);
      onSaved(updatedJson);
    } catch (err) {
      setAnchorError((prev) => ({
        ...prev,
        [accId]: err instanceof Error ? err.message : 'Failed to lock anchor.',
      }));
    } finally {
      setLockingAnchorId(null);
    }
  };

  const handleGenerateFitAnchor = async (accId: string) => {
    setGeneratingFitAnchorId(accId);
    setFitAnchorError((prev) => ({ ...prev, [accId]: '' }));
    try {
      const result = await apiClient.generateFitAnchor(character.id, accId);
      const updatedJson = patchAccessoryInJson(character.identity_anchor_json, result.accessory);
      onSaved(updatedJson);
    } catch (err) {
      setFitAnchorError((prev) => ({
        ...prev,
        [accId]: err instanceof Error ? err.message : 'Failed to generate fit anchor.',
      }));
    } finally {
      setGeneratingFitAnchorId(null);
    }
  };

  const handleLockFitAnchor = async (accId: string) => {
    setLockingFitAnchorId(accId);
    setFitAnchorError((prev) => ({ ...prev, [accId]: '' }));
    try {
      const result = await apiClient.lockFitAnchor(character.id, accId);
      const updatedJson = patchAccessoryInJson(character.identity_anchor_json, result.accessory);
      onSaved(updatedJson);
    } catch (err) {
      setFitAnchorError((prev) => ({
        ...prev,
        [accId]: err instanceof Error ? err.message : 'Failed to lock fit anchor.',
      }));
    } finally {
      setLockingFitAnchorId(null);
    }
  };

  const handleCancel = () => {
    setEditing(false);
    setError('');
  };

  return (
    <div className="border-t border-gray-800 pt-6 space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-medium text-gray-300">Signature Accessory</h2>
        <span className="text-xs text-gray-600 font-normal">(v2)</span>
      </div>

      {/* Saved list ─────────────────────────────────────────────────── */}
      {!showForm && accessories.map((acc) => (
        <div
          key={acc.id}
          className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-2"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-900/40 border border-emerald-800/50 text-emerald-400/80 capitalize">
                  {acc.type}
                </span>
                <Lock className="w-3 h-3 text-emerald-500/60" />
              </div>
              <p className="text-sm font-medium text-gray-200">{acc.name}</p>
              <p className="text-xs text-gray-400 leading-relaxed">{acc.description}</p>
              {acc.visual_rules.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {acc.visual_rules.map((rule, i) => (
                    <li key={i} className="text-xs text-gray-500 flex gap-1.5">
                      <span className="text-gray-700 select-none">–</span>
                      {rule}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <button
              onClick={() => handleStartEdit(acc)}
              className="flex-shrink-0 text-gray-600 hover:text-gray-400 transition-colors p-1"
              aria-label="Edit accessory"
            >
              <Pencil className="w-3.5 h-3.5" />
            </button>
          </div>
          {/* v2 Object anchor section (design reference only — not used for scene generation) */}
          <div className="pt-2 border-t border-gray-800/50 space-y-2">
            <p className="text-xs text-gray-600 font-medium">Design anchor (object view)</p>
            {acc.anchor_status === 'locked' && acc.anchor_image_url ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <Lock className="w-3 h-3 text-emerald-500" />
                  <span className="text-xs text-emerald-400 font-medium">Design Anchor Locked</span>
                </div>
                <img
                  src={resolveImageUrl(acc.anchor_image_url)}
                  alt={`${acc.name} design anchor`}
                  className="w-20 h-20 object-cover rounded border border-gray-700"
                />
              </div>
            ) : acc.anchor_status === 'generated' && acc.anchor_image_url ? (
              <div className="space-y-2">
                <p className="text-xs text-amber-400/80">Design anchor generated — preview below. Lock it to save.</p>
                <img
                  src={resolveImageUrl(acc.anchor_image_url)}
                  alt={`${acc.name} design anchor preview`}
                  className="w-20 h-20 object-cover rounded border border-gray-700"
                />
                {anchorError[acc.id] && (
                  <p className="text-xs text-red-400">{anchorError[acc.id]}</p>
                )}
                <button
                  onClick={() => handleLockAnchor(acc.id)}
                  disabled={lockingAnchorId === acc.id}
                  className="flex items-center gap-1.5 text-xs text-emerald-400 border border-emerald-800/60 rounded px-2.5 py-1.5 hover:bg-emerald-900/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Lock className="w-3 h-3" />
                  {lockingAnchorId === acc.id ? 'Locking…' : 'Lock Design Anchor'}
                </button>
              </div>
            ) : (
              <div className="space-y-1.5">
                {anchorError[acc.id] && (
                  <p className="text-xs text-red-400">{anchorError[acc.id]}</p>
                )}
                <button
                  onClick={() => handleGenerateAnchor(acc.id)}
                  disabled={generatingAnchorId === acc.id}
                  className="flex items-center gap-1.5 text-xs text-gray-400 border border-gray-700 rounded px-2.5 py-1.5 hover:border-gray-500 hover:text-gray-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ImageIcon className="w-3 h-3" />
                  {generatingAnchorId === acc.id ? 'Generating…' : 'Generate Design Anchor'}
                </button>
              </div>
            )}
          </div>

          {/* v2 Fit anchor section (worn portrait — used for scene generation) */}
          <div className="pt-2 border-t border-gray-800/50 space-y-2">
            <p className="text-xs text-gray-600 font-medium">Fit anchor (worn portrait)</p>
            <p className="text-xs text-gray-600">
              Portrait of the character wearing the accessory correctly. Used as the scene reference instead of the design anchor.
            </p>
            {acc.fit_anchor_status === 'locked' && acc.fit_anchor_image_url ? (
              <div className="space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <Lock className="w-3 h-3 text-emerald-500" />
                  <span className="text-xs text-emerald-400 font-medium">Fit Anchor Locked</span>
                </div>
                <img
                  src={resolveImageUrl(acc.fit_anchor_image_url)}
                  alt={`${acc.name} fit anchor`}
                  className="w-20 h-20 object-cover rounded border border-gray-700"
                />
              </div>
            ) : acc.fit_anchor_status === 'generated' && acc.fit_anchor_image_url ? (
              <div className="space-y-2">
                <p className="text-xs text-amber-400/80">Fit anchor generated — confirm the mask is fitted correctly, then lock.</p>
                <img
                  src={resolveImageUrl(acc.fit_anchor_image_url)}
                  alt={`${acc.name} fit anchor preview`}
                  className="w-20 h-20 object-cover rounded border border-gray-700"
                />
                {fitAnchorError[acc.id] && (
                  <p className="text-xs text-red-400">{fitAnchorError[acc.id]}</p>
                )}
                <button
                  onClick={() => handleLockFitAnchor(acc.id)}
                  disabled={lockingFitAnchorId === acc.id}
                  className="flex items-center gap-1.5 text-xs text-emerald-400 border border-emerald-800/60 rounded px-2.5 py-1.5 hover:bg-emerald-900/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Lock className="w-3 h-3" />
                  {lockingFitAnchorId === acc.id ? 'Locking…' : 'Lock Fit Anchor'}
                </button>
              </div>
            ) : (
              <div className="space-y-1.5">
                {fitAnchorError[acc.id] && (
                  <p className="text-xs text-red-400">{fitAnchorError[acc.id]}</p>
                )}
                <button
                  onClick={() => handleGenerateFitAnchor(acc.id)}
                  disabled={generatingFitAnchorId === acc.id}
                  className="flex items-center gap-1.5 text-xs text-gray-400 border border-gray-700 rounded px-2.5 py-1.5 hover:border-gray-500 hover:text-gray-300 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <ImageIcon className="w-3 h-3" />
                  {generatingFitAnchorId === acc.id ? 'Generating…' : 'Generate Fit Anchor'}
                </button>
              </div>
            )}
          </div>

          <p className="text-xs text-gray-600">
            Only injected when your image prompt mentions this accessory.
          </p>
        </div>
      ))}

      {/* Success flash ───────────────────────────────────────────────── */}
      {success && (
        <p className="text-xs text-emerald-400 bg-emerald-900/20 border border-emerald-800/40 rounded px-3 py-2">
          Accessory locked.
        </p>
      )}

      {/* Form ────────────────────────────────────────────────────────── */}
      {showForm && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 space-y-4">
          {/* Type */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 font-medium">Type</label>
            <div className="relative">
              <select
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full appearance-none bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-emerald-700 pr-8"
              >
                {ACCESSORY_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none" />
            </div>
          </div>

          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 font-medium">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Leonardo's Mask"
              maxLength={100}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-emerald-700"
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 font-medium">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g. matte black half-face tactical mask with subtle wolf-like contours, dark metallic edges, covers lower face and nose bridge, leaves eyes visible, no logos, no bright colors"
              maxLength={500}
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-emerald-700 resize-none"
            />
          </div>

          {/* Visual rules */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 font-medium">
              Visual rules{' '}
              <span className="text-gray-600 font-normal">(one per line, optional)</span>
            </label>
            <textarea
              value={visualRulesRaw}
              onChange={(e) => setVisualRulesRaw(e.target.value)}
              placeholder={'matte black surface, no shine\nwolf-like contour on cheekbones\ncovers lower face and nose bridge only'}
              rows={3}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-emerald-700 resize-none font-mono text-xs"
            />
          </div>

          {/* Info note */}
          <p className="text-xs text-gray-500 leading-relaxed">
            This accessory will only appear when your image prompt asks for it — e.g. "wearing his mask". It will not affect unmasked images.
          </p>

          {/* Error */}
          {error && (
            <p className="text-xs text-red-400 bg-red-400/10 rounded px-3 py-2">{error}</p>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={saving}
              className="btn btn-primary text-sm flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Lock className="w-3.5 h-3.5" />
              {saving ? 'Locking…' : 'Lock Signature Accessory'}
            </button>
            {editing && (
              <button
                onClick={handleCancel}
                disabled={saving}
                className="btn btn-secondary text-sm"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
