import { useState } from 'react';
import { PenLine, RefreshCw, CheckCircle } from 'lucide-react';
import type { SketchResponse, SketchStyle } from '../shared/types';
import { SKETCH_STYLES } from '../shared/types';
import { generateIdentitySketch, resolveImageUrl } from '../shared/api';

interface Props {
  characterId: number;
  onConfirmed: (sketchImageId: number) => void;
  onBack: () => void;
}

export default function StepSketch({ characterId, onConfirmed, onBack }: Props) {
  const [selectedStyle, setSelectedStyle] = useState<SketchStyle>('pencil');
  const [sketch, setSketch] = useState<SketchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    setLoading(true);
    setError('');
    try {
      const result = await generateIdentitySketch(characterId, selectedStyle);
      setSketch(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate sketch.');
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = () => {
    if (sketch) {
      onConfirmed(sketch.image_id);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="text-center">
        <div className="flex items-center justify-center gap-2 mb-1">
          <PenLine className="w-5 h-5 text-emerald-400" />
          <h2 className="text-lg font-semibold text-gray-100">Identity Sketch</h2>
        </div>
        <p className="text-sm text-gray-400">
          Generate a quick sketch to anchor your character's face before the full identity pack.
          Regenerate as many times as you like.
        </p>
      </div>

      {/* Style selector */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Sketch Style</p>
        <div className="grid grid-cols-3 gap-2">
          {SKETCH_STYLES.map((s) => (
            <button
              key={s.value}
              onClick={() => setSelectedStyle(s.value as SketchStyle)}
              className={`p-3 rounded-lg border text-left transition-colors ${
                selectedStyle === s.value
                  ? 'border-emerald-500 bg-emerald-900/30 text-emerald-300'
                  : 'border-gray-700 bg-gray-800/50 text-gray-400 hover:border-gray-600'
              }`}
            >
              <p className="text-sm font-medium">{s.label}</p>
              <p className="text-xs mt-0.5 opacity-70">{s.description}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        disabled={loading}
        className="flex items-center justify-center gap-2 w-full py-3 rounded-lg bg-emerald-700 hover:bg-emerald-600 text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Generating…
          </>
        ) : (
          <>
            <PenLine className="w-4 h-4" />
            {sketch ? 'Regenerate Sketch' : 'Generate Sketch'}
          </>
        )}
      </button>

      {/* Error */}
      {error && (
        <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 text-center">
          {error}
        </p>
      )}

      {/* Sketch result */}
      {sketch && (
        <div className="flex flex-col items-center gap-4">
          <div className="w-full max-w-xs rounded-xl overflow-hidden border border-gray-700 shadow-lg">
            <img
              src={resolveImageUrl(sketch.image_url)}
              alt={`${sketch.style} character sketch`}
              className="w-full object-cover"
            />
          </div>
          <p className="text-xs text-gray-500 text-center italic max-w-xs">
            {sketch.style.charAt(0).toUpperCase() + sketch.style.slice(1)} sketch
          </p>

          {/* Confirm button */}
          <button
            onClick={handleConfirm}
            className="flex items-center justify-center gap-2 w-full max-w-xs py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-colors"
          >
            <CheckCircle className="w-4 h-4" />
            Yes, I recognise them — continue
          </button>
        </div>
      )}

      {/* Skip / Back */}
      <div className="flex gap-3">
        <button
          onClick={onBack}
          className="flex-1 py-2 rounded-lg border border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-600 text-sm transition-colors"
        >
          Back
        </button>
        <button
          onClick={() => onConfirmed(sketch?.image_id ?? 0)}
          className="flex-1 py-2 rounded-lg border border-gray-700 text-gray-500 hover:text-gray-300 hover:border-gray-600 text-sm transition-colors"
        >
          Skip sketch
        </button>
      </div>
    </div>
  );
}
