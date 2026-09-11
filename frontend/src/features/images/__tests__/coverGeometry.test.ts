/**
 * Cover framing geometry — which axis a drag may move, and by how much.
 *
 * Every case is a (image shape, viewport shape) pair, because that pair — not
 * the viewport alone — decides where `object-fit: cover` leaves slack. The
 * frames are the two the preview offers (16:9 desktop, 3:4 mobile) at a fixed
 * pixel size, so expected overflows can be worked out by hand.
 */
import { describe, expect, it } from 'vitest';
import {
  coverDragDelta,
  coverOverflow,
  freeAxesFromAspect,
  freeAxesFromOverflow,
} from '../coverGeometry';

const DESKTOP = { width: 320, height: 180 }; // 16:9
const MOBILE = { width: 210, height: 280 }; // 3:4

const IMAGES = {
  portrait: { width: 800, height: 1200 }, // 2:3
  landscape: { width: 2000, height: 1000 }, // 2:1, wider than 16:9
  square: { width: 1000, height: 1000 },
  nearDesktop: { width: 1601, height: 900 }, // a hair wider than 16:9
  nearMobile: { width: 750, height: 1001 }, // a hair taller than 3:4
};

const free = (image: { width: number; height: number }, frame: { width: number; height: number }) =>
  freeAxesFromOverflow(coverOverflow(image, frame));

describe('coverOverflow — the axis that overflows follows the image, not the viewport', () => {
  it('portrait in desktop: overflows vertically only → Y free, X fitted', () => {
    // scale = max(320/800, 180/1200) = 0.4 → 320×480; overflowY = 300.
    const ov = coverOverflow(IMAGES.portrait, DESKTOP);
    expect(ov.overflowX).toBe(0);
    expect(ov.overflowY).toBeCloseTo(300, 6);
    expect(free(IMAGES.portrait, DESKTOP)).toEqual({ x: false, y: true });
  });

  it('portrait (2:3) in mobile (3:4): still taller than the frame → Y free, X fitted', () => {
    // 0.667 < 0.75, so even the phone frame is wider than this image.
    // scale = max(210/800, 280/1200) = 0.2625 → 210×315; overflowY = 35.
    const ov = coverOverflow(IMAGES.portrait, MOBILE);
    expect(ov.overflowX).toBe(0);
    expect(ov.overflowY).toBeCloseTo(35, 6);
    expect(free(IMAGES.portrait, MOBILE)).toEqual({ x: false, y: true });
  });

  it('landscape (2:1) in desktop: WIDER than 16:9, so it overflows horizontally — X free, Y fitted', () => {
    // This is the case the old hint got wrong ("adjust the vertical framing").
    // scale = max(320/2000, 180/1000) = 0.18 → 360×180; overflowX = 40.
    const ov = coverOverflow(IMAGES.landscape, DESKTOP);
    expect(ov.overflowX).toBeCloseTo(40, 6);
    expect(ov.overflowY).toBe(0);
    expect(free(IMAGES.landscape, DESKTOP)).toEqual({ x: true, y: false });
  });

  it('landscape in mobile: overflows horizontally by a lot → X free', () => {
    // scale = max(210/2000, 280/1000) = 0.28 → 560×280; overflowX = 350.
    const ov = coverOverflow(IMAGES.landscape, MOBILE);
    expect(ov.overflowX).toBeCloseTo(350, 6);
    expect(ov.overflowY).toBe(0);
    expect(free(IMAGES.landscape, MOBILE)).toEqual({ x: true, y: false });
  });

  it('square in desktop: Y free; square in mobile: X free — the axis flips with the viewport', () => {
    expect(free(IMAGES.square, DESKTOP)).toEqual({ x: false, y: true }); // 320×320, overflowY 140
    expect(free(IMAGES.square, MOBILE)).toEqual({ x: true, y: false }); // 280×280, overflowX 70
  });

  it('near-matching shapes: sub-pixel overflow counts as none on BOTH axes', () => {
    expect(free(IMAGES.nearDesktop, DESKTOP)).toEqual({ x: false, y: false });
    expect(free(IMAGES.nearMobile, MOBILE)).toEqual({ x: false, y: false });
    // …but the same near-desktop image is decisively wider than a phone.
    expect(free(IMAGES.nearDesktop, MOBILE)).toEqual({ x: true, y: false });
  });

  it('never overflows on both axes — cover fits one axis exactly', () => {
    for (const image of Object.values(IMAGES)) {
      for (const frame of [DESKTOP, MOBILE]) {
        const f = free(image, frame);
        expect(f.x && f.y).toBe(false);
      }
    }
  });

  it('degenerate sizes give zero overflow rather than NaN or Infinity', () => {
    expect(coverOverflow({ width: 0, height: 0 }, DESKTOP)).toEqual({ scale: 1, overflowX: 0, overflowY: 0 });
    expect(coverOverflow(IMAGES.square, { width: 0, height: 0 })).toEqual({ scale: 1, overflowX: 0, overflowY: 0 });
  });
});

