import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import ImageCard, { type BodyAnchorOption } from './ImageCard';

interface Props {
  images: CharacterImageRead[];
  onImageClick?: (index: number) => void;
  onUseInPost?: (image: CharacterImageRead) => void;
  onSetAsCover?: (image: CharacterImageRead) => void;
  /** Owner-only body anchor assignment options forwarded to each card. */
  bodyAnchorOptions?: BodyAnchorOption[];
  onBodyAnchorAssign?: (image: CharacterImageRead, value: string) => void | Promise<void>;
  /** Renders a pulsing placeholder tile as the first cell while a scene is generating. */
  showPlaceholder?: boolean;
  /** ID of the most-recently generated image — receives a fade-in transition. */
  newestId?: number | null;
  /** Whether the newest image has reached its opaque end-state (driven by a RAF tick in the parent). */
  newestVisible?: boolean;
}

export default function ImageGrid({
  images,
  onImageClick,
  onUseInPost,
  onSetAsCover,
  bodyAnchorOptions,
  onBodyAnchorAssign,
  showPlaceholder,
  newestId,
  newestVisible,
}: Props) {
  if (images.length === 0 && !showPlaceholder) return null;

  return (
    <div className="grid grid-cols-3 gap-3">
      {showPlaceholder && (
        <div className="rounded-lg border border-edge bg-surface-elevated aspect-[2/3] animate-pulse" />
      )}

      {images.map((img, idx) => {
        const isNewest = newestId != null && img.id === newestId;
        return (
          <div
            key={img.id}
            className={
              isNewest
                ? `transition-opacity duration-500 ${newestVisible ? 'opacity-100' : 'opacity-0'}`
                : undefined
            }
          >
            <ImageCard
              image={img}
              onClick={onImageClick ? () => onImageClick(idx) : undefined}
              onUseInPost={onUseInPost}
              onSetAsCover={onSetAsCover}
              bodyAnchorOptions={bodyAnchorOptions}
              onBodyAnchorAssign={onBodyAnchorAssign}
            />
          </div>
        );
      })}
    </div>
  );
}
