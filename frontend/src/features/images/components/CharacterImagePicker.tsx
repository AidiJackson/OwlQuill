import { useEffect, useRef, useState } from 'react';
import { X, Check, Camera, Loader2 } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';
import type { LibraryImage } from '@/lib/types';
import { useObjectPositionDrag } from '../useObjectPositionDrag';
import { GALLERY_KINDS } from '../galleryKinds';

/**
 * Owner-only image picker, scoped to a SINGLE character.
 *
 * This is the whole point of the sprint: an owner curating Shadow's avatar or
 * cover picks from Shadow's own images, previews the crop in the real profile
 * aspect, nudges the position, and confirms — without ever visiting the global
 * library or being able to touch another character. Cancelling mutates nothing.
 *
 * Positioning is non-destructive (CSS object-position / transform); the stored
 * file is never altered.
 */
interface Props {
  characterId: number;
  characterName: string;
  mode: 'avatar' | 'cover';
  /** Preselect the current cover and start straight in reposition mode. */
  repositionOnly?: boolean;
  currentImageUrl?: string | null;
  initialPosX?: number;
  initialPosY?: number;
  onConfirmed: (result: { avatar_url?: string; cover_url?: string }) => void;
  onCancel: () => void;
}

// Only finished, shareable output is eligible for a profile picture or cover —
// never anchors, face refs or identity working plates. Same allowlist the
// library and the public gallery use; see features/images/galleryKinds.
const ELIGIBLE_KINDS = [...GALLERY_KINDS];

