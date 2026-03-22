import { useEffect, useState } from 'react';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage } from '@/lib/types';

interface Props {
  open: boolean;
  characterId: number;
  onClose: () => void;
  onSaved: (coverUrl: string) => void;
}

export default function CoverPickerModal({ open, characterId, onClose, onSaved }: Props) {
  const [images, setImages] = useState<LibraryImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState<LibraryImage | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');

  useEffect(() => {
    if (!open) return;
    setPicked(null);
    setSaveError('');
    setLoading(true);
    setError('');
    apiClient
      .listMyCharacterImages()
      .then((imgs) => setImages(imgs.filter((img) => img.kind === 'generated')))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load images'))
      .finally(() => setLoading(false));
  }, [open]);

  if (!open) return null;

  const handleSave = async () => {
    if (!picked) return;
    setSaving(true);
    setSaveError('');
    try {
      const result = await apiClient.setCharacterCover(characterId, 'character', picked.id);
      onSaved(result.cover_url);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to set cover');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-lg w-full shadow-xl max-h-[85vh] flex flex-col">
          <h3 className="text-lg font-semibold text-gray-200 mb-1">Choose Character Cover</h3>
          <p className="text-xs text-gray-500 mb-3">Selected image will be cropped to banner format.</p>

          {loading ? (
            <p className="text-sm text-gray-400 py-8 text-center">Loading images…</p>
          ) : error ? (
            <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 mb-3">{error}</p>
          ) : images.length === 0 ? (
            <>
              <p className="text-sm text-gray-400 mb-4">No generated images yet. Generate character images first.</p>
              <button onClick={onClose} className="btn btn-secondary text-sm">Close</button>
            </>
          ) : (
            <>
              <div className="overflow-y-auto flex-1 -mx-1 px-1 mb-3">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {images.map((img) => (
                    <button
                      key={img.id}
                      type="button"
                      onClick={() => setPicked(img)}
                      className={`rounded-lg overflow-hidden border-2 transition-colors ${
                        picked?.id === img.id
                          ? 'border-emerald-500 ring-2 ring-emerald-500/30'
                          : 'border-gray-800 hover:border-gray-600'
                      }`}
                    >
                      <img
                        src={img.url}
                        alt={img.prompt_summary || 'Generated image'}
                        className="w-full aspect-[2/3] object-cover"
                      />
                    </button>
                  ))}
                </div>
              </div>

              {saveError && <p className="text-sm text-red-400 mb-2">{saveError}</p>}

              <div className="flex items-center gap-3">
                <button
                  onClick={handleSave}
                  disabled={!picked || saving}
                  className="btn btn-primary text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? 'Saving…' : 'Set as Cover'}
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
