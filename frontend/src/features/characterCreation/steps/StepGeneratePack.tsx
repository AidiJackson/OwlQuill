import { useState } from 'react';
import { ImageIcon, RefreshCw, ZoomIn, X } from 'lucide-react';
import type {
  V2PackResponse,
  V2PackCard,
  IdentityPackResponse,
  IdentitySpec,
  BodyMorphology,
} from '../shared/types';
import { V2_SLOT_LABELS, BODY_HEIGHT_OPTIONS, BODY_BUILD_OPTIONS } from '../shared/types';
import {
  generateV2Pack,
  patchBodyCanon,
  generateIdentityPack,
  resolveImageUrl,
} from '../shared/api';

interface Props {
  characterId: number;
  vibeText: string;
  identitySpec?: IdentitySpec | null;
  bodyMorphology: BodyMorphology;
  onBodyMorphologyChange: (m: BodyMorphology) => void;
  pack: V2PackResponse | null;
  onPackGenerated: (pack: V2PackResponse) => void;
  onNext: () => void;
  onBack: () => void;
}

// Section ordering for the grouped review grid.
const FACE_ORDER = ['face_front', 'face_left_3q', 'face_right_3q', 'face_profile', 'face_expression'];
const BODY_ORDER = [
  'body_front', 'body_left', 'body_right', 'body_back',
  'torso_front', 'torso_side', 'standing_relaxed', 'seated_relaxed',
];

/** DEV-only escape hatch: map a legacy 4-anchor pack into the v2 shape. */
function legacyToV2(p: IdentityPackResponse): V2PackResponse {
  return {
    pack_id: p.pack_id,
    dry_run: false,
    cards: p.images.map((im) => {
      const role = (im.metadata_json?.pack_role as string) || '';
      return { slot: role, section: 'face', role, url: im.url, status: 'generated' };
    }),
    marks: [],
    total_spend: 0,
    image_count: p.images.length,
    regenerations: [],
    openai_fallback: [],
    gate_failed: [],
    errors: [],
    clean_pass: true,
  };
}