export default function CharacterImagePicker({
  characterId,
  characterName,
  mode,
  repositionOnly = false,
  currentImageUrl,
  initialPosX = 0.5,
  initialPosY = 0.5,
  onConfirmed,
  onCancel,
}: Props) {
  const [images, setImages] = useState<LibraryImage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<LibraryImage | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  const mountedRef = useRef(true);

  const drag = useObjectPositionDrag({
    mode: mode === 'cover' ? 'objectPosition' : 'scaleTranslate',
    initialPosX,
    initialPosY,
    debugLabel: `CharacterImagePicker:${mode}`,
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; drag.cleanupDrag(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Reposition-only: skip selection, treat the current cover as the subject.
  useEffect(() => {
    if (repositionOnly && currentImageUrl) {
      setSelected({
        id: -1, character_id: characterId, kind: 'cover', status: 'active',
        visibility: 'private', file_path: currentImageUrl, url: currentImageUrl,
        created_at: '',
      });
      setLoading(false);
      return;
    }
    apiClient
      .listMyCharacterImages({ characterId, kind: ELIGIBLE_KINDS, sort: 'newest' })
      .then((imgs) => { if (mountedRef.current) setImages(imgs); })
      .catch((err) => { if (mountedRef.current) setLoadError(err instanceof Error ? err.message : 'Failed to load images.'); })
      .finally(() => { if (mountedRef.current) setLoading(false); });
  }, [characterId, repositionOnly, currentImageUrl]);

  const handleSelect = (img: LibraryImage) => {
    setSelected(img);
    drag.reset(0.5, 0.5, 1.0);
    setSaveError('');
  };

  const handleConfirm = async () => {
    if (!selected) return;
    setSaving(true);
    setSaveError('');
    try {
      if (mode === 'cover') {
        // Reposition-only reuses the existing cover image id path via the
        // current image; for a fresh selection we assign then position.
        if (repositionOnly) {
          await apiClient.updateCharacter(characterId, {
            cover_position_x: drag.posXRef.current,
            cover_position_y: drag.posYRef.current,
          });
          if (!mountedRef.current) return;
          onConfirmed({ cover_url: currentImageUrl ?? undefined });
        } else {
          const result = await apiClient.setCharacterCover(
            characterId, 'character', selected.id,
            drag.posYRef.current, drag.posXRef.current,
          );
          await apiClient.updateCharacter(characterId, { cover_scale: 1.0 });
          if (!mountedRef.current) return;
          onConfirmed({ cover_url: result.cover_url });
        }
      } else {
        const result = await apiClient.setCharacterAvatar(characterId, 'character', selected.id);
        await apiClient.updateCharacter(characterId, {
          avatar_position_x: drag.posXRef.current,
          avatar_position_y: drag.posYRef.current,
          avatar_scale: drag.scaleRef.current,
        });
        if (!mountedRef.current) return;
        onConfirmed({ avatar_url: result.avatar_url });
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setSaveError(err instanceof Error ? err.message : 'Could not save. Try again.');
    } finally {
      if (mountedRef.current) setSaving(false);
    }
  };

  const isCover = mode === 'cover';
  const previewUrl = selected ? resolveImageUrl(selected.url) : null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true">
      <div className="bg-surface border border-edge rounded-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-edge">
          <h2 className="font-serif text-lg text-ink">
            {isCover ? 'Cover image' : 'Profile picture'}
            <span className="text-ink-3 font-sans text-sm"> · {characterName}</span>
          </h2>
          <button onClick={onCancel} className="text-ink-3 hover:text-ink transition-colors" aria-label="Cancel">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Preview frame — real profile aspect, drag to reposition */}
          {previewUrl && (
            <div className="space-y-2">
              <p className="text-xs text-ink-3">
                Drag to reposition. The original image is never altered.
              </p>
              <div
                ref={drag.frameRef}
                onMouseDown={(e) => { e.preventDefault(); drag.startDrag(e.clientX, e.clientY); }}
                onTouchStart={(e) => drag.startDrag(e.touches[0].clientX, e.touches[0].clientY)}
                className={`relative overflow-hidden bg-surface-elevated cursor-move select-none ${
                  isCover ? 'w-full aspect-[3/1] rounded-xl' : 'w-40 h-40 rounded-2xl mx-auto'
                }`}
              >
                <img
                  src={previewUrl}
                  alt="Preview"
                  draggable={false}
                  className="absolute inset-0 w-full h-full object-cover pointer-events-none"
                  style={
                    isCover
                      ? { objectPosition: `${drag.posX * 100}% ${drag.posY * 100}%` }
                      : drag.scale > 1.001
                      ? { transform: `scale(${drag.scale}) translate(${(0.5 - drag.posX) * (drag.scale - 1) / drag.scale * 100}%, ${(0.5 - drag.posY) * (drag.scale - 1) / drag.scale * 100}%)` }
                      : undefined
                  }
                />
              </div>
              {!isCover && (
                <div className="flex items-center gap-2 justify-center">
                  <span className="text-xs text-ink-3">Zoom</span>
                  <input
                    type="range" min={1} max={2.5} step={0.05} value={drag.scale}
                    onChange={(e) => drag.setScale(Number(e.target.value))}
                    className="w-40"
                  />
                </div>
              )}
            </div>
          )}

          {/* Selection grid — hidden in reposition-only mode */}
          {!repositionOnly && (
            loading ? (
              <div className="flex justify-center py-10"><Loader2 className="w-6 h-6 text-ink-3 animate-spin" /></div>
            ) : loadError ? (
              <p className="text-sm text-red-500 py-4 text-center">{loadError}</p>
            ) : images.length === 0 ? (
              <div className="py-10 text-center">
                <Camera className="w-8 h-8 text-ink-3/50 mx-auto mb-3" />
                <p className="text-sm text-ink-2">{characterName} has no images yet.</p>
                <p className="text-xs text-ink-3 mt-1">Generate one from the image library first.</p>
              </div>
            ) : (
              <div>
                <p className="text-xs text-ink-3 mb-2">Choose from {characterName}'s images</p>
                <div className="grid grid-cols-4 gap-2 max-h-64 overflow-y-auto">
                  {images.map((img) => (
                    <button
                      key={img.id}
                      onClick={() => handleSelect(img)}
                      className={`relative aspect-square rounded-lg overflow-hidden border-2 transition-colors ${
                        selected?.id === img.id ? 'border-gem' : 'border-transparent hover:border-edge-md'
                      }`}
                    >
                      <img src={resolveImageUrl(img.url)} alt="" className="w-full h-full object-cover" draggable={false} />
                      {selected?.id === img.id && (
                        <div className="absolute inset-0 bg-gem/20 flex items-center justify-center">
                          <Check className="w-5 h-5 text-gem" />
                        </div>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )
          )}

          {saveError && <p className="text-sm text-red-500">{saveError}</p>}
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-edge">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg text-sm font-medium text-ink-2 hover:text-ink transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={!selected || saving}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-gem text-gem-ink hover:bg-gem/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {isCover ? 'Set cover' : 'Set profile picture'}
          </button>
        </div>
      </div>
    </div>
  );
}
