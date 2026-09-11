/**
 * The geometry behind cover framing, as pure functions.
 *
 * A cover is drawn with `object-fit: cover` and `object-position: X% Y%`, and
 * the two stored fractions `cover_position_x/y` ARE that object-position. Under
 * `cover` the image is scaled uniformly until it fills the frame on both axes,
 * which means it overflows on AT MOST ONE axis — the one where, after scaling,
 * it is longer than the frame — and object-position only does anything on that
 * axis. On the other axis the image fits exactly and the fraction is inert.
 *
 * WHICH AXIS OVERFLOWS IS A PROPERTY OF THE PAIR, NOT OF THE FRAME. A 16:9
 * frame overflows vertically for a portrait or square image and HORIZONTALLY
 * for anything wider than 16:9. The reposition editor used to assume the axis
 * from the viewport alone ("desktop → vertical", "mobile → horizontal") and
 * mapped the pointer to a fraction of the frame on both axes regardless, so a
 * wide landscape cover on the desktop preview could not be moved up or down at
 * all (correct, but the hint said otherwise) and moved left/right much more
 * slowly than the pointer (incorrect — a full-frame drag was needed to travel
 * an overflow of a few dozen pixels). Everything here derives the free axis
 * from the real image and the real frame, and maps pointer pixels 1:1 onto
 * image pixels along it.
 *
 * Nothing here touches the DOM or the API; the hook and the preview call in
 * with measurements and apply the answers.
 */

export interface Size {
  width: number;
  height: number;
}

export interface CoverOverflow {
  /** The uniform scale `object-fit: cover` applies to the image. */
  scale: number;
  /** Scaled-image width minus frame width, in frame pixels; never negative. */
  overflowX: number;
  /** Scaled-image height minus frame height, in frame pixels; never negative. */
  overflowY: number;
}

export interface FreeAxes {
  /** `cover_position_x` changes what is shown. */
  x: boolean;
  /** `cover_position_y` changes what is shown. */
  y: boolean;
}

/**
 * Below this many frame pixels an overflow is treated as none. A 1600×900 image
 * in a 16:9 frame computes to a fraction of a pixel of overflow from rounding
 * alone, and dragging a value that moves the image by less than a pixel is
 * noise, not framing.
 */
export const OVERFLOW_EPSILON_PX = 1;

/**
 * Relative tolerance when only aspect ratios are known (no pixel sizes yet):
 * an image within this fraction of the frame's ratio is "the same shape".
 */
export const ASPECT_EPSILON = 0.005;

/**
 * How far the cover-scaled *image* overflows *frame* on each axis.
 *
 * Returns zero overflow on both axes for degenerate input (a dimension of 0 or
 * less) rather than NaN, so a frame that has not laid out yet cannot poison a
 * drag with Infinity.
 */
export function coverOverflow(image: Size, frame: Size): CoverOverflow {
  if (image.width <= 0 || image.height <= 0 || frame.width <= 0 || frame.height <= 0) {
    return { scale: 1, overflowX: 0, overflowY: 0 };
  }
  const scale = Math.max(frame.width / image.width, frame.height / image.height);
  const overflowX = Math.max(0, image.width * scale - frame.width);
  const overflowY = Math.max(0, image.height * scale - frame.height);
  return { scale, overflowX, overflowY };
}

/** Which of `cover_position_x/y` has any effect for this image in this frame. */
export function freeAxesFromOverflow(overflow: CoverOverflow): FreeAxes {
  return {
    x: overflow.overflowX >= OVERFLOW_EPSILON_PX,
    y: overflow.overflowY >= OVERFLOW_EPSILON_PX,
  };
}

/**
 * The same question answered from aspect ratios alone (width ÷ height), for a
 * frame whose pixel size is not known — the preview hint is computed from the
 * viewport's nominal ratio before, and independently of, layout.
 *
 * Wider than the frame → the image overflows horizontally → X is free.
 * Taller than the frame → it overflows vertically → Y is free.
 * The same shape → neither.
 */
export function freeAxesFromAspect(imageAspect: number, frameAspect: number): FreeAxes {
  if (!(imageAspect > 0) || !(frameAspect > 0)) return { x: false, y: false };
  const ratio = imageAspect / frameAspect;
  return {
    x: ratio > 1 + ASPECT_EPSILON,
    y: ratio < 1 - ASPECT_EPSILON,
  };
}

/**
 * Convert a pointer movement in frame pixels into a change of the stored
 * fractions, 1:1 with the image along each free axis and exactly zero along a
 * fitted one.
 *
 * Sign: object-position X% places the image's X% point on the frame's X% point,
 * so the image's left edge sits at `-overflowX · X`. Dragging the pointer to
 * the RIGHT should carry the image to the right, i.e. move that edge towards
 * zero, i.e. DECREASE X. Hence the subtraction — and the same on Y.
 */
export function coverDragDelta(
  dxPx: number,
  dyPx: number,
  overflow: CoverOverflow,
): { dX: number; dY: number } {
  const free = freeAxesFromOverflow(overflow);
  // `|| 0` folds the -0 a zero-length pointer move would otherwise produce.
  return {
    dX: free.x ? -dxPx / overflow.overflowX || 0 : 0,
    dY: free.y ? -dyPx / overflow.overflowY || 0 : 0,
  };
}
