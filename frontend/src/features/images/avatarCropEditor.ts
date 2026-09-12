/**
 * What the avatar crop editors share besides the maths: the zoom range, the
 * default crop, and the words and cursor the editor shows for a given image
 * shape at a given zoom. Both editors (the character-page picker and the image
 * library) read from here so they cannot disagree.
 */
import { avatarFreeAxes, avatarOverflow } from './avatarGeometry';
import type { FreeAxes, Size } from './coverGeometry';

export const AVATAR_MIN_ZOOM = 1;
/**
 * 3, not the picker's former 2.5: the library already allowed 3 and avatars
 * were saved at it, and a slider whose max is below a stored value pins to its
 * max and snaps the crop on first touch. The range only ever widens.
 */
export const AVATAR_MAX_ZOOM = 3;
export const AVATAR_ZOOM_STEP = 0.01;

/** The editors' square viewport, in CSS px (`w-40 h-40`). */
export const AVATAR_EDITOR_FRAME_PX = 160;
export const AVATAR_EDITOR_FRAME: Size = { width: AVATAR_EDITOR_FRAME_PX, height: AVATAR_EDITOR_FRAME_PX };

export const DEFAULT_AVATAR_CROP = { x: 0.5, y: 0.5, scale: 1 } as const;

export function isDefaultAvatarCrop(x: number, y: number, scale: number, epsilon = 1e-6): boolean {
  return (
    Math.abs(x - DEFAULT_AVATAR_CROP.x) < epsilon
    && Math.abs(y - DEFAULT_AVATAR_CROP.y) < epsilon
    && Math.abs(scale - DEFAULT_AVATAR_CROP.scale) < epsilon
  );
}

export type AvatarCropCursor = 'grab' | 'grabbing' | 'default';

export interface AvatarCropAffordance {
  /** Which axes a drag moves — both assumed free until the image's size is known. */
  free: FreeAxes;
  hint: string;
  cursor: AvatarCropCursor;
}

/**
 * What to tell and show the creator for *image* at *scale* in the editor
 * frame. Before the image reports its size the editor assumes it can be
 * dragged (the hook's fallback still pans the zoom overflow), so the hint and
 * cursor say so rather than announcing a lock that may not exist.
 */
export function avatarCropAffordance(image: Size | null, scale: number, dragging: boolean): AvatarCropAffordance {
  const free: FreeAxes = image
    ? avatarFreeAxes(avatarOverflow(image, AVATAR_EDITOR_FRAME, scale))
    : { x: true, y: true };
  const any = free.x || free.y;
  const hint = !any
    ? 'Zoom in to adjust the crop'
    : free.x && free.y
      ? 'Drag to position'
      : free.y
        ? 'Drag up or down to position'
        : 'Drag left or right to position';
  const cursor: AvatarCropCursor = !any ? 'default' : dragging ? 'grabbing' : 'grab';
  return { free, hint, cursor };
}
