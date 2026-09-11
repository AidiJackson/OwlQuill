/**
 * The shared avatar/cover framing maths.
 *
 * This lives in one module because two surfaces render the same stored values —
 * the authenticated character page and the public Character Home. A character
 * whose portrait is cropped one way for its creator and another way for a
 * visitor is a bug the creator cannot see, so these tests pin the arithmetic
 * rather than either page's markup.
 */
import { describe, it, expect } from 'vitest';
import { avatarTransformStyle, coverObjectPosition } from '@/lib/media';

describe('avatarTransformStyle', () => {
  it('at scale 1 carries no transform — only the object-position that frames the cover fit', () => {
    // A never-repositioned avatar (0.5/0.5/1) renders exactly as before: a
    // centred cover crop. What is new is that a portrait can now be framed
    // on its head without zooming, through object-position.
    expect(avatarTransformStyle(1, 0.5, 0.5)).toEqual({ objectPosition: '50% 50%' });
    expect(avatarTransformStyle(1.0005, 0.5, 0.5)).toEqual({ objectPosition: '50% 50%' });
    expect(avatarTransformStyle(1, 0.5, 0)).toEqual({ objectPosition: '50% 0%' });
    expect(avatarTransformStyle(1, 1, 0.5)).toEqual({ objectPosition: '100% 50%' });
  });

  it('treats absent values as the centred, unzoomed default', () => {
    expect(avatarTransformStyle(null, null, null)).toEqual({ objectPosition: '50% 50%' });
    expect(avatarTransformStyle(undefined, undefined, undefined)).toEqual({ objectPosition: '50% 50%' });
  });

  it('centres a scaled avatar with no offset when the focal point is the centre', () => {
    const style = avatarTransformStyle(2, 0.5, 0.5);
    expect(style.transform).toBe('scale(2) translate(0%, 0%)');
    expect(style.transformOrigin).toBe('center center');
    expect(style.objectPosition).toBe('50% 50%');
  });

  it('above scale 1 sets BOTH mechanisms from the one stored pair', () => {
    // object-position slides through the cover-fit overflow; the translate
    // slides through the zoom overflow. Together the image's edge lands at
    // −position × total overflow (see avatarGeometry tests).
    const style = avatarTransformStyle(2, 0.5, 0);
    expect(style.objectPosition).toBe('50% 0%');
    expect(style.transform).toBe('scale(2) translate(0%, 25%)');
  });

  it('shifts toward the top when the focal point is the top edge', () => {
    // Pan's stored framing: 2x zoom pinned to the top of the image. A positive
    // Y translate slides the scaled image DOWN, which brings its top into view.
    const style = avatarTransformStyle(2, 0.5, 0);
    expect(style.transform).toBe('scale(2) translate(0%, 25%)');
  });

  it('divides the offset by the scale, so the crop does not drift when zoomed', () => {
    // The same focal point at two zoom levels: the offset shrinks as a
    // proportion of the scaled image, which is what keeps the chosen point
    // centred rather than sliding further off-target the more it is zoomed.
    expect(avatarTransformStyle(2, 0, 0.5).transform).toBe('scale(2) translate(25%, 0%)');
    expect(avatarTransformStyle(4, 0, 0.5).transform).toBe('scale(4) translate(37.5%, 0%)');
  });

  it('moves the opposite way for a focal point past the centre', () => {
    expect(avatarTransformStyle(2, 1, 0.5).transform).toBe('scale(2) translate(-25%, 0%)');
  });
});

describe('coverObjectPosition', () => {
  it('maps stored fractions onto percentages', () => {
    expect(coverObjectPosition(0.5, 0.075)).toBe('50% 7.5%');
    expect(coverObjectPosition(0, 1)).toBe('0% 100%');
  });

  it('centres when unset — the documented default for an unpositioned cover', () => {
    expect(coverObjectPosition(null, null)).toBe('50% 50%');
    expect(coverObjectPosition(undefined, undefined)).toBe('50% 50%');
  });
});
