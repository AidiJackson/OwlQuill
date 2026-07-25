import { useState, useRef, useEffect } from 'react';
import { ChevronDown } from 'lucide-react';
import type { CharacterGalleryImage } from '@/lib/types';
import { resolveImageUrl } from '@/features/characterCreation/shared/api';

export interface BodyAnchorOption {
  value: string;
  label: string;
}

interface Props {
  /** Public-safe shape — the card reads only id/kind/url, never prompt or
   *  provider, so it renders correctly for a viewer the server gave nothing
   *  else to. */
  image: CharacterGalleryImage;
  onClick?: () => void;
  onUseInPost?: (image: CharacterGalleryImage) => void | Promise<void>;
  onSetAsCover?: (image: CharacterGalleryImage) => void | Promise<void>;
  /** Owner-only body anchor assignment options. When provided, renders a dropdown. */
  bodyAnchorOptions?: BodyAnchorOption[];
  onBodyAnchorAssign?: (image: CharacterGalleryImage, value: string) => void | Promise<void>;
}

export default function ImageCard({
  image,
  onClick,
  onUseInPost,
  onSetAsCover,
  bodyAnchorOptions,
  onBodyAnchorAssign,
}: Props) {
  const hasBodyAnchor = bodyAnchorOptions && bodyAnchorOptions.length > 0 && onBodyAnchorAssign;
  const hasActions = onUseInPost || onSetAsCover || hasBodyAnchor;
  const [actionBusy, setActionBusy] = useState<null | 'useInPost' | 'setCover' | 'anchor'>(null);
  const [anchorMenuOpen, setAnchorMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!anchorMenuOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setAnchorMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [anchorMenuOpen]);

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

  const handleAnchorOption = async (e: React.MouseEvent, value: string) => {
    e.stopPropagation();
    if (actionBusy || !onBodyAnchorAssign) return;
    setAnchorMenuOpen(false);
    setActionBusy('anchor');
    try { await onBodyAnchorAssign(image, value); } finally { setActionBusy(null); }
  };

  return (
    <div className="relative group rounded-lg overflow-hidden border border-edge bg-surface hover:border-edge-md transition-colors">
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
              className="flex-1 text-xs px-2 py-1.5 rounded bg-gem hover:bg-gem/90 text-gem-ink transition-colors truncate disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {actionBusy === 'useInPost' ? 'Saving…' : 'Use in Post'}
            </button>
          )}
          {onSetAsCover && (
            <button
              type="button"
              disabled={actionBusy !== null}
              onClick={handleSetAsCover}
              className="flex-1 text-xs px-2 py-1.5 rounded bg-surface-overlay hover:bg-surface-overlay text-ink transition-colors truncate disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {actionBusy === 'setCover' ? 'Saving…' : 'Set as Cover'}
            </button>
          )}
          {hasBodyAnchor && (
            <div ref={menuRef} className="relative flex-shrink-0">
              <button
                type="button"
                disabled={actionBusy !== null}
                onClick={(e) => { e.stopPropagation(); setAnchorMenuOpen(v => !v); }}
                className="flex items-center gap-0.5 text-xs px-2 py-1.5 rounded bg-violet-700/80 hover:bg-violet-600/80 text-violet-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Use as Anchor"
              >
                {actionBusy === 'anchor' ? '…' : 'Anchor'}
                <ChevronDown className="w-3 h-3" />
              </button>
              {anchorMenuOpen && (
                <div className="absolute bottom-full mb-1 right-0 z-20 min-w-max bg-surface-elevated border border-edge-md rounded-lg shadow-xl overflow-hidden">
                  {bodyAnchorOptions!.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={(e) => handleAnchorOption(e, opt.value)}
                      className="block w-full text-left text-xs px-3 py-2 text-ink hover:bg-surface-overlay transition-colors whitespace-nowrap"
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
