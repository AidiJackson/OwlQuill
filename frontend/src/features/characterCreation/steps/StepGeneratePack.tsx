import { useState } from 'react';
import { ImageIcon, ChevronDown, ChevronUp, RefreshCw, ZoomIn, X, Info } from 'lucide-react';
import type { IdentityPackResponse } from '../shared/types';
import { TWEAK_CATEGORIES } from '../shared/types';
import { generateIdentityPack, resolveImageUrl } from '../shared/api';

interface Props {
  characterId: number;
  vibeText: string;
  pack: IdentityPackResponse | null;
  onPackGenerated: (pack: IdentityPackResponse) => void;
  onNext: () => void;
  onBack: () => void;
}

const ROLE_LABELS: Record<string, string> = {
  anchor_front: 'Front',
  anchor_three_quarter: '¾ View',
  anchor_torso: 'Torso',
};

export default function StepGeneratePack({
  characterId,
  vibeText,
  pack,
  onPackGenerated,
  onNext,
  onBack,
}: Props) {
  const [tweaks, setTweaks] = useState<Record<string, string>>({});
  const [tweaksOpen, setTweaksOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [enlargedIndex, setEnlargedIndex] = useState<number | null>(null);

  const activeTweakCount = Object.keys(tweaks).length;

  const toggleTweak = (key: string, value: string) => {
    setTweaks((prev) => {
      const next = { ...prev };
      if (next[key] === value) {
        delete next[key];
        return next;
      }
      if (!(key in next) && activeTweakCount >= 2) return prev;
      next[key] = value;
      return next;
    });
  };

  const handleGenerate = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await generateIdentityPack(characterId, tweaks, vibeText);
      onPackGenerated(result);
    } catch {
      setError("We couldn't generate the images right now. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // Derive helper flags from pack metadata (safe for older responses)
  const rewriteApplied = pack?.rewrite_applied === true;
  const tierUsed = pack?.tier_used;
  const blockedRoles = pack?.blocked_roles ?? [];
  const hadBlockedRoles = blockedRoles.length > 0;
  const tierEscalated = tierUsed === 'B' || tierUsed === 'C';

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-owl-600/20 flex items-center justify-center">
          <ImageIcon className="w-6 h-6 text-owl-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Generate Identity Pack</h2>
        <p className="text-sm text-gray-400">
          These are interpretations — not final. Choose the set that feels closest.
        </p>
      </div>

      {/* Tweak panel */}
      <div className="border border-gray-800 rounded-lg overflow-hidden">
        <button
          type="button"
          onClick={() => setTweaksOpen(!tweaksOpen)}
          className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-gray-300 hover:bg-gray-800/50 transition-colors"
        >
          <span>Adjust appearance {activeTweakCount > 0 && `(${activeTweakCount}/2)`}</span>
          {tweaksOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>

        {tweaksOpen && (
          <div className="px-4 pb-4 space-y-3 border-t border-gray-800 pt-3">
            <p className="text-xs text-gray-500">Select up to 2 categories to tweak per generation.</p>
            {TWEAK_CATEGORIES.map((cat) => {
              const isActive = cat.key in tweaks;
              const isDisabled = !isActive && activeTweakCount >= 2;
              return (
                <div key={cat.key} className="space-y-1.5">
                  <span className={`text-xs font-medium ${isDisabled ? 'text-gray-600' : 'text-gray-400'}`}>
                    {cat.label}
                  </span>
                  <div className="flex gap-2">
                    {cat.options.map((opt) => {
                      const selected = tweaks[cat.key] === opt.value;
                      return (
                        <button
                          key={opt.value}
                          type="button"
                          disabled={isDisabled && !selected}
                          onClick={() => toggleTweak(cat.key, opt.value)}
                          className={`px-3 py-1 rounded text-xs font-medium transition-colors border ${
                            selected
                              ? 'bg-owl-600 border-owl-500 text-white'
                              : isDisabled
                                ? 'bg-gray-900 border-gray-800 text-gray-600 cursor-not-allowed'
                                : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
                          }`}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Generate / Regenerate */}
      <div className="flex justify-center">
        <button
          className="btn btn-primary flex items-center gap-2"
          onClick={handleGenerate}
          disabled={loading}
        >
          {loading ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Generating…
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

      {/* Network / system error — friendly, no policy language */}
      {error && (
        <div className="text-center space-y-2">
          <p className="text-sm text-gray-400 bg-gray-800/60 rounded-lg px-4 py-2">
            {error}
          </p>
          <button
            type="button"
            className="text-xs text-owl-400 hover:text-owl-300 transition-colors"
            onClick={handleGenerate}
            disabled={loading}
          >
            Try again
          </button>
        </div>
      )}

      {/* Image grid */}
      {pack && (
        <div className="grid grid-cols-3 gap-3">
          {pack.images.map((img, i) => {
            const role = (img.metadata_json?.pack_role as string) || '';
            return (
              <button
                key={img.id}
                type="button"
                onClick={() => setEnlargedIndex(i)}
                className="rounded-lg overflow-hidden border border-gray-800 hover:border-gray-600 transition-all relative group cursor-pointer text-left"
              >
                <img
                  src={resolveImageUrl(img.url)}
                  alt={ROLE_LABELS[role] || 'Pack image'}
                  className="w-full aspect-[2/3] object-cover"
                />
                {/* Enlarge icon */}
                <div className="absolute top-2 right-2 p-1.5 rounded-full bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
                  <ZoomIn className="w-3.5 h-3.5" />
                </div>
                <div className="px-2 py-1.5 text-center bg-gray-900">
                  <span className="text-xs text-gray-400">{ROLE_LABELS[role] || role}</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* Subtle metadata-driven helpers — no policy language */}
      {pack && (rewriteApplied || tierEscalated || hadBlockedRoles) && (
        <div className="space-y-2">
          {/* Rewrite helper */}
          {rewriteApplied && !tierEscalated && !hadBlockedRoles && (
            <p className="text-center text-xs text-gray-500">
              We refined the visual description slightly to keep results consistent.
            </p>
          )}

          {/* Tier escalation helper (B or C used, but no individual blocked roles to call out) */}
          {tierEscalated && !hadBlockedRoles && (
            <p className="text-center text-xs text-gray-500">
              We generated a safer variant to keep your character consistent.
            </p>
          )}

          {/* Blocked roles info box */}
          {hadBlockedRoles && (
            <div className="flex items-start gap-2.5 rounded-lg border border-gray-800 bg-gray-800/40 px-4 py-3">
              <Info className="w-4 h-4 text-gray-500 mt-0.5 shrink-0" />
              <div className="space-y-1.5">
                <p className="text-xs font-medium text-gray-300">One angle didn't land</p>
                <p className="text-xs text-gray-500">
                  We kept your character consistent and filled the missing angle safely.
                  You can try again for a different take.
                </p>
                <button
                  type="button"
                  className="text-xs text-owl-400 hover:text-owl-300 transition-colors flex items-center gap-1"
                  onClick={handleGenerate}
                  disabled={loading}
                >
                  <RefreshCw className="w-3 h-3" />
                  Regenerate pack
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Enlarged preview overlay */}
      {pack && enlargedIndex !== null && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
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
        <button className="btn btn-primary" disabled={!pack} onClick={onNext}>
          Next
        </button>
      </div>
    </div>
  );
}
