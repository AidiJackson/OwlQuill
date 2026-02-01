import { User } from 'lucide-react';
import type { CreationBasics } from '../shared/types';

interface Props {
  data: CreationBasics;
  onChange: (data: CreationBasics) => void;
  onNext: () => void;
}

export default function StepBasics({ data, onChange, onNext }: Props) {
  const set = (field: keyof CreationBasics, value: string) =>
    onChange({ ...data, [field]: value });

  const canProceed = data.name.trim().length > 0;

  return (
    <div className="space-y-6">
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-owl-600/20 flex items-center justify-center">
          <User className="w-6 h-6 text-owl-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Create Your Character</h2>
        <p className="text-sm text-gray-400">Start with the basics — you can always refine later.</p>
      </div>

      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            Name <span className="text-owl-400">*</span>
          </label>
          <input
            className="input"
            placeholder="e.g. Kael Ashborne"
            value={data.name}
            onChange={(e) => set('name', e.target.value)}
            autoFocus
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Species</label>
            <input
              className="input"
              placeholder="e.g. Human, Elf"
              value={data.species}
              onChange={(e) => set('species', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1">Age</label>
            <input
              className="input"
              placeholder="e.g. 26, Young Adult"
              value={data.age}
              onChange={(e) => set('age', e.target.value)}
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            Gender Presentation
          </label>
          <input
            className="input"
            placeholder="e.g. Feminine, Masculine, Androgynous"
            value={data.gender_presentation}
            onChange={(e) => set('gender_presentation', e.target.value)}
          />
        </div>
      </div>

      <div className="flex justify-end pt-2">
        <button
          className="btn btn-primary"
          disabled={!canProceed}
          onClick={onNext}
        >
          Next
        </button>
      </div>
    </div>
  );
}
