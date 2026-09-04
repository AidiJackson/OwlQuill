/**
 * Shared media presentation maths.
 *
 * The avatar transform lives here rather than in a page because two surfaces
 * render the same avatar from the same stored values — the authenticated
 * character page and the public Character Home — and a character whose portrait
 * is framed one way for its creator and another way for a visitor is a bug the
 * creator cannot see. One implementation is the only way that stays true.
 */
import type { CSSProperties } from 'react';

/**
 * Inline style that applies a character's stored avatar crop.
 *
 * ``avatar_scale`` zooms and ``avatar_position_x/y`` choose the point that
 * stays centred. The translate is what makes the pair work together: scaling
 * about the centre moves every other point away from it, so the offset is
 * divided by the scale to convert "where in the ORIGINAL image" into "how far
 * to slide the SCALED image". Without that division the crop drifts further
 * off-target the more it is zoomed.
 *
 * Returns ``undefined`` at scale 1 (within a float tolerance) so an unzoomed
 * avatar carries no transform at all, leaving the browser's plain
 * ``object-fit: cover`` path untouched.
 *
 * The caller must render the image absolutely inside a ``relative``,
 * ``overflow-hidden`` box. That box is the containing block that clips the
 * result; without it a scaled avatar escapes and overlaps whatever sits below.
 */
export function avatarTransformStyle(
  scale: number | null | undefined,
  posX: number | null | undefined,
  posY: number | null | undefined,
): CSSProperties | undefined {
  const s = scale ?? 1;
  if (s <= 1.001) return undefined;

  const x = posX ?? 0.5;
  const y = posY ?? 0.5;
  const shift = (position: number) => ((0.5 - position) * (s - 1) / s) * 100;

  return {
    transformOrigin: 'center center',
    transform: `scale(${s}) translate(${shift(x)}%, ${shift(y)}%)`,
  };
}

/**
 * ``object-position`` for a character's stored cover framing.
 *
 * Simpler than the avatar because the cover is never scaled — the stored
 * fractions map straight onto percentages. Centre is the documented default for
 * a cover that has never been positioned.
 */
export function coverObjectPosition(
  posX: number | null | undefined,
  posY: number | null | undefined,
): string {
  return `${(posX ?? 0.5) * 100}% ${(posY ?? 0.5) * 100}%`;
}
