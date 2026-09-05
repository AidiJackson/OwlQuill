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
 *
 * SIZING is intrinsic, and that is what puts the close control on the picture.
 * The panel is `w-fit`, so its box IS the image's box; the image sizes itself
 * from its own aspect ratio under a max width and a max height, so the element
 * box and the drawn pixels are the same rectangle. The earlier `w-full` +
 * `object-contain` pair let them differ: a portrait image drawn inside a
 * 672px-wide box left ~47px of empty gutter each side, and the close button —
 * anchored to the box, as it still is — floated in the backdrop clear of the
 * photo. Every image in a character gallery is portrait, so that was every
 * image. Nothing about the mobile result changes: the max width is the same
 * viewport-minus-margin figure the old `w-full mx-4` produced, so a phone still
 * shows an image that spans the screen.
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

  /**
   * Hold the Home still underneath.
   *
   * Without this the page behind the backdrop scrolls under a wheel or a touch
   * drag, so closing the lightbox returns the visitor to somewhere they never
   * chose to be. `overflow: hidden` on `body` is enough — the root element
   * carries no overflow of its own (checked in index.css), so the UA propagates
   * body's value to the viewport.
   *
   * Only INLINE values are captured and restored, empty string included. Wiping
   * the property instead would silently drop a rule some other code had set,
   * and restoring a computed value would promote a stylesheet rule into an
   * inline one that outlives this component.
   *
   * Removing the scrollbar widens the viewport, which shifts the whole page
   * left by its width at the moment the lightbox opens and back again on close.
   * The compensating padding absorbs that. It is added to whatever padding the
   * body already computes to rather than assuming zero. `clientWidth` is 0 in
   * an environment that never lays out, and innerWidth-minus-zero is not a
   * scrollbar, so the compensation is skipped there — the lock itself, which is
   * the part that matters, still applies. Hence "where practical".
   *
   * The effect runs once for the life of the mount, so the lock is held through
   * the 200ms exit transition and released by unmount — the same cleanup path
   * whether the visitor closed it or navigated away mid-fade.
   */
  useEffect(() => {
    const { body } = document;
    const previousOverflow = body.style.overflow;
    const previousPaddingRight = body.style.paddingRight;

    const { clientWidth } = document.documentElement;
    const scrollbarWidth = clientWidth > 0 ? window.innerWidth - clientWidth : 0;

    body.style.overflow = 'hidden';
    if (scrollbarWidth > 0) {
      const existing = parseFloat(window.getComputedStyle(body).paddingRight) || 0;
      body.style.paddingRight = `${existing + scrollbarWidth}px`;
    }

    return () => {
      body.style.overflow = previousOverflow;
      body.style.paddingRight = previousPaddingRight;
    };
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
        className={`relative w-fit transition-all duration-200 ease-out ${
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
        {/* The max width is `min(panel cap, viewport − the old mx-4 margins)`.
            Expressed in viewport units rather than a percentage because a
            percentage would resolve against this `w-fit` panel, whose own width
            is what the image is deciding — the browser would be asked to size
            each from the other. */}
        <img
          src={resolveImageUrl(image.url)}
          alt=""
          className="block max-h-[85vh] max-w-[min(42rem,calc(100vw-2rem))] rounded-xl"
        />
      </div>
    </div>
  );
}
