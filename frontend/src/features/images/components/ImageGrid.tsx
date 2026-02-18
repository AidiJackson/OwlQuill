import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import ImageCard from './ImageCard';

interface Props {
  images: CharacterImageRead[];
  onImageClick?: (index: number) => void;
  onUseInPost?: (image: CharacterImageRead) => void;
  onSetAsCover?: (image: CharacterImageRead) => void;
}

export default function ImageGrid({ images, onImageClick, onUseInPost, onSetAsCover }: Props) {
  if (images.length === 0) return null;

  return (
    <div className="grid grid-cols-3 gap-3">
      {images.map((img, idx) => (
        <ImageCard
          key={img.id}
          image={img}
          onClick={onImageClick ? () => onImageClick(idx) : undefined}
          onUseInPost={onUseInPost}
          onSetAsCover={onSetAsCover}
        />
      ))}
    </div>
  );
}
