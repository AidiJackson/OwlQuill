import { useState } from 'react';
import { Check, X, ZoomIn } from 'lucide-react';
import type { IdentityPackResponse } from '../shared/types';
import { resolveImageUrl } from '../shared/api';

interface Props {
  pack: IdentityPackResponse;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onNext: () => void;
  onBack: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  anchor_front: 'Front',
  anchor_three_quarter: '¾ View',
  anchor_torso: 'Torso',
};

export default function StepSelect({ pack, selectedIndex, onSelect, onNext, onBack }: Props) {
  const [enlargedIndex, setEnlargedIndex] = useState<number | null>(null);

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <h2 className="text-xl font-semibold text-gray-100">Review Your Identity Pack</h2>
        <p className="text-sm text-gray-400">
          Tap an image to enlarge it. Choose the one that feels closest — it will be your
          character's primary portrait.
        </p>
      </div>

      {/* Image grid */}
      <div className="grid grid-cols-3 gap-3">
        {pack.images.map((img, i) => {
          const role = (img.metadata_json?.pack_role as string) || '';
          const isSelected = selectedIndex === i;
          return (
            <button
              key={img.id}
              type="button"
              onClick={() => onSelect(i)}
              className={`rounded-lg overflow-hidden border-2 transition-all relative group ${
                isSelected
                  ? 'border-owl-500 ring-2 ring-owl-500/30'
                  : 'border-gray-800 hover:border-gray-600'
              }`}
            >
              <img
                src={resolveImageUrl(img.url)}
                alt={ROLE_LABELS[role] || 'Pack image'}
                className="w-full aspect-[2/3] object-cover"
              />
              {/* Enlarge button */}
              <div
                className="absolute top-2 right-2 p-1.5 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                onClick={(e) => {
                  e.stopPropagation();
                  setEnlargedIndex(i);
                }}
              >
                <ZoomIn className="w-3.5 h-3.5" />
              </div>
              {/* Selected badge */}
              {isSelected && (
                <div className="absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-owl-600 text-white text-xs font-medium px-2 py-0.5 rounded-full">
                  <Check className="w-3 h-3" />
                  Primary
                </div>
              )}
              <div className="px-2 py-1.5 text-center bg-gray-900">
                <span className="text-xs text-gray-400">{ROLE_LABELS[role] || role}</span>
              </div>
            </button>
          );
        })}
      </div>

      {/* Enlarged overlay */}
      {enlargedIndex !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => setEnlargedIndex(null)}
        >
          <div className="relative max-w-md w-full" onClick={(e) => e.stopPropagation()}>
            <img
              src={resolveImageUrl(pack.images[enlargedIndex].url)}
              alt="Enlarged preview"
              className="w-full rounded-lg"
            />
            <button
              type="button"
              onClick={() => setEnlargedIndex(null)}
              className="absolute top-3 right-3 p-1.5 rounded-full bg-black/60 text-white hover:bg-black/80 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      <div className="flex justify-between pt-2">
        <button className="btn btn-secondary" onClick={onBack}>
          Back
        </button>
        <button className="btn btn-primary" onClick={onNext}>
          Continue to Lock
        </button>
      </div>
    </div>
  );
}