export default function StepGeneratePack({
  characterId,
  vibeText,
  identitySpec,
  bodyMorphology,
  onBodyMorphologyChange,
  pack,
  onPackGenerated,
  onNext,
  onBack,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [enlarged, setEnlarged] = useState<string | null>(null);

  // Debug fallback: legacy 4-anchor path stays reachable only via this DEV flag,
  // never as the default. Production users always get the v2 canon pack.
  const legacyDebug =
    import.meta.env.DEV && localStorage.getItem('useLegacyPack') === '1';

  const handleGenerate = async () => {
    if (loading) return;
    setLoading(true);
    setError('');
    try {
      if (legacyDebug) {
        const spec: IdentitySpec | null = identitySpec
          ? { ...identitySpec, body_height: bodyMorphology.height, body_build: bodyMorphology.build }
          : null;
        const legacy = await generateIdentityPack(characterId, undefined, vibeText, spec);
        onPackGenerated(legacyToV2(legacy));
        return;
      }
      // Persist body morphology so v2 generation grounds on it, then generate.
      await patchBodyCanon(characterId, {
        height: bodyMorphology.height,
        build: bodyMorphology.build,
      });
      const result = await generateV2Pack(characterId, { maxSpend: 8 });
      if (result.stopped) {
        setError('Generation stopped early. Please try again.');
      }
      onPackGenerated(result);
    } catch {
      setError("We couldn't generate the images right now. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const cardBySlot = new Map<string, V2PackCard>();
  (pack?.cards ?? []).forEach((c) => cardBySlot.set(c.slot, c));

  const renderSection = (title: string, slots: string[]) => (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-gray-300">{title}</h3>
      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
        {slots.map((slot) => {
          const card = cardBySlot.get(slot);
          const url = card?.url ? resolveImageUrl(card.url) : null;
          return (
            <div key={slot} className="rounded-lg overflow-hidden border border-gray-800">
              {url ? (
                <button
                  type="button"
                  onClick={() => setEnlarged(url)}
                  className="block w-full relative group"
                >
                  <img src={url} alt={V2_SLOT_LABELS[slot] || slot} className="w-full aspect-[2/3] object-cover" />
                  <div className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                    <ZoomIn className="w-3 h-3" />
                  </div>
                </button>
              ) : (
                <div className="w-full aspect-[2/3] bg-gray-800 flex items-center justify-center">
                  <span className="text-[10px] text-gray-600">—</span>
                </div>
              )}
              <div className="px-1.5 py-1 text-center bg-gray-900">
                <span className="text-[11px] text-gray-400">{V2_SLOT_LABELS[slot] || slot}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-emerald-600/20 flex items-center justify-center">
          <ImageIcon className="w-6 h-6 text-emerald-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Generate Identity Pack</h2>
        <p className="text-sm text-gray-400">
          We'll create your character's full visual canon — face, body, and details.
        </p>
      </div>

      {/* Body Identity (applied to the whole pack) */}
      <div className="border border-gray-800 rounded-lg px-4 py-4 space-y-4">
        <p className="text-sm font-medium text-gray-300">Body Identity</p>
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-gray-400">Height</span>
          <div className="flex gap-2">
            {BODY_HEIGHT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => onBodyMorphologyChange({ ...bodyMorphology, height: opt.value })}
                className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                  bodyMorphology.height === opt.value
                    ? 'bg-emerald-600 border-emerald-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-gray-400">Build</span>
          <div className="flex flex-wrap gap-2">
            {BODY_BUILD_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => onBodyMorphologyChange({ ...bodyMorphology, build: opt.value })}
                className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                  bodyMorphology.build === opt.value
                    ? 'bg-emerald-600 border-emerald-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="text-center space-y-1">
        <p className="text-sm font-medium text-gray-300">
          Locking facial identity first — outfits come next.
        </p>
        <p className="text-xs text-gray-500">
          This pack creates your character's visual canon (13 reference cards).
        </p>
      </div>

      <div className="flex justify-center">
        <button className="btn btn-primary flex items-center gap-2" onClick={handleGenerate} disabled={loading}>
          {loading ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Generating your canon pack…
            </>
          ) : pack ? (
            <>
              <RefreshCw className="w-4 h-4" />
              Regenerate Pack
            </>
          ) : (
            'Generate Identity Pack'
          )}
        </button>
      </div>

      {error && (
        <div className="text-center space-y-2">
          <p className="text-sm text-gray-400 bg-gray-800/60 rounded-lg px-4 py-2">{error}</p>
          <button
            type="button"
            className="text-xs text-emerald-400 hover:text-emerald-300 transition-colors"
            onClick={handleGenerate}
            disabled={loading}
          >
            Try again
          </button>
        </div>
      )}

      {loading && (
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
          {Array.from({ length: 13 }).map((_, i) => (
            <div key={i} className="rounded-lg overflow-hidden border border-gray-800">
              <div className="w-full aspect-[2/3] bg-gray-800 animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {!loading && pack && (
        <div className="space-y-5">
          {renderSection('Face', FACE_ORDER)}
          {renderSection('Body', BODY_ORDER)}
          {pack.marks.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-gray-300">Details</h3>
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
                {pack.marks.map((m) => {
                  const url = m.detail_crop_url ? resolveImageUrl(m.detail_crop_url) : null;
                  return (
                    <div key={m.mark_id} className="rounded-lg overflow-hidden border border-gray-800">
                      {url ? (
                        <button type="button" onClick={() => setEnlarged(url)} className="block w-full">
                          <img src={url} alt={m.label} className="w-full aspect-[2/3] object-cover" />
                        </button>
                      ) : (
                        <div className="w-full aspect-[2/3] bg-gray-800" />
                      )}
                      <div className="px-1.5 py-1 text-center bg-gray-900">
                        <span className="text-[11px] text-gray-400 truncate block">{m.label}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {enlarged && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
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
        <button className="btn btn-primary" disabled={!pack || loading} onClick={onNext}>
          Next
        </button>
      </div>
    </div>
  );
}
