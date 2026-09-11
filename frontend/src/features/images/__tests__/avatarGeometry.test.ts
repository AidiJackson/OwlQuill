/**
 * Avatar crop geometry — what the stored position spans, which axis a drag
 * may move at a given zoom, and that the CSS composition really does what the
 * arithmetic says.
 *
 * Frame is the editors' 160×160 square. Overflows are worked out by hand:
 *   portrait 800×1200 → cover-fit 160×240, overflowY 80
 *   landscape 2000×1000 → cover-fit 320×160, overflowX 160
 *   square 1000×1000 → cover-fit 160×160, no overflow
 */
import { describe, expect, it } from 'vitest';
import {
  avatarDragDelta,
  avatarFreeAxes,
  avatarOverflow,
  avatarRenderedOffset,
} from '../avatarGeometry';

const F = { width: 160, height: 160 };
const PORTRAIT = { width: 800, height: 1200 };
const LANDSCAPE = { width: 2000, height: 1000 };
const SQUARE = { width: 1000, height: 1000 };
const NEAR_SQUARE = { width: 1001, height: 1000 }; // 0.16px of overflow: none

const free = (image: { width: number; height: number } | null, scale: number) =>
  avatarFreeAxes(avatarOverflow(image, F, scale));

describe('avatarOverflow — cover-fit overflow scaled, plus what the zoom adds', () => {
  it('at minimum zoom only the cover-fit overflow exists, on the longer axis', () => {
    expect(avatarOverflow(PORTRAIT, F, 1)).toEqual({ overflowX: 0, overflowY: 80 });
    expect(avatarOverflow(LANDSCAPE, F, 1)).toEqual({ overflowX: 160, overflowY: 0 });
    expect(avatarOverflow(SQUARE, F, 1)).toEqual({ overflowX: 0, overflowY: 0 });
  });

  it('above minimum zoom the zoom overflow is added on both axes and the fit overflow scales', () => {
    // portrait at 1.5: Y = 1.5·80 + 0.5·160 = 200; X = 0 + 0.5·160 = 80
    expect(avatarOverflow(PORTRAIT, F, 1.5)).toEqual({ overflowX: 80, overflowY: 200 });
    // landscape at 2: X = 2·160 + 160 = 480; Y = 160
    expect(avatarOverflow(LANDSCAPE, F, 2)).toEqual({ overflowX: 480, overflowY: 160 });
    // square at 2.5: both 1.5·160 = 240
    expect(avatarOverflow(SQUARE, F, 2.5)).toEqual({ overflowX: 240, overflowY: 240 });
  });

  it('grows monotonically with zoom on every axis', () => {
    for (const image of [PORTRAIT, LANDSCAPE, SQUARE]) {
      let prev = avatarOverflow(image, F, 1);
      for (const s of [1.05, 1.5, 2, 2.5, 3]) {
        const cur = avatarOverflow(image, F, s);
        expect(cur.overflowX).toBeGreaterThanOrEqual(prev.overflowX);
        expect(cur.overflowY).toBeGreaterThanOrEqual(prev.overflowY);
        prev = cur;
      }
    }
  });

  it('with no image size known, only the zoom overflow is used (the safe fallback)', () => {
    expect(avatarOverflow(null, F, 1)).toEqual({ overflowX: 0, overflowY: 0 });
    expect(avatarOverflow(null, F, 2)).toEqual({ overflowX: 160, overflowY: 160 });
  });

  it('treats a scale below 1 or a missing frame as inert rather than negative', () => {
    expect(avatarOverflow(PORTRAIT, F, 0.5)).toEqual({ overflowX: 0, overflowY: 80 });
    expect(avatarOverflow(PORTRAIT, { width: 0, height: 0 }, 2)).toEqual({ overflowX: 0, overflowY: 0 });
  });
});

describe('avatarFreeAxes — which axis a drag may move', () => {
  it('portrait at zoom 1: vertical only — the reported defect', () => {
    expect(free(PORTRAIT, 1)).toEqual({ x: false, y: true });
  });

  it('landscape at zoom 1: horizontal only', () => {
    expect(free(LANDSCAPE, 1)).toEqual({ x: true, y: false });
  });

  it('a square (or near enough) at zoom 1: nothing to move', () => {
    expect(free(SQUARE, 1)).toEqual({ x: false, y: false });
    expect(free(NEAR_SQUARE, 1)).toEqual({ x: false, y: false });
  });

  it('any zoom above 1 frees both axes for every shape', () => {
    for (const image of [PORTRAIT, LANDSCAPE, SQUARE, NEAR_SQUARE]) {
      expect(free(image, 1.5)).toEqual({ x: true, y: true });
      expect(free(image, 2.5)).toEqual({ x: true, y: true });
    }
  });
});

