import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';

interface Props {
  image: CharacterImageRead;
  onClick?: () => void;
  onUseInPost?: (image: CharacterImageRead) => void;
  onSetAsCover?: (image: CharacterImageRead) => void;
}

export default function ImageCard({ image, onClick, onUseInPost, onSetAsCover }: Props) {
  const hasActions = onUseInPost || onSetAsCover;

  return (
    <div className="relative group rounded-lg overflow-hidden border border-gray-800 bg-gray-900 hover:border-gray-600 transition-colors">
      <button
        type="button"
        className="block w-full cursor-pointer"
        onClick={onClick}
      >
        <img
          src={resolveImageUrl(image.url)}
          alt={image.kind.replace(/_/g, ' ')}
          className="w-full aspect-[2/3] object-cover"
        />
      </button>

      {hasActions && (
        <div
          className={[
            'absolute bottom-0 inset-x-0',
            'bg-gradient-to-t from-black/80 to-transparent',
            'px-2 py-2 flex gap-1.5',
            // Desktop: show on hover; touch: always visible
            'opacity-0 group-hover:opacity-100',
            'pointer-events-none group-hover:pointer-events-auto',
            'transition-opacity duration-150',
            '[@media(pointer:coarse)]:opacity-100 [@media(pointer:coarse)]:pointer-events-auto',
          ].join(' ')}
        >
          {onUseInPost && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onUseInPost(image); }}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-owl-600 hover:bg-owl-500 text-white transition-colors truncate"
            >
              Use in Post
            </button>
          )}
          {onSetAsCover && (
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onSetAsCover(image); }}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors truncate"
            >
              Set as Cover
            </button>
          )}
        </div>
      )}
    </div>
  );
}
