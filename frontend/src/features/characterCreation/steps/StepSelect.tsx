import { useState } from 'react';
import { Check, X, ZoomIn } from 'lucide-react';
import type { V2PackResponse, V2PackCard } from '../shared/types';
import { V2_SLOT_LABELS } from '../shared/types';
import { resolveImageUrl } from '../shared/api';

interface Props {
  pack: V2PackResponse;
  selectedIndex: number;
  onSelect: (index: number) => void;
  onNext: () => void;
  onBack: () => void;
}

const FACE_ORDER = ['face_front', 'face_left_3q', 'face_right_3q', 'face_profile', 'face_expression'];
const BODY_ORDER = [
  'body_front', 'body_left', 'body_right', 'body_back',
  'torso_front', 'torso_side', 'standing_relaxed', 'seated_relaxed',
];

export default function StepSelect({ pack, selectedIndex, onSelect, onNext, onBack }: Props) {
  const [enlarged, setEnlarged] = useState<string | null>(null);

  const indexOfSlot = (slot: string) => pack.cards.findIndex((c) => c.slot === slot);

  const renderSection = (title: string, slots: string[], selectable: boolean) => (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-ink-2">{title}</h3>
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
        {slots.map((slot) => {
          const idx = indexOfSlot(slot);
          const card: V2PackCard | undefined = idx >= 0 ? pack.cards[idx] : undefined;
          const url = card?.url ? resolveImageUrl(card.url) : null;
          const isSelected = selectable && idx === selectedIndex;
          return (
            <button
              key={slot}
              type="button"
              onClick={() => selectable && idx >= 0 && onSelect(idx)}
              className={`rounded-lg overflow-hidden border-2 transition-all relative group ${
                isSelected ? 'border-gem/50 ring-2 ring-gem/40' : 'border-edge hover:border-edge-md'
              } ${selectable ? 'cursor-pointer' : 'cursor-default'}`}
            >
              {url ? (
                <img src={url} alt={V2_SLOT_LABELS[slot] || slot} className="w-full aspect-[2/3] object-cover" />
              ) : (
                <div className="w-full aspect-[2/3] bg-surface-elevated" />
              )}
              {url && (
                <div
                  className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                  onClick={(e) => { e.stopPropagation(); setEnlarged(url); }}
                >
                  <ZoomIn className="w-3 h-3" />
                </div>
              )}
              {isSelected && (
                <div className="absolute bottom-1.5 left-1/2 -translate-x-1/2 flex items-center gap-1 bg-gem text-gem-ink text-[10px] font-medium px-1.5 py-0.5 rounded-full">
                  <Check className="w-2.5 h-2.5" />
                  Primary
                </div>
              )}
              <div className="px-1.5 py-1 text-center bg-surface">
                <span className="text-[11px] text-ink-2">{V2_SLOT_LABELS[slot] || slot}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <h2 className="text-xl font-semibold text-ink">Review Your Identity Pack</h2>
        <p className="text-sm text-ink-2">
          Your full visual canon. Pick a face card as your primary portrait — tap any image to enlarge.
        </p>
      </div>

      {renderSection('Face', FACE_ORDER, true)}
      {renderSection('Body', BODY_ORDER, false)}
      {pack.marks.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-ink-2">Details</h3>
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
            {pack.marks.map((m) => {
              const url = m.detail_crop_url ? resolveImageUrl(m.detail_crop_url) : null;
              return (
                <div key={m.mark_id} className="rounded-lg overflow-hidden border border-edge">
                  {url ? (
                    <button type="button" onClick={() => setEnlarged(url)} className="block w-full">
                      <img src={url} alt={m.label} className="w-full aspect-[2/3] object-cover" />
                    </button>
                  ) : (
                    <div className="w-full aspect-[2/3] bg-surface-elevated" />
                  )}
                  <div className="px-1.5 py-1 text-center bg-surface">
                    <span className="text-[11px] text-ink-2 truncate block">{m.label}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {enlarged && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => setEnlarged(null)}
        >
          <div className="relative max-w-md w-full" onClick={(e) => e.stopPropagation()}>
            <img src={enlarged} alt="Enlarged preview" className="w-full rounded-lg" />
            <button
              type="button"
              onClick={() => setEnlarged(null)}
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
          Choose this version
        </button>
      </div>
    </div>
  );
}
