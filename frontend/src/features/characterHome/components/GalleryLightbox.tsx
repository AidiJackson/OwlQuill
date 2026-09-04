import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import type { CharacterImagePublic } from '@/lib/types';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';

/**
 * Full-size view of one gallery image, without leaving the Character Home.
 *
 * The alternative — linking a tile straight at its storage URL — would send a
 * visitor to a bare R2 image on another origin, with no way back except the
 * browser's back button. A gallery interaction should keep them here.
 *
 * The enter/exit transition follows the authenticated page's lightbox: a RAF
 * tick after mount drives opacity/scale in, and close reverses it before
 * unmounting 200ms later so the exit is visible rather than a cut. `mountedRef`
 * guards the delayed clear, since a visitor can navigate away mid-transition.
 *
 * Public by construction: it takes `CharacterImagePublic`, which carries no
 * prompt, provider, seed or metadata, so there is nothing owner-shaped to leak
 * even if this were rendered somewhere it should not be.
 */
export default function GalleryLightbox({
  images,
  index,
  onClose,
}: {
  images: CharacterImagePublic[];
  index: number;
  onClose: () => void;
}) {
  const [visible, setVisible] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    const id = requestAnimationFrame(() => {
      if (mountedRef.current) setVisible(true);
    });
    return () => cancelAnimationFrame(id);
  }, []);

  const close = () => {
    setVisible(false);
    setTimeout(() => { if (mountedRef.current) onClose(); }, 200);
  };

  // Escape closes. A visitor who opens an image by accident on a page with no
  // navigation needs a way out that is not the back button.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }); // no dep array: `close` closes over current state each render

  const image = images[index];
  if (!image) return null;

  return (
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm transition-opacity duration-200 ${
        visible ? 'opacity-100' : 'opacity-0'
      }`}
      onClick={close}
      role="dialog"
      aria-modal="true"
      aria-label="Image"
    >
      <div
        className={`relative max-w-2xl w-full mx-4 transition-all duration-200 ease-out ${
          visible ? 'opacity-100 scale-100' : 'opacity-0 scale-95'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 z-10"
          onClick={close}
          aria-label="Close"
        >
          <X className="w-4 h-4" />
        </button>
        <img
          src={resolveImageUrl(image.url)}
          alt=""
          className="w-full max-h-[85vh] object-contain rounded-xl"
        />
      </div>
    </div>
  );
}
