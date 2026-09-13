// "Show examples as: Feminine | Masculine" — the explanatory-set switch.
//
// A true single choice with no "none", so it is a real radiogroup. Changing
// it changes which example images are shown and nothing else: it never
// calls an anatomical onChange, and the picker's emitted value is untouched.
import { EXAMPLE_SETS, type ExampleSet } from './refCatalog';

interface Props {
  value: ExampleSet;
  onChange: (set: ExampleSet) => void;
}

export default function ExampleSetToggle({ value, onChange }: Props) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span className="text-[11px] text-ink-3" id="example-set-label">
        Show examples as:
      </span>
      <div
        role="radiogroup"
        aria-labelledby="example-set-label"
        className="inline-flex rounded-lg border border-edge-md overflow-hidden"
      >
        {EXAMPLE_SETS.map((s) => {
          const on = s.value === value;
          return (
            <button
              key={s.value}
              type="button"
              role="radio"
              aria-checked={on}
              tabIndex={on ? 0 : -1}
              onClick={() => onChange(s.value)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                  e.preventDefault();
                  onChange(s.value === 'feminine' ? 'masculine' : 'feminine');
                }
              }}
              className={`px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gem/50 ${
                on ? 'bg-gem-soft text-gem' : 'bg-surface-elevated text-ink-2 hover:text-ink'
              }`}
            >
              {s.label}
            </button>
          );
        })}
      </div>
      <span className="text-[11px] text-ink-3 basis-full sm:basis-auto">
        For illustration only — this doesn&apos;t change your character.
      </span>
    </div>
  );
}
