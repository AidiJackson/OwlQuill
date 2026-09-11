import { useCallback, useEffect, useRef, useState } from 'react';
import { ficDebug } from '@/lib/ficDebug';
import { coverDragDelta, coverOverflow, type Size } from './coverGeometry';

/**
 * Drag-to-reposition for previewing how an image sits inside a fixed frame,
 * without ever touching the underlying file — the profile uses CSS object
 * positioning, so repositioning is non-destructive by construction.
 *
 * Two modes, matching the two frame shapes on a character profile:
 *
 * - `objectPosition` (cover / hero): pan works at any zoom. Position maps
 *   directly to CSS `object-position`; dragging right reveals the left of the
 *   image, so the delta is subtracted. Once the caller has reported the
 *   image's natural size (`setImageSize`), the pointer moves the image 1:1
 *   along the axis where it actually overflows the frame and not at all along
 *   the axis where it fits — see `coverGeometry`. Until then it falls back to
 *   treating the pointer as a fraction of the frame, so a drag before the
 *   image has loaded still does something rather than nothing.
 * - `scaleTranslate` (square avatar): panning only means something once the
 *   image is zoomed in (`scale > 1`), and the delta is scaled by the zoom.
 *
 * Lifted verbatim from the original inline implementation in Images.tsx so the
 * profile and the library share one behaviour rather than drifting apart.
 */
export type DragMode = 'objectPosition' | 'scaleTranslate';

interface Options {
  mode: DragMode;
  /** Starting values, e.g. from an existing cover_position_x/y. */
  initialPosX?: number;
  initialPosY?: number;
  initialScale?: number;
  /** Debug label so overlapping drags are distinguishable in the log. */
  debugLabel?: string;
}

const clamp01 = (n: number) => Math.min(1, Math.max(0, n));

export function useObjectPositionDrag({
  mode,
  initialPosX = 0.5,
  initialPosY = 0.5,
  initialScale = 1.0,
  debugLabel = 'objectPositionDrag',
}: Options) {
  const [posX, setPosX] = useState(initialPosX);
  const [posY, setPosY] = useState(initialPosY);
  const [scale, setScale] = useState(initialScale);

  // Live refs — the drag listeners are attached once and must read the latest
  // values without re-binding on every state change.
  const posXRef = useRef(posX);
  const posYRef = useRef(posY);
  const scaleRef = useRef(scale);
  useEffect(() => { posXRef.current = posX; }, [posX]);
  useEffect(() => { posYRef.current = posY; }, [posY]);
  useEffect(() => { scaleRef.current = scale; }, [scale]);

  const frameRef = useRef<HTMLDivElement | null>(null);
  // The image's natural pixel size, reported by whoever renders it. Only the
  // objectPosition mode reads it; the avatar's scale/translate pan is a zoom
  // on a square and needs no overflow calculation.
  const imageSizeRef = useRef<Size | null>(null);
  const dragStateRef = useRef<{ startX: number; startY: number; startPosX: number; startPosY: number } | null>(null);
  const activeCleanupRef = useRef<(() => void) | null>(null);

  const startDrag = useCallback((clientX: number, clientY: number) => {
    activeCleanupRef.current?.();

    if (mode === 'scaleTranslate' && scaleRef.current <= 1.001) {
      // Nothing to pan until the image is zoomed in.
      return;
    }

    ficDebug.dragStart(debugLabel);
    dragStateRef.current = {
      startX: clientX,
      startY: clientY,
      startPosX: posXRef.current,
      startPosY: posYRef.current,
    };

    const applyMove = (x: number, y: number) => {
      const container = frameRef.current;
      if (!dragStateRef.current || !container) return;
      const { offsetWidth: w, offsetHeight: h } = container;
      const dxPx = x - dragStateRef.current.startX;
      const dyPx = y - dragStateRef.current.startY;
      const dx = dxPx / w;
      const dy = dyPx / h;

      if (mode === 'objectPosition') {
        const image = imageSizeRef.current;
        if (image) {
          // Real geometry: the free axis follows the image, the fitted axis
          // stays put, and the image tracks the pointer pixel for pixel.
          const { dX, dY } = coverDragDelta(dxPx, dyPx, coverOverflow(image, { width: w, height: h }));
          setPosX(clamp01(dragStateRef.current.startPosX + dX));
          setPosY(clamp01(dragStateRef.current.startPosY + dY));
        } else {
          setPosX(clamp01(dragStateRef.current.startPosX - dx));
          setPosY(clamp01(dragStateRef.current.startPosY - dy));
        }
      } else {
        const sc = scaleRef.current;
        if (sc <= 1.001) return;
        setPosX(clamp01(dragStateRef.current.startPosX + (-dx * sc) / (sc - 1)));
        setPosY(clamp01(dragStateRef.current.startPosY + (-dy * sc) / (sc - 1)));
      }
    };

    const onMouseMove = (ev: MouseEvent) => applyMove(ev.clientX, ev.clientY);
    const onTouchMove = (ev: TouchEvent) => { ev.preventDefault(); applyMove(ev.touches[0].clientX, ev.touches[0].clientY); };
    const onEnd = () => {
      ficDebug.dragEnd(debugLabel);
      dragStateRef.current = null;
      activeCleanupRef.current = null;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onEnd);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onEnd);
      window.removeEventListener('touchcancel', onEnd);
    };

    activeCleanupRef.current = onEnd;
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onEnd);
    window.addEventListener('touchmove', onTouchMove, { passive: false });
    window.addEventListener('touchend', onEnd);
    window.addEventListener('touchcancel', onEnd);
  }, [mode, debugLabel]);

  /** Tear down any in-flight drag — call on modal close / unmount. */
  const cleanupDrag = useCallback(() => {
    activeCleanupRef.current?.();
  }, []);

  /** Reset to given values (e.g. re-opening the editor on a new image). */
  const reset = useCallback((x = 0.5, y = 0.5, s = 1.0) => {
    setPosX(x);
    setPosY(y);
    setScale(s);
  }, []);

  /**
   * Report the natural size of the image being framed (from the <img>'s
   * `naturalWidth/Height`). Pass `null` when the image changes and its size is
   * not yet known, so a drag on the new image does not use the old geometry.
   */
  const setImageSize = useCallback((size: Size | null) => {
    imageSizeRef.current = size && size.width > 0 && size.height > 0 ? size : null;
  }, []);

  useEffect(() => () => { activeCleanupRef.current?.(); }, []);

  return {
    posX, posY, scale,
    setPosX, setPosY, setScale,
    posXRef, posYRef, scaleRef,
    frameRef, startDrag, cleanupDrag, reset,
    imageSizeRef, setImageSize,
  };
}
