import { useEffect, useRef, useState } from 'react';
import type { useObjectPositionDrag } from '../useObjectPositionDrag';
import { freeAxesFromAspect, type FreeAxes } from '../coverGeometry';

/**
 * The cover framing preview, shared by both editors that write
 * `cover_position_x/y` — the character profile's reposition picker and the
 * image library's cover editor. One component so the two can never again show
 * the creator different things about the same stored value.
 *
 * WHY THERE ARE TWO VIEWPORTS AND NOT ONE FRAME
 * ---------------------------------------------
 * The stored framing is two fractions applied as CSS `object-position` under
 * `object-fit: cover`, and `cover` only leaves slack on the axis where the
 * scaled image overflows its frame. Which axis that is depends entirely on the
 * FRAME's aspect ratio, and the Character Home hero is wide on a desktop
 * (~1.8:1) and TALLER THAN IT IS WIDE on a phone (~0.7:1).
 *
 * So the two viewports do not merely look different — the axis that does
 * anything can flip between them. For a portrait or square image the desktop
 * frame overflows vertically (Y frames the shot) and the mobile frame
 * horizontally (X does). A single wide preview (this used to be `aspect-[3/1]`)
 * therefore left X pinned and UNREACHABLE, while X is the axis that decides
 * what a phone actually shows — and a share link is most often opened on a
 * phone. The toggle is not decoration; it is the only way to set both halves of
 * a value the product has always stored.
 *
 * WHICH AXIS IS FREE IS NOT A PROPERTY OF THE VIEWPORT ALONE. It is the pair —
 * image shape against frame shape — that decides: a landscape wider than 16:9
 * overflows the desktop frame HORIZONTALLY, so there Y is the inert axis. The
 * hint under the toggle used to be a fixed string per viewport and was simply
 * wrong for such an image ("adjust the vertical framing" on an axis that
 * could not move). It is now computed from the image's natural size, reported
 * to the drag hook so the drag itself follows the same geometry — see
 * `coverGeometry`.
 *
 * WHAT THIS DELIBERATELY DOES NOT CLAIM
 * -------------------------------------
 * It is an APPROXIMATION, not WYSIWYG, and the wording in the UI says so. The
 * real heroes are sized in `vh` and their height includes the character's own
 * content — a character with an alias gets a taller hero, and therefore a
 * different crop, from the identical stored value. No fixed aspect can be exact
 * for every character on every screen. These two ratios bring the error down
 * from roughly fourfold to a few percent, which is the whole of the claim.
 *
 * It also holds no state of its own beyond WHICH viewport is being previewed.
 * Position lives in `useObjectPositionDrag`, which is owned by the caller and
 * never re-created here, so switching viewport cannot disturb the values and
 * cannot save anything — there is no API call in this file.
 */

/** The two shapes a cover is really seen in. */
export type CoverPreviewViewport = 'desktop' | 'mobile';

/**
 * Frame geometry per viewport, and the axis each one can actually express.
 *
 * ``16/9`` (1.78) sits between the authenticated hero (~1.74) and the public
 * Character Home hero (~1.83), within about 3% of both. ``3/4`` (0.75) sits
 * between their mobile counterparts (~0.68 and ~0.74).
 *
 * The mobile frame is WIDTH-CONSTRAINED rather than full width, and that is
 * structural rather than stylistic: the picker dialog is `max-w-lg` with `p-5`,
 * so a full-width 3:4 frame would stand about 629px tall and break straight
 * through the dialog's own `max-h-[90vh]`. Only the ratio matters to
 * `object-fit: cover`, so rendering it at a phone-like width is exact, not a
 * compromise.
 */
const VIEWPORTS: Record<
  CoverPreviewViewport,
  { label: string; aspect: number; frameClass: string }
> = {
  desktop: {
    label: 'Desktop',
    aspect: 16 / 9,
    frameClass: 'w-full aspect-[16/9]',
  },
  mobile: {
    label: 'Mobile',
    aspect: 3 / 4,
    frameClass: 'w-[210px] mx-auto aspect-[3/4]',
  },
};

/**
 * What the creator can actually do in this viewport with this image. Worded
 * from the free axis, never from the viewport: the desktop frame is not
 * "vertical" — a wide enough image makes it horizontal.
 */
