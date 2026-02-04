import { useState, useMemo } from 'react';
import { Sparkles } from 'lucide-react';
import type { CreationSeeds } from '../shared/types';
import { PERSONALITY_TRAITS } from '../shared/types';

const MAX_VIBE_LENGTH = 200;

const FILLER_WORDS = /\b(very|really|extremely|quite|rather|somewhat|pretty|fairly|incredibly|absolutely|totally|completely|literally|basically|actually|honestly|definitely|certainly|obviously|seriously|truly)\b/gi;

const CELEBRITY_MAPPINGS: Record<string, string> = {
  'taylor swift': 'elegant features, bright eyes, graceful poise',
  'brad pitt': 'strong jawline, rugged features, confident demeanor',
  'beyonce': 'radiant skin, striking eyes, commanding presence',
  'johnny depp': 'sharp cheekbones, expressive eyes, bohemian style',
  'zendaya': 'refined features, warm complexion, elegant stature',
  'timothee chalamet': 'angular features, tousled hair, youthful intensity',
  'chris hemsworth': 'broad build, chiseled features, heroic presence',
  'rihanna': 'bold features, striking gaze, confident aura',
};

function refinePrompt(input: string): string {
  let result = input.trim();
  result = result.replace(FILLER_WORDS, '').replace(/\s+/g, ' ').trim();
  for (const [celebrity, traits] of Object.entries(CELEBRITY_MAPPINGS)) {
    result = result.replace(new RegExp(celebrity, 'gi'), traits);
  }
  result = result.replace(/\s+/g, ' ').trim();
  if (result.length > MAX_VIBE_LENGTH) {
    result = result.substring(0, MAX_VIBE_LENGTH - 3).trim() + '...';
  }
  return result;
}

interface Props {
  data: CreationSeeds;
  onChange: (data: CreationSeeds) => void;
  onNext: () => void;
  onBack: () => void;
  saving: boolean;
}

export default function StepPersonality({ data, onChange, onNext, onBack, saving }: Props) {
  const [rawVibeText, setRawVibeText] = useState(data.vibeText);

  const refinedVibe = useMemo(() => refinePrompt(rawVibeText), [rawVibeText]);

  const handleVibeChange = (value: string) => {
    if (value.length <= MAX_VIBE_LENGTH) {
      setRawVibeText(value);
      onChange({ ...data, vibeText: refinePrompt(value) });
    }
  };

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
          maxLength={MAX_VIBE_LENGTH}
          placeholder='e.g. "Weathered and battle-scarred, with a quiet intensity and silver-streaked hair."'
          value={rawVibeText}
          onChange={(e) => handleVibeChange(e.target.value)}
        />
        <div className="flex justify-between items-center mt-1">
          <p className="text-xs text-gray-500">
            A short description that guides how your character is visualised.
          </p>
          <span className={`text-xs ${rawVibeText.length >= MAX_VIBE_LENGTH ? 'text-red-400' : 'text-gray-500'}`}>
            {rawVibeText.length} / {MAX_VIBE_LENGTH}
          </span>
        </div>
      </div>

      {refinedVibe && refinedVibe !== rawVibeText && (
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            Refined Visual Description
          </label>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 text-sm text-gray-300">
            {refinedVibe}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            This refined version will be used for generation.
          </p>
        </div>
      )}

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
