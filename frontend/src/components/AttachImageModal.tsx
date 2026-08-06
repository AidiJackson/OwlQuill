import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiClient } from '@/lib/apiClient';
import type { LibraryImage } from '@/lib/types';
import { ficDebug } from '@/lib/ficDebug';
import { isAttachableImage, ATTACHABLE_KIND_LIST } from './attachImageKinds';

interface Props {
  open: boolean;
  onClose: () => void;
  onSelect: (image: LibraryImage) => void;
  selectedId?: number;
  /**
   * The character the post is being authored as. Required — a post composer is
   * character-contextual and must never show an account-wide library: posting
   * as Pan must not expose Shadow's media.
   *
   * This is deliberately not optional and has no "all characters" mode. That
   * belongs to the founder Image Library workspace, which is a different
   * surface with a different purpose.
   */
  characterId?: number | null;
}

export default function AttachImageModal({ open, onClose, onSelect, selectedId, characterId }: Props) {
  const [images, setImages] = useState<LibraryImage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [picked, setPicked] = useState<number | undefined>(selectedId);

  useEffect(() => {
    if (open) ficDebug.modalOpen('AttachImageModal');
    else ficDebug.modalClose('AttachImageModal');
  }, [open]);

  useEffect(() => {
    if (!open) return;
    setPicked(selectedId);
    // No acting character means no scope to show. Failing closed is correct:
    // the alternative is falling back to the account-wide library, which is
    // exactly the leak this guards against.
    if (characterId == null) {
      setImages([]);
      setLoading(false);
      setError('');
      return;
    }
    ficDebug.log(`AttachImageModal: fetching images for character ${characterId}`);
    setLoading(true);
    setError('');
    let cancelled = false;
    apiClient
      // Scoped server-side by character AND kind; the client-side filter below
      // is belt-and-braces for older rows, not the boundary.
      .listMyCharacterImages({ characterId, kind: ATTACHABLE_KIND_LIST })
      .then((imgs) => {
        if (!cancelled) setImages(imgs.filter(isAttachableImage));
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    // Guards against a stale response from the previous character landing after
    // a fast switch and repopulating the grid with the wrong character's media.
    return () => {
      cancelled = true;
    };
  }, [open, selectedId, characterId]);

  if (!open) return null;

  const handleAttach = () => {
    const img = images.find((i) => i.id === picked);
    if (img) onSelect(img);
  };

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-40" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="bg-surface border border-edge rounded-lg p-6 max-w-lg w-full shadow-xl max-h-[85vh] flex flex-col">
          <h3 className="text-lg font-semibold text-ink mb-3">Attach a Ficshon image</h3>

          {loading ? (
            <p className="text-sm text-ink-2 py-8 text-center">Loading images…</p>
          ) : error ? (
            <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 mb-3">{error}</p>
          ) : characterId == null ? (
            // Distinct from "no images". Telling a founder with a full library
            // that they have none is the kind of small lie that costs a support
            // thread; the actual blocker is that nobody is posting yet.
            <>
              <p className="text-sm text-ink-2 mb-4">
                Choose which character you&rsquo;re posting as first — a post can only carry
                that character&rsquo;s images.
              </p>
              <button onClick={onClose} className="btn btn-secondary text-sm">
                Close
              </button>
            </>
          ) : images.length === 0 ? (
            <>
              <p className="text-sm text-ink-2 mb-4">
                No generated images saved yet. Generate an image first, then attach it here.
              </p>
              <div className="flex items-center gap-3">
                <Link to="/images/new" className="btn btn-primary text-sm">
                  Generate an image
                </Link>
                <button onClick={onClose} className="btn btn-secondary text-sm">
                  Close
                </button>
              </div>
              <p className="text-xs text-ink-3 mt-3">
                Uploads are disabled in beta. Only images generated in Ficshon can be attached.
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
                          ? 'border-gem/50 ring-2 ring-gem/40'
                          : 'border-edge hover:border-edge-md'
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
                <Link to="/images/new" className="text-xs text-gem hover:opacity-80 ml-auto">
                  Generate new
                </Link>
              </div>
              <p className="text-xs text-ink-3 mt-2">
                Uploads are disabled in beta. Only images generated in Ficshon can be attached.
              </p>
            </>
          )}
        </div>
      </div>
    </>
  );
}