export function framingHint(free: FreeAxes | null, viewportLabel: string): string {
  if (!free || (free.x && free.y)) return 'Drag the image to adjust its framing.';
  if (free.y) return 'Drag up or down to adjust the vertical framing.';
  if (free.x) return 'Drag left or right to adjust the horizontal framing.';
  return `This image fills the ${viewportLabel.toLowerCase()} viewport exactly — nothing to adjust here.`;
}

interface Props {
  /**
   * The caller's live drag state. Passed whole rather than as loose props so
   * both editors are provably driving the SAME hook instance — the shared
   * `cover_position_x/y` pair — and neither can accidentally introduce a second
   * source of truth.
   */
  drag: ReturnType<typeof useObjectPositionDrag>;
  /** Already-resolved image url to preview. */
  imageUrl: string;
}

export default function CoverFramingPreview({ drag, imageUrl }: Props) {
  // The ONLY state here. Switching it re-renders a differently shaped frame;
  // it does not touch posX/posY, does not reset the drag, and writes nothing.
  // `useObjectPositionDrag` reads the frame's dimensions from the DOM on every
  // pointer move rather than caching them, so a frame that changes shape
  // between drags needs no notification and no second drag implementation.
  const [viewport, setViewport] = useState<CoverPreviewViewport>('desktop');
  const { label, aspect, frameClass } = VIEWPORTS[viewport];

  // The image's natural size, once known. It feeds two things and nothing
  // else: the drag hook (so the pointer moves the image along its real free
  // axis) and the hint below (so it names that axis). A new url forgets the
  // old size until the new image reports its own — the hook is told the same,
  // so a drag in between falls back to its size-less behaviour rather than
  // using the previous image's geometry.
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [imageSize, setImageSize] = useState<{ width: number; height: number } | null>(null);
  const reportSize = (img: HTMLImageElement | null) => {
    if (!img || !img.naturalWidth || !img.naturalHeight) return;
    const size = { width: img.naturalWidth, height: img.naturalHeight };
    setImageSize(size);
    drag.setImageSize(size);
  };
  useEffect(() => {
    setImageSize(null);
    drag.setImageSize(null);
    // A cached image can be complete before React attaches onLoad; ask now
    // rather than wait for an event that may already have fired.
    if (imgRef.current?.complete) reportSize(imgRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageUrl]);

  const free = imageSize ? freeAxesFromAspect(imageSize.width / imageSize.height, aspect) : null;
  const hint = framingHint(free, label);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div
          role="group"
          aria-label="Preview viewport"
          className="inline-flex rounded-lg border border-edge overflow-hidden"
        >
          {(Object.keys(VIEWPORTS) as CoverPreviewViewport[]).map((key) => {
            const active = key === viewport;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setViewport(key)}
                aria-pressed={active}
                className={`px-2.5 py-1 text-xs font-medium transition-colors ${
                  active
                    ? 'bg-gem text-gem-ink'
                    : 'bg-transparent text-ink-3 hover:text-ink'
                }`}
              >
                {VIEWPORTS[key].label}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-ink-2" data-testid="cover-framing-hint">{hint}</p>
      </div>

      <div
        ref={drag.frameRef}
        data-testid="cover-preview-frame"
        data-viewport={viewport}
        data-free-x={free ? String(free.x) : undefined}
        data-free-y={free ? String(free.y) : undefined}
        onMouseDown={(e) => { e.preventDefault(); drag.startDrag(e.clientX, e.clientY); }}
        onTouchStart={(e) => { e.preventDefault(); drag.startDrag(e.touches[0].clientX, e.touches[0].clientY); }}
        className={`relative overflow-hidden rounded-xl bg-surface-elevated cursor-move select-none ${frameClass}`}
        style={{ touchAction: 'none' }}
      >
        <img
          ref={imgRef}
          src={imageUrl}
          alt="Cover preview"
          draggable={false}
          onLoad={(e) => reportSize(e.currentTarget)}
          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
          style={{ objectPosition: `${drag.posX * 100}% ${drag.posY * 100}%` }}
        />
      </div>

      <p className="text-[11px] text-ink-3">
        Drag to reposition. Previews are approximate — the original image is never altered.
      </p>
    </div>
  );
}
