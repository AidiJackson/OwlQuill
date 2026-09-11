/**
 * The geometry behind the avatar crop, as pure functions.
 *
 * An avatar is a square. The source is cover-fitted into it (so it fills the
 * square and overflows on the axis where it is longer), then optionally zoomed
 * about the centre. The stored triple is `avatar_scale` (zoom, ≥ 1) and
 * `avatar_position_x/y` (fractions in [0, 1]).
 *
 * WHAT THE POSITION SPANS — AND WHAT IT USED TO. Rendered at zoom `s`, the
 * image is `s` times its cover-fitted size, so on each axis it overflows the
 * frame `F` by
 *
 *     O = s · coverOverflow + (s − 1) · F
 *
 * — the cover-fit overflow, itself scaled, plus the overflow the zoom adds.
 * `avatar_position` is now the fraction of THAT total the image is slid by:
 * 0 shows the source's top/left edge, 1 its bottom/right, 0.5 the centre, at
 * every zoom. It used to parameterise only the second term: the cover-fit
 * overflow was pinned at centre by the browser's default `object-position`
 * and never entered the pan range, so a portrait's top sixth (in frame
 * pixels, `coverOverflow/2 · s − (s−1)·F/2`, which for a 2:3 source is 40·s
 * px in a 160 px frame) could not be reached at any zoom, and at zoom 1 no
 * drag was allowed at all.
 *
 * HOW THE RENDERER REALISES IT. Two CSS mechanisms compose: `object-position:
 * X% Y%` slides the image through the cover-fit overflow, and
 * `scale(s) translate((0.5 − p)·(s−1)/s · 100%)` slides the zoomed result
 * through the zoom overflow. Composed, the image's leading edge lands at
 * exactly `−p · O` — linear, and reaching both edges — which
 * :func:`avatarRenderedOffset` reproduces step by step so a test can check the
 * identity rather than trust it. Because the image is never smaller than the
 * frame and never slid past its own overflow, the frame is always fully
 * covered: no blank space at any position or zoom.
 *
 * `coverOverflow` is shared with the cover editor and not altered here.
 */
import { coverDragDelta, coverOverflow, freeAxesFromOverflow, type FreeAxes, type Size } from './coverGeometry';

export interface AvatarOverflow {
  /** Total horizontal overflow at this zoom, in frame pixels; never negative. */
  overflowX: number;
  /** Total vertical overflow at this zoom, in frame pixels; never negative. */
  overflowY: number;
}

/**
 * Total per-axis overflow of *image* cover-fitted into *frame* and zoomed by
 * *scale*. With no image size known the cover-fit term is unknown and treated
 * as zero, leaving only the zoom term — the same range the editor allowed
 * before, so a drag before the image has loaded degrades rather than breaks.
 */
export function avatarOverflow(image: Size | null, frame: Size, scale: number): AvatarOverflow {
  const s = Math.max(1, scale || 1);
  const zoom = (s - 1);
  const fit = image ? coverOverflow(image, frame) : { overflowX: 0, overflowY: 0 };
  if (frame.width <= 0 || frame.height <= 0) return { overflowX: 0, overflowY: 0 };
  return {
    overflowX: s * fit.overflowX + zoom * frame.width,
    overflowY: s * fit.overflowY + zoom * frame.height,
  };
}

/** Which of `avatar_position_x/y` moves anything for this image at this zoom. */
export function avatarFreeAxes(overflow: AvatarOverflow): FreeAxes {
  return freeAxesFromOverflow({ scale: 1, ...overflow });
}

/**
 * Pointer pixels → change in the stored fractions: 1:1 with the image along
 * each overflowing axis, zero along a fitted one. Same sign convention as the
 * cover: dragging right or down carries the image right or down, which
 * DECREASES the fraction.
 */
export function avatarDragDelta(dxPx: number, dyPx: number, overflow: AvatarOverflow): { dX: number; dY: number } {
  return coverDragDelta(dxPx, dyPx, { scale: 1, ...overflow });
}

/**
 * Where the rendered image's leading (left/top) edge lands relative to the
 * frame's, in frame pixels, by composing the three CSS steps the renderer
 * uses — cover-fit with `object-position`, `scale()` about the centre, then
 * `translate()` in the scaled space. Negative means the edge is outside the
 * frame (content hidden on that side). Exists so tests can verify the
 * `−p · O` identity and full coverage against the actual composition rather
 * than against a restatement of it.
 */
export function avatarRenderedOffset(
  image: Size,
  frame: Size,
  scale: number,
  posX: number,
  posY: number,
): { left: number; top: number; width: number; height: number } {
  const s = Math.max(1, scale || 1);
  const fit = coverOverflow(image, frame);
  const fitW = image.width * fit.scale;
  const fitH = image.height * fit.scale;

  // 1. object-fit: cover + object-position P%: the image's P% point sits on
  //    the frame's P% point, so its leading edge is at −overflow · P.
  const objLeft = -fit.overflowX * posX;
  const objTop = -fit.overflowY * posY;

  // 2. scale(s) about the frame's centre: every point's distance from the
  //    centre is multiplied by s.
  const cx = frame.width / 2;
  const cy = frame.height / 2;
  const scaledLeft = cx + (objLeft - cx) * s;
  const scaledTop = cy + (objTop - cy) * s;

  // 3. translate((0.5 − P)·(s−1)/s · 100%) — a percentage of the element's
  //    own box (the frame), applied in the scaled space, hence × s.
  const shiftX = (0.5 - posX) * (s - 1) / s * frame.width * s;
  const shiftY = (0.5 - posY) * (s - 1) / s * frame.height * s;

  return {
    left: scaledLeft + shiftX,
    top: scaledTop + shiftY,
    width: fitW * s,
    height: fitH * s,
  };
}
