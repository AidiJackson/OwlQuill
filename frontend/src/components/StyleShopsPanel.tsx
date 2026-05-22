import { useState, useEffect, useCallback } from 'react';
import { X, Scissors, Pen, VenetianMask, Gem, Sword, Check, Trash2, ChevronRight } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import type { ShopType, StylePreset, StyleElementRead } from '@/lib/types';

interface Props {
  characterId: number;
  isOwner: boolean;
}

const SHOPS: { type: ShopType; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { type: 'barber', label: 'Barber', icon: Scissors },
  { type: 'tattoo', label: 'Tattoo Parlour', icon: Pen },
  { type: 'mask', label: 'Mask Shop', icon: VenetianMask },
  { type: 'jewellery', label: 'Jewellery Store', icon: Gem },
  { type: 'weapon', label: 'Weapon Store', icon: Sword },
];

const PLACEMENT_LABELS: Record<string, string> = {
  hair: 'Hair',
  face: 'Face',
  lower_face: 'Lower Face',
  right_arm: 'Right Arm',
  left_arm: 'Left Arm',
  chest: 'Chest',
  back: 'Back',
  neck: 'Neck',
  hand: 'Hand',
  custom: 'Custom',
};

const MODE_BADGE: Record<string, string> = {
  permanent: 'Permanent',
  removable: 'Removable',
};

