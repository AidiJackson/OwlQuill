import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage } from '@/lib/types';

interface Props {
  open: boolean;
  onClose: () => void;
  onSelect: (image: LibraryImage) => void;
  selectedId?: number;
}

export default function AttachImageModal({ open, onClose, onSelect, selectedId }: Props) {
  const [images, setImages] = useState<LibraryImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState<number | undefined>(selectedId);

  useEffect(() => {
    if (!open) return;
    setPicked(selectedId);
    setLoading(true);
    setError('');
    apiClient
      .listLibraryImages()
      .then(setImages)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false));
  }, [open, selectedId]);

  if (!open) return null;

  const handleAttach = () => {
    const img = images.find((i) => i.id === picked);
    if (img) onSelect(img);
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6 max-w-md w-full shadow-xl max-h-[80vh] flex flex-col">
          <h3 className="text-lg font-semibold text-gray-200 mb-3">Attach an OwlQuill image</h3>

          {loading ? (
            <p className="text-sm text-gray-400 py-8 text-center">Loading images…</p>
          ) : error ? (
            <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 mb-3">{error}</p>
          ) : images.length === 0 ? (
            <>
              <p className="text-sm text-gray-400 mb-4">No saved images yet.</p>
              <div className="flex items-center gap-3">
                <Link to="/images/new" className="btn btn-primary text-sm">
                  Generate an image
                </Link>
                <button onClick={onClose} className="btn btn-secondary text-sm">
                  Close
                </button>
              </div>
              <p className="text-xs text-gray-500 mt-3">
                Uploads are disabled in beta. Only images generated in OwlQuill can be attached.
              </p>
            </>
          ) : (
            <>
              <div className="overflow-y-auto flex-1 -mx-1 px-1 mb-3">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {images.map((img) => (
                    <button
                      key={img.id}
                      type="button"
                      onClick={() => setPicked(img.id)}
                      className={`rounded-lg overflow-hidden border-2 transition-colors ${
                        picked === img.id
                          ? 'border-owl-500 ring-2 ring-owl-500/30'
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
              <div className="flex items-center gap-3">
                <button
                  onClick={handleAttach}
                  disabled={picked == null}
                  className="btn btn-primary text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Attach selected
                </button>
                <button onClick={onClose} className="btn btn-secondary text-sm">
                  Close
                </button>
                <Link to="/images/new" className="text-xs text-owl-400 hover:text-owl-300 ml-auto">
                  Generate new
                </Link>
              </div>
              <p className="text-xs text-gray-500 mt-2">
                Uploads are disabled in beta. Only images generated in OwlQuill can be attached.
              </p>
            </>
          )}
        </div>
      </div>
    </>
  );
}
