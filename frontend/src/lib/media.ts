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
 * The image is cover-fitted into a square and may be zoomed. That leaves two
 * kinds of overflow — what the cover fit hides on the image's longer axis, and
 * what the zoom adds on both — and the stored ``avatar_position_x/y`` span the
 * TOTAL. Two CSS mechanisms realise the two parts:
 *
 * * ``object-position: X% Y%`` slides the image through the cover-fit
 *   overflow. It is set at every scale, zoom 1 included — this is what lets a
 *   portrait be framed on its head rather than its middle without zooming.
 * * ``scale(s) translate(…)`` slides the zoomed result through the zoom
 *   overflow. The translate is ``(0.5 − p)·(s − 1)/s`` of the box, divided by
 *   the scale because it is applied in the scaled space; composed with the
 *   object-position above, the image's leading edge lands at exactly
 *   ``−p · (total overflow)`` — see ``features/images/avatarGeometry``.
 *
 * At scale 1 (within a float tolerance) only the ``objectPosition`` is
 * returned, so an unzoomed avatar carries no transform and stays on the
 * browser's plain ``object-fit: cover`` path. A centred, unzoomed avatar
 * (``0.5/0.5/1`` — every never-repositioned avatar) therefore renders exactly
 * as it did when the function returned nothing.
 *
 * The caller must render the image absolutely inside a ``relative``,
 * ``overflow-hidden`` box. That box is the containing block that clips the
 * result; without it a scaled avatar escapes and overlaps whatever sits below.
 */
export function avatarTransformStyle(
  scale: number | null | undefined,
  posX: number | null | undefined,
  posY: number | null | undefined,
): CSSProperties {
  const s = scale ?? 1;
  const x = posX ?? 0.5;
  const y = posY ?? 0.5;
  const objectPosition = `${x * 100}% ${y * 100}%`;
  if (s <= 1.001) return { objectPosition };

  const shift = (position: number) => ((0.5 - position) * (s - 1) / s) * 100;

  return {
    objectPosition,
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
