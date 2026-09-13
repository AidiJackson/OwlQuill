// VisualFeaturePicker — one single-select Interview field as picture cards.
//
// Polish Phase 3A. A drop-in replacement for one LabeledChipRow: same
// options (from shared/types.ts, via the catalog), same value in, same value
// out — the stored option value or undefined. The pictures explain the
// words; they are never sent anywhere.
//
// Semantics. The Interview's chip rows let a creator clear a choice by
// pressing it again, and that is kept here. A WAI-ARIA radiogroup cannot
// express "unchecked by pressing the checked radio", so the cards are a
// `group` of toggle buttons with `aria-pressed` — exactly the semantics the
// existing chips already use — plus arrow-key movement between cards so the
// group reads as one control. A screen reader hears "Oval, toggle button,
// pressed". Selection is shown by border, tick badge and label weight, never
// colour alone.
//
// Missing image. Final assets arrive later at refAssetUrl's path; until then
// (and whenever a file is absent in production) the image area is a quiet
// neutral tile behind the same visible label — never a broken-image icon.
import { useEffect, useRef, useState } from 'react';
import { Check, Shapes } from 'lucide-react';
import type { ExampleSet, VisualCategory } from './refCatalog';
import { refAssetUrl } from './refAssetUrl';

interface Props<V extends string> {
  category: VisualCategory<V>;
  value: V | undefined | '';
  onChange: (next: V | undefined) => void;
  exampleSet: ExampleSet;
  ariaLabel: string;
}

function RefImage({ src, alt, aspect }: { src: string; alt: string; aspect: string }) {
  const [state, setState] = useState<'loading' | 'ok' | 'missing'>('loading');
  // A new src (example set switched) gets a fresh attempt.
  useEffect(() => setState('loading'), [src]);
  return (
    <div
      className="relative w-full overflow-hidden rounded-t-xl bg-surface-overlay"
      style={{ aspectRatio: aspect }}
    >
      {state !== 'missing' && (
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          onLoad={() => setState('ok')}
          onError={() => setState('missing')}
          className={`absolute inset-0 h-full w-full object-cover transition-opacity ${state === 'ok' ? 'opacity-100' : 'opacity-0'}`}
        />
      )}
      {state !== 'ok' && (
        <div
          className="absolute inset-0 flex items-center justify-center text-ink-3"
          data-testid="ref-placeholder"
          aria-hidden="true"
        >
          <Shapes className="w-6 h-6 opacity-40" strokeWidth={1.5} />
        </div>
      )}
    </div>
  );
}

export default function VisualFeaturePicker<V extends string>({
  category,
  value,
  onChange,
  exampleSet,
  ariaLabel,
}: Props<V>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = value || undefined;

  const move = (from: number, delta: number) => {
    const n = category.options.length;
    const to = (from + delta + n) % n;
    refs.current[to]?.focus();
  };

  return (
    // Three across at every width. The Interview column is max-w-xl minus
    // the sketch pad, so five across gave 58px cards on a laptop, and two
    // across gave three tall rows on a phone. Three keeps one question in
    // view: five cards, two rows, ~104px wide at 360px.
    <div role="group" aria-label={ariaLabel} className="grid grid-cols-3 gap-2">
      {category.options.map((opt, i) => {
        const selected = current === opt.value;
        const hint = category.hints?.[opt.value];
        return (
          <button
            key={opt.value}
            ref={(el) => { refs.current[i] = el; }}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(selected ? undefined : opt.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); move(i, 1); }
              if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); move(i, -1); }
            }}
            className={`group relative flex flex-col text-left rounded-xl border-2 bg-surface-elevated transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gem/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface ${
              selected ? 'border-gem' : 'border-edge-md hover:border-gem/40'
            }`}
          >
            <RefImage
              src={refAssetUrl(category.key, exampleSet, opt.value)}
              alt=""
              aspect={category.aspect}
            />
            {selected && (
              <span
                className="absolute top-1.5 right-1.5 flex h-5 w-5 items-center justify-center rounded-full bg-gem text-gem-ink shadow"
                aria-hidden="true"
              >
                <Check className="h-3 w-3" strokeWidth={3} />
              </span>
            )}
            <span className="px-2 py-1.5 min-w-0">
              <span className={`block text-xs ${selected ? 'font-semibold text-gem' : 'font-medium text-ink-2 group-hover:text-ink'}`}>
                {opt.label}
              </span>
              {hint && <span className="block text-[10px] leading-snug text-ink-3">{hint}</span>}
            </span>
          </button>
        );
      })}
    </div>
  );
}