describe('avatarDragDelta — 1:1 with the image on a free axis, zero on a fitted one', () => {
  it('portrait at zoom 1: a vertical drag moves Y by px ÷ 80, a horizontal drag moves nothing', () => {
    const ov = avatarOverflow(PORTRAIT, F, 1);
    expect(avatarDragDelta(0, -8, ov)).toEqual({ dX: 0, dY: 0.1 });
    expect(avatarDragDelta(40, 0, ov)).toEqual({ dX: 0, dY: 0 });
  });

  it('landscape at zoom 1: a horizontal drag moves X by px ÷ 160, a vertical drag moves nothing', () => {
    const ov = avatarOverflow(LANDSCAPE, F, 1);
    expect(avatarDragDelta(-16, 0, ov)).toEqual({ dX: 0.1, dY: 0 });
    expect(avatarDragDelta(0, 40, ov)).toEqual({ dX: 0, dY: 0 });
  });

  it('a diagonal drag never leaks into the fitted axis — X and Y are not swapped', () => {
    expect(avatarDragDelta(-16, -8, avatarOverflow(PORTRAIT, F, 1))).toEqual({ dX: 0, dY: 0.1 });
    expect(avatarDragDelta(-16, -8, avatarOverflow(LANDSCAPE, F, 1))).toEqual({ dX: 0.1, dY: 0 });
  });

  it('zoomed: both axes move, each over its own total overflow', () => {
    const ov = avatarOverflow(PORTRAIT, F, 1.5); // X 80, Y 200
    expect(avatarDragDelta(-8, -20, ov)).toEqual({ dX: 0.1, dY: 0.1 });
  });

  it('sign: dragging right or down carries the image right or down, i.e. DECREASES the fraction', () => {
    expect(avatarDragDelta(16, 0, avatarOverflow(LANDSCAPE, F, 1)).dX).toBeLessThan(0);
    expect(avatarDragDelta(0, 8, avatarOverflow(PORTRAIT, F, 1)).dY).toBeLessThan(0);
  });
});

describe('avatarRenderedOffset — the CSS composition matches −p · O and never exposes blank space', () => {
  const SCALES = [1, 1.5, 2, 2.5];
  const POSITIONS = [0, 0.25, 0.5, 0.75, 1];

  it('the leading edge lands at exactly −position × total overflow, at every zoom', () => {
    for (const image of [PORTRAIT, LANDSCAPE, SQUARE]) {
      for (const s of SCALES) {
        const ov = avatarOverflow(image, F, s);
        for (const p of POSITIONS) {
          const box = avatarRenderedOffset(image, F, s, p, p);
          expect(box.left).toBeCloseTo(-p * ov.overflowX, 6);
          expect(box.top).toBeCloseTo(-p * ov.overflowY, 6);
        }
      }
    }
  });

  it('position 0 shows the source’s top/left edge and 1 its bottom/right — the whole source is reachable', () => {
    for (const s of SCALES) {
      const top = avatarRenderedOffset(PORTRAIT, F, s, 0.5, 0);
      expect(top.top).toBeCloseTo(0, 6); // the head is in view
      const bottom = avatarRenderedOffset(PORTRAIT, F, s, 0.5, 1);
      expect(bottom.top + bottom.height).toBeCloseTo(F.height, 6);

      const left = avatarRenderedOffset(LANDSCAPE, F, s, 0, 0.5);
      expect(left.left).toBeCloseTo(0, 6);
      const right = avatarRenderedOffset(LANDSCAPE, F, s, 1, 0.5);
      expect(right.left + right.width).toBeCloseTo(F.width, 6);
    }
  });

  it('the frame is always fully covered: no blank space at any position or zoom', () => {
    for (const image of [PORTRAIT, LANDSCAPE, SQUARE, NEAR_SQUARE]) {
      for (const s of SCALES) {
        for (const px of POSITIONS) {
          for (const py of POSITIONS) {
            const box = avatarRenderedOffset(image, F, s, px, py);
            expect(box.left).toBeLessThanOrEqual(1e-6);
            expect(box.top).toBeLessThanOrEqual(1e-6);
            expect(box.left + box.width).toBeGreaterThanOrEqual(F.width - 1e-6);
            expect(box.top + box.height).toBeGreaterThanOrEqual(F.height - 1e-6);
          }
        }
      }
    }
  });

  it('centre at zoom 1 is the plain centred cover crop — the unchanged default', () => {
    const box = avatarRenderedOffset(PORTRAIT, F, 1, 0.5, 0.5);
    expect(box).toEqual({ left: 0, top: -40, width: 160, height: 240 });
  });
});
