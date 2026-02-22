import { useState } from 'react';
import type { CharacterImageRead } from '@/features/characterCreation/shared/types';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';

interface Props {
  image: CharacterImageRead;
  onClick?: () => void;
  // Callbacks may be async (e.g. API call); ImageCard awaits them to track in-flight state.
  onUseInPost?: (image: CharacterImageRead) => void | Promise<void>;
  onSetAsCover?: (image: CharacterImageRead) => void | Promise<void>;
}

export default function ImageCard({ image, onClick, onUseInPost, onSetAsCover }: Props) {
  const hasActions = onUseInPost || onSetAsCover;
  // Tracks which action button is currently in-flight. Null means idle.
  const [actionBusy, setActionBusy] = useState<null | 'useInPost' | 'setCover'>(null);

  const handleUseInPost = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (actionBusy || !onUseInPost) return;
    setActionBusy('useInPost');
    try { await onUseInPost(image); } finally { setActionBusy(null); }
  };

  const handleSetAsCover = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (actionBusy || !onSetAsCover) return;
    setActionBusy('setCover');
    try { await onSetAsCover(image); } finally { setActionBusy(null); }
  };

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
              disabled={actionBusy !== null}
              onClick={handleUseInPost}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-owl-600 hover:bg-owl-500 text-white transition-colors truncate disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {actionBusy === 'useInPost' ? 'Saving…' : 'Use in Post'}
            </button>
          )}
          {onSetAsCover && (
            <button
              type="button"
              disabled={actionBusy !== null}
              onClick={handleSetAsCover}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 transition-colors truncate disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {actionBusy === 'setCover' ? 'Saving…' : 'Set as Cover'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
