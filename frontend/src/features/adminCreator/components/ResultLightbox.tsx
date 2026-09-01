// Full-size inspection of one Admin Creator result.
//
// The point of this surface is judging whether a deliberate reference set
// actually worked, and that cannot be done against a thumbnail — the whole
// image has to be visible, uncropped, as large as the viewport allows.
//
// Admin Creator only. The Image Generator on /images keeps its own result
// presentation; nothing here is shared with it.
//
// Dismissal follows the three conventions people already expect from an overlay
// — Escape, backdrop click, and an always-visible close button — while a click
// on the image itself does nothing, so dragging or tapping to look closer never
// throws the image away.
import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

interface Props {
  src: string;
  onClose: () => void;
}

export default function ResultLightbox({ src, onClose }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', onKeyDown);
    // The page behind must not scroll while the overlay owns the viewport —
    // on a tablet that is the difference between inspecting an image and
    // fighting the page.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // Move focus into the overlay so Escape reaches it and the close control is
    // the first thing a keyboard or screen-reader user lands on.
    closeRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Generated image"
      // The backdrop is the click target for dismissal. The image and the close
      // button sit above it and stop propagation, so only the surrounding dark
      // area closes.
      onClick={onClose}
      className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center p-3 sm:p-6"
    >
      <button
        ref={closeRef}
        type="button"
        onClick={onClose}
        aria-label="Close"
        // Generous hit area for touch, and inset far enough to clear an iPad's
        // rounded corners and status area.
        className="absolute top-3 right-3 sm:top-5 sm:right-5 z-10 flex items-center justify-center w-11 h-11 rounded-full bg-black/60 border border-white/25 text-white/90 hover:text-white hover:border-white/50 transition-colors"
      >
        <X className="w-5 h-5" />
      </button>

      <img
        src={src}
        alt=""
        onClick={(e) => e.stopPropagation()}
        // max-w/max-h against the flex container plus object-contain: the image
        // grows to fill whichever axis binds first and is never cropped, at any
        // aspect ratio or orientation.
        className="max-w-full max-h-full w-auto h-auto object-contain rounded-lg"
      />
    </div>
  );
}
