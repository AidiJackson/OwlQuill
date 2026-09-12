import { useCallback, useEffect, useRef, useState } from 'react';
import { ficDebug } from '@/lib/ficDebug';
import { coverDragDelta, coverOverflow, type Size } from './coverGeometry';
import { avatarDragDelta, avatarOverflow } from './avatarGeometry';

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
 * - `scaleTranslate` (square avatar): the image is cover-fitted into the
 *   square and may be zoomed. Position spans the TOTAL overflow — the cover
 *   fit's on the image's longer axis plus what the zoom adds on both — so a
 *   portrait can be panned vertically at zoom 1 and zooming widens the range
 *   rather than unlocking it. The pointer moves the image 1:1 along any
 *   overflowing axis and not at all along a fitted one; see `avatarGeometry`.
 *   Until the image's natural size is reported, only the zoom overflow is
 *   known and the pan is confined to it (the pre-fix range), never stalled.
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

/**
 * The natural size of an <img>, or null while it has none (not yet loaded,
 * or failed). For `setImageSize`: call it from `onLoad`, and once from a ref
 * callback for an image that was already complete (cached) before React
 * attached the load handler.
 */
export function naturalSizeOf(img: HTMLImageElement | null): Size | null {
  if (!img || !img.naturalWidth || !img.naturalHeight) return null;
  return { width: img.naturalWidth, height: img.naturalHeight };
}

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
  const [dragging, setDragging] = useState(false);
  // State as well as a ref: the ref is what a drag in flight reads, the state
  // is what lets the editor re-render its hint once the size arrives.
  const [imageSize, setImageSizeState] = useState<Size | null>(null);

  // Live refs — the drag listeners are attached once and must read the latest
  // values without re-binding on every state change.
  const posXRef = useRef(posX);
  const posYRef = useRef(posY);
  const scaleRef = useRef(scale);
  useEffect(() => { posXRef.current = posX; }, [posX]);
  useEffect(() => { posYRef.current = posY; }, [posY]);
  useEffect(() => { scaleRef.current = scale; }, [scale]);

  const frameRef = useRef<HTMLDivElement | null>(null);
  // The image's natural pixel size, reported by whoever renders it. Both
  // modes read it to find the axis the cover fit overflows on.
  const imageSizeRef = useRef<Size | null>(null);
  const dragStateRef = useRef<{ startX: number; startY: number; startPosX: number; startPosY: number } | null>(null);
  const activeCleanupRef = useRef<(() => void) | null>(null);

  const startDrag = useCallback((clientX: number, clientY: number) => {
    activeCleanupRef.current?.();

    ficDebug.dragStart(debugLabel);
    setDragging(true);
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

      if (mode === 'objectPosition') {
        const image = imageSizeRef.current;
        if (image) {
          // Real geometry: the free axis follows the image, the fitted axis
          // stays put, and the image tracks the pointer pixel for pixel.
          const { dX, dY } = coverDragDelta(dxPx, dyPx, coverOverflow(image, { width: w, height: h }));
          setPosX(clamp01(dragStateRef.current.startPosX + dX));
          setPosY(clamp01(dragStateRef.current.startPosY + dY));
        } else {
          setPosX(clamp01(dragStateRef.current.startPosX - dxPx / w));
          setPosY(clamp01(dragStateRef.current.startPosY - dyPx / h));
        }
      } else {
        // Total overflow at the current zoom, per axis; zero on an axis the
        // image merely fits, so the pointer cannot drag it into blank space.
        const overflow = avatarOverflow(imageSizeRef.current, { width: w, height: h }, scaleRef.current);
        const { dX, dY } = avatarDragDelta(dxPx, dyPx, overflow);
        setPosX(clamp01(dragStateRef.current.startPosX + dX));
        setPosY(clamp01(dragStateRef.current.startPosY + dY));
      }
    };

    const onMouseMove = (ev: MouseEvent) => applyMove(ev.clientX, ev.clientY);
    const onTouchMove = (ev: TouchEvent) => { ev.preventDefault(); applyMove(ev.touches[0].clientX, ev.touches[0].clientY); };
    const onEnd = () => {
      ficDebug.dragEnd(debugLabel);
      setDragging(false);
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
    const next = size && size.width > 0 && size.height > 0 ? size : null;
    imageSizeRef.current = next;
    setImageSizeState((prev) =>
      prev?.width === next?.width && prev?.height === next?.height ? prev : next,
    );
  }, []);

  /**
   * Move the image by a pointer-equivalent number of frame pixels without a
   * pointer (arrow keys). `scaleTranslate` only; bounded exactly as a drag is,
   * so it can no more expose blank space than a drag can.
   */
  const nudge = useCallback((dxPx: number, dyPx: number) => {
    const container = frameRef.current;
    if (mode !== 'scaleTranslate' || !container) return;
    const { offsetWidth: w, offsetHeight: h } = container;
    const overflow = avatarOverflow(imageSizeRef.current, { width: w, height: h }, scaleRef.current);
    const { dX, dY } = avatarDragDelta(dxPx, dyPx, overflow);
    if (dX) setPosX((p) => clamp01(p + dX));
    if (dY) setPosY((p) => clamp01(p + dY));
  }, [mode]);

  useEffect(() => () => { activeCleanupRef.current?.(); }, []);

  return {
    posX, posY, scale, dragging, imageSize,
    setPosX, setPosY, setScale,
    posXRef, posYRef, scaleRef,
    frameRef, startDrag, cleanupDrag, reset, nudge,
    imageSizeRef, setImageSize,
  };
}