export default function StyleShopsPanel({ characterId, isOwner }: Props) {
  const [activeShop, setActiveShop] = useState<ShopType | null>(null);
  const [presets, setPresets] = useState<StylePreset[]>([]);
  const [elements, setElements] = useState<StyleElementRead[]>([]);
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [applying, setApplying] = useState<number | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const [error, setError] = useState('');

  const loadElements = useCallback(async () => {
    try {
      const resp = await apiClient.getCharacterStyleElements(characterId);
      setElements(resp.elements);
    } catch {
      // silently fail — panel degrades gracefully
    }
  }, [characterId]);

  useEffect(() => {
    loadElements();
  }, [loadElements]);

  async function openShop(shopType: ShopType) {
    setActiveShop(shopType);
    setError('');
    setLoadingPresets(true);
    try {
      const data = await apiClient.getStylePresets(shopType);
      setPresets(data);
    } catch (err) {
      setError(err instanceof Error ? `Could not load presets: ${err.message}` : 'Could not load presets.');
    } finally {
      setLoadingPresets(false);
    }
  }

  function closeModal() {
    setActiveShop(null);
    setPresets([]);
    setError('');
  }

  async function handleApply(preset: StylePreset) {
    if (!isOwner) return;
    setApplying(preset.id);
    setError('');
    try {
      const resp = await apiClient.applyStyleElement(characterId, preset.id);
      setElements(resp.elements);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply.');
    } finally {
      setApplying(null);
    }
  }

  async function handleRemove(elementId: number) {
    if (!isOwner) return;
    setRemoving(elementId);
    try {
      const resp = await apiClient.archiveStyleElement(characterId, elementId);
      setElements(resp.elements);
    } catch {
      // silently fail
    } finally {
      setRemoving(null);
    }
  }

  function isPresetActive(presetId: number) {
    return elements.some(e => e.preset_id === presetId);
  }

  const activeShopData = SHOPS.find(s => s.type === activeShop);

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">Style Shops</h3>

      {/* Shop buttons */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {SHOPS.map(({ type, label, icon: Icon }) => {
          const shopElements = elements.filter(e => e.preset.shop_type === type);
          return (
            <button
              key={type}
              onClick={() => openShop(type)}
              className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-lg border border-gray-700 bg-gray-800/60 hover:border-gray-500 hover:bg-gray-800 transition-colors text-left"
            >
              <div className="flex items-center gap-2 min-w-0">
                <Icon className="w-4 h-4 text-gray-400 flex-shrink-0" />
                <span className="text-sm text-gray-300 truncate">{label}</span>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                {shopElements.length > 0 && (
                  <span className="text-xs text-emerald-400 font-medium">{shopElements.length}</span>
                )}
                <ChevronRight className="w-3.5 h-3.5 text-gray-600" />
              </div>
            </button>
          );
        })}
      </div>

      {/* Active elements summary */}
      {elements.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-gray-500 uppercase tracking-wide">Active</p>
          <div className="space-y-1">
            {elements.map(el => (
              <div
                key={el.id}
                className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg bg-gray-800/40 border border-gray-700/50"
              >
                <div className="min-w-0">
                  <span className="text-xs text-gray-400">{PLACEMENT_LABELS[el.placement] ?? el.placement}: </span>
                  <span className="text-xs text-gray-200">{el.preset.name}</span>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                    el.preset.attachment_mode === 'permanent'
                      ? 'text-amber-400 border-amber-800/40 bg-amber-900/20'
                      : 'text-blue-400 border-blue-800/40 bg-blue-900/20'
                  }`}>
                    {MODE_BADGE[el.preset.attachment_mode]}
                  </span>
                  {isOwner && (
                    <button
                      onClick={() => handleRemove(el.id)}
                      disabled={removing === el.id}
                      className="text-gray-600 hover:text-red-400 transition-colors disabled:opacity-40"
                      aria-label={`Remove ${el.preset.name}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Shop modal */}
      {activeShop && (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/60">
          <div className="w-full max-w-md bg-gray-900 border border-gray-700 rounded-2xl shadow-2xl overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3.5 border-b border-gray-800">
              <div className="flex items-center gap-2">
                {activeShopData && <activeShopData.icon className="w-4 h-4 text-gray-400" />}
                <span className="font-semibold text-gray-200 text-sm">{activeShopData?.label}</span>
              </div>
              <button
                onClick={closeModal}
                className="text-gray-500 hover:text-gray-300 transition-colors"
                aria-label="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Preset list */}
            <div className="overflow-y-auto max-h-[60vh]">
              {loadingPresets ? (
                <div className="py-8 text-center text-gray-500 text-sm">Loading…</div>
              ) : error ? (
                <div className="py-6 px-4 text-center text-red-400 text-sm">{error}</div>
              ) : (
                <ul className="divide-y divide-gray-800">
                  {presets.map(preset => {
                    const active = isPresetActive(preset.id);
                    const busy = applying === preset.id;
                    return (
                      <li key={preset.id} className="px-4 py-3.5 flex items-start gap-3">
                        {/* Preview placeholder */}
                        <div className="w-10 h-10 rounded-lg bg-gray-800 border border-gray-700 flex-shrink-0 overflow-hidden">
                          {preset.preview_image_url ? (
                            <img src={preset.preview_image_url} alt={preset.name} className="w-full h-full object-cover" />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center">
                              {activeShopData && <activeShopData.icon className="w-4 h-4 text-gray-600" />}
                            </div>
                          )}
                        </div>

                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium text-gray-200">{preset.name}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                              preset.attachment_mode === 'permanent'
                                ? 'text-amber-400 border-amber-800/40 bg-amber-900/20'
                                : 'text-blue-400 border-blue-800/40 bg-blue-900/20'
                            }`}>
                              {MODE_BADGE[preset.attachment_mode]}
                            </span>
                          </div>
                          <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{preset.description}</p>
                          <p className="text-xs text-gray-600 mt-0.5">{PLACEMENT_LABELS[preset.placement] ?? preset.placement}</p>
                        </div>

                        {isOwner && (
                          <button
                            onClick={() => handleApply(preset)}
                            disabled={busy}
                            className={`flex-shrink-0 flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50 ${
                              active
                                ? 'bg-emerald-900/40 border border-emerald-700/50 text-emerald-400 hover:bg-emerald-900/60'
                                : 'bg-gray-800 border border-gray-700 text-gray-300 hover:border-gray-500 hover:text-gray-100'
                            }`}
                          >
                            {busy ? (
                              <span>Applying…</span>
                            ) : active ? (
                              <>
                                <Check className="w-3 h-3" />
                                <span>Applied</span>
                              </>
                            ) : (
                              <span>Apply</span>
                            )}
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