describe('freeAxesFromAspect — the same verdicts from ratios alone (drives the hint)', () => {
  const D = 16 / 9;
  const M = 3 / 4;
  const aspect = (s: { width: number; height: number }) => s.width / s.height;

  it('agrees with the pixel computation for every fixture', () => {
    for (const image of Object.values(IMAGES)) {
      expect(freeAxesFromAspect(aspect(image), D)).toEqual(free(image, DESKTOP));
      expect(freeAxesFromAspect(aspect(image), M)).toEqual(free(image, MOBILE));
    }
  });

  it('treats an unknown or invalid ratio as nothing to adjust', () => {
    expect(freeAxesFromAspect(0, D)).toEqual({ x: false, y: false });
    expect(freeAxesFromAspect(NaN, D)).toEqual({ x: false, y: false });
  });
});

describe('coverDragDelta — pointer pixels map 1:1 onto the image along the free axis only', () => {
  it('vertical overflow: a vertical drag moves Y by pixels ÷ overflow; a horizontal drag moves nothing', () => {
    const ov = coverOverflow(IMAGES.portrait, DESKTOP); // overflowY 300
    expect(coverDragDelta(0, -30, ov)).toEqual({ dX: 0, dY: 0.1 });
    expect(coverDragDelta(50, 0, ov)).toEqual({ dX: 0, dY: 0 });
  });

  it('horizontal overflow: a horizontal drag moves X by pixels ÷ overflow; a vertical drag moves nothing', () => {
    const ov = coverOverflow(IMAGES.landscape, DESKTOP); // overflowX 40
    expect(coverDragDelta(-20, 0, ov)).toEqual({ dX: 0.5, dY: 0 });
    expect(coverDragDelta(0, 80, ov)).toEqual({ dX: 0, dY: 0 });
  });

  it('a diagonal drag only moves the free axis — X and Y are never swapped', () => {
    const vertical = coverOverflow(IMAGES.portrait, DESKTOP);
    const horizontal = coverOverflow(IMAGES.landscape, DESKTOP);
    const v = coverDragDelta(-20, -30, vertical);
    const h = coverDragDelta(-20, -30, horizontal);
    expect(v).toEqual({ dX: 0, dY: 0.1 }); // −30px on a 300px overflow
    expect(h).toEqual({ dX: 0.5, dY: 0 }); // −20px on a 40px overflow
  });

  it('sign: dragging right or down carries the image right or down, i.e. DECREASES the fraction', () => {
    expect(coverDragDelta(+20, 0, coverOverflow(IMAGES.landscape, DESKTOP)).dX).toBeLessThan(0);
    expect(coverDragDelta(0, +30, coverOverflow(IMAGES.portrait, DESKTOP)).dY).toBeLessThan(0);
  });

  it('no overflow at all: no movement on either axis, however far the pointer goes', () => {
    const ov = coverOverflow(IMAGES.nearDesktop, DESKTOP);
    expect(coverDragDelta(500, 500, ov)).toEqual({ dX: 0, dY: 0 });
  });
});
