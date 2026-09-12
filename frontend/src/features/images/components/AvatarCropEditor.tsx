import type { KeyboardEvent } from 'react';
import type { useObjectPositionDrag } from '../useObjectPositionDrag';
import { naturalSizeOf } from '../useObjectPositionDrag';
import { avatarTransformStyle } from '@/lib/media';
import {
  AVATAR_MAX_ZOOM,
  AVATAR_MIN_ZOOM,
  AVATAR_ZOOM_STEP,
  DEFAULT_AVATAR_CROP,
  avatarCropAffordance,
  isDefaultAvatarCrop,
} from '../avatarCropEditor';

/**
 * The square crop viewport for a profile picture, with its hint, zoom and
 * reset. The character-page picker and the image library both render this,
 * so the two editors share one shape, one zoom range, one set of words and one
 * drawing function — `avatarTransformStyle`, the same one the character page
 * and the public Home render the saved crop with. What is framed here is what
 * is shown there.
 *
 * The viewport IS the crop: the image is clipped to it rather than shown on a
 * larger stage behind a mask, so there is nothing outside it to darken.
 */
interface Props {
  drag: ReturnType<typeof useObjectPositionDrag>;
  imageUrl: string;
}

const NUDGE_PX = 4;
const NUDGE_FAST_PX = 16;

export default function AvatarCropEditor({ drag, imageUrl }: Props) {
  const { hint, cursor } = avatarCropAffordance(drag.imageSize, drag.scale, drag.dragging);
  const isDefault = isDefaultAvatarCrop(drag.posX, drag.posY, drag.scale);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? NUDGE_FAST_PX : NUDGE_PX;
    const move: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
    };
    const delta = move[e.key];
    if (!delta) return;
    e.preventDefault();
    drag.nudge(delta[0], delta[1]);
  };

  return (
    <div className="space-y-2">
      <p className="text-xs text-ink-3 text-center" data-testid="avatar-crop-hint">{hint}</p>
      <div
        ref={drag.frameRef}
        data-testid="avatar-preview-frame"
        role="group"
        aria-label="Profile picture crop. Use the arrow keys to move the image."
        tabIndex={0}
        onKeyDown={onKeyDown}
        onMouseDown={(e) => { e.preventDefault(); drag.startDrag(e.clientX, e.clientY); }}
        onTouchStart={(e) => drag.startDrag(e.touches[0].clientX, e.touches[0].clientY)}
        className="relative overflow-hidden bg-surface-elevated select-none w-40 h-40 rounded-2xl mx-auto border border-edge-md focus:outline-none focus-visible:ring-2 focus-visible:ring-gem"
        style={{ cursor, touchAction: 'none' }}
      >
        <img
          ref={(el) => { if (el?.complete) drag.setImageSize(naturalSizeOf(el)); }}
          onLoad={(e) => drag.setImageSize(naturalSizeOf(e.currentTarget))}
          src={imageUrl}
          alt="Preview"
          draggable={false}
          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
          style={avatarTransformStyle(drag.scale, drag.posX, drag.posY)}
        />
        {/* Inner ring, so the square reads as the picture's edge rather than a box the image sits in */}
        <div aria-hidden className="absolute inset-0 rounded-2xl pointer-events-none shadow-[inset_0_0_0_1px_rgba(255,255,255,0.18)]" />
      </div>
      <div className="flex items-center gap-2 justify-center">
        <span className="text-xs text-ink-3">Zoom</span>
        <input
          type="range"
          aria-label="Zoom"
          min={AVATAR_MIN_ZOOM}
          max={AVATAR_MAX_ZOOM}
          step={AVATAR_ZOOM_STEP}
          value={drag.scale}
          onChange={(e) => drag.setScale(Number(e.target.value))}
          className="w-40 accent-[rgb(var(--gem))]"
          onMouseDown={(e) => e.stopPropagation()}
          onTouchStart={(e) => e.stopPropagation()}
        />
        <span className="text-xs text-ink-3 w-8 tabular-nums">{drag.scale.toFixed(1)}×</span>
      </div>
      <div className="flex items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => drag.reset(DEFAULT_AVATAR_CROP.x, DEFAULT_AVATAR_CROP.y, DEFAULT_AVATAR_CROP.scale)}
          disabled={isDefault}
          className="text-xs text-ink-2 hover:text-ink underline-offset-2 hover:underline transition-colors disabled:opacity-40 disabled:no-underline disabled:cursor-default"
        >
          Reset crop
        </button>
      </div>
      <p className="text-xs text-ink-3 text-center">The original image is never altered.</p>
    </div>
  );
}
