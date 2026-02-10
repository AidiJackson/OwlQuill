import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage, UserImageRead } from '@/lib/types';

type ImageItem = {
  id: number;
  type: 'character' | 'user';
  url: string;
  label: string;
};

interface Props {
  open: boolean;
  onClose: () => void;
  onSaved: (avatarUrl: string) => void;
}

export default function AvatarPickerModal({ open, onClose, onSaved }: Props) {
  const [images, setImages] = useState<ImageItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState<ImageItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    if (!open) return;
    setPicked(null);
    setSaveError('');
    setLoading(true);
    setError('');

    Promise.all([
      apiClient.listMyCharacterImages().catch(() => [] as LibraryImage[]),
      apiClient.listMyUserImages().catch(() => [] as UserImageRead[]),
    ])
      .then(([charImages, userImages]) => {
        const items: ImageItem[] = [];
        for (const img of charImages) {
          items.push({
            id: img.id,
            type: 'character',
            url: img.url,
            label: img.prompt_summary || 'Character image',
          });
        }
        for (const img of userImages) {
          items.push({
            id: img.id,
            type: 'user',
            url: img.url,
            label: img.prompt_summary || img.kind,
          });
        }
        setImages(items);
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load images'))
      .finally(() => setLoading(false));
  }, [open]);

  if (!open) return null;

  const handleSave = async () => {
    if (!picked) return;
    setSaving(true);
    setSaveError('');
    try {
      const result = await apiClient.setAvatar(picked.type, picked.id);
      onSaved(result.avatar_url);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to set avatar');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-md w-full shadow-xl max-h-[80vh] flex flex-col">
          <h3 className="text-lg font-semibold text-gray-200 mb-3">Choose Avatar</h3>

          {loading ? (
            <p className="text-sm text-gray-400 py-8 text-center">Loading images...</p>
          ) : error ? (
            <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 mb-3">{error}</p>
          ) : images.length === 0 ? (
            <>
              <p className="text-sm text-gray-400 mb-4">
                No images available. Generate character images or profile covers first, then use them as your avatar.
              </p>
              <button onClick={onClose} className="btn btn-secondary text-sm">
                Close
              </button>
            </>
          ) : (
            <>
              <div className="overflow-y-auto flex-1 -mx-1 px-1 mb-3">
                <div className="grid grid-cols-3 gap-2">
                  {images.map((img) => (
                    <button
                      key={`${img.type}-${img.id}`}
                      type="button"
                      onClick={() => setPicked(img)}
                      className={`rounded-lg overflow-hidden border-2 transition-colors aspect-square ${
                        picked?.id === img.id && picked?.type === img.type
                          ? 'border-owl-500 ring-2 ring-owl-500/30'
                          : 'border-gray-800 hover:border-gray-600'
                      }`}
                    >
                      <img
                        src={img.url}
                        alt={img.label}
                        className="w-full h-full object-cover"
                      />
                    </button>
                  ))}
                </div>
              </div>

              {saveError && (
                <p className="text-sm text-red-400 mb-2">{saveError}</p>
              )}

              <div className="flex items-center gap-3">
                <button
                  onClick={handleSave}
                  disabled={!picked || saving}
                  className="btn btn-primary text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? 'Saving...' : 'Set as Avatar'}
                </button>
                <button onClick={onClose} className="btn btn-secondary text-sm" disabled={saving}>
                  Cancel
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
