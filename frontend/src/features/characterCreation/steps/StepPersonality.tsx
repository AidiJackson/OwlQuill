import { Sparkles } from 'lucide-react';
import type { CreationSeeds } from '../shared/types';
import { PERSONALITY_TRAITS } from '../shared/types';

interface Props {
  data: CreationSeeds;
  onChange: (data: CreationSeeds) => void;
  onNext: () => void;
  onBack: () => void;
  saving: boolean;
}

export default function StepPersonality({ data, onChange, onNext, onBack, saving }: Props) {
  const toggleTrait = (trait: string) => {
    const next = data.traits.includes(trait)
      ? data.traits.filter((t) => t !== trait)
      : [...data.traits, trait];
    onChange({ ...data, traits: next });
  };

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-owl-600/20 flex items-center justify-center">
          <Sparkles className="w-6 h-6 text-owl-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Define Their Essence</h2>
        <p className="text-sm text-gray-400">
          Pick traits that shape how your character looks and feels. These influence visual generation.
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-2">Personality Traits</label>
        <div className="flex flex-wrap gap-2">
          {PERSONALITY_TRAITS.map((trait) => {
            const selected = data.traits.includes(trait);
            return (
              <button
                key={trait}
                type="button"
                onClick={() => toggleTrait(trait)}
                className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors border ${
                  selected
                    ? 'bg-owl-600 border-owl-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
                }`}
              >
                {trait}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-300 mb-1">
          Visual Vibe
        </label>
        <textarea
          className="textarea"
          rows={3}
          placeholder='e.g. "Weathered and battle-scarred, with a quiet intensity and silver-streaked hair."'
          value={data.vibeText}
          onChange={(e) => onChange({ ...data, vibeText: e.target.value })}
        />
        <p className="text-xs text-gray-500 mt-1">
          A short description that guides how your character is visualised.
        </p>
      </div>

      <div className="flex justify-between pt-2">
        <button className="btn btn-secondary" onClick={onBack}>
          Back
        </button>
        <button
          className="btn btn-primary"
          onClick={onNext}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Next'}
        </button>
      </div>
    </div>
  );
}
