// The Interview's six question groups and the chip controls they share.
//
// Polish Phase 1. Extracted from StepPersonality so the step shell (layout,
// progress, navigation, validation) and the vocabulary (what is asked, in
// which group, with which options) can be read and changed separately. This
// file IS the visible Interview vocabulary: Phase 3's visual reference cards
// replace individual `LabeledChipRow`s here and nowhere else.
//
// Every control rendered here either changes the generated identity (the
// sketch and the V2 pack read the spec these write) or says, next to itself,
// what else it is for. Controls that did neither — Style, Marks &
// accessories, Artist notes, Brows (detailed) — were removed in Phase 1 (C4,
// C5). Their fields remain in IdentitySpec for stored characters; nothing
// here writes them.
import type { IdentitySpec, Species, CreationBasics } from '../shared/types';
import {
  AGE_BAND_OPTIONS,
  CHEEKBONE_TYPES,
  EYEBROW_SHAPE_OPTIONS,
  EYE_COLORS,
  EYE_SHAPES,
  EYE_SPACINGS,
  FACIAL_HAIR_TYPES,
  GENDER_OPTIONS,
  HAIR_COLORS,
  HAIR_LENGTHS,
  HAIR_STYLE_OPTIONS,
  HAIR_TEXTURE_OPTIONS,
  HAIRLINE_TYPES,
  JAW_TYPES,
  LIP_TYPES,
  NOSE_TYPES,
  PERSONALITY_TRAITS,
  SKIN_TONES,
  SPECIES_OPTIONS,
  SPECIES_TELLS_MAP,
} from '../shared/types';
import { hairDetailApplies, withHairLength } from '../shared/interviewRules';
import VisualFeaturePicker from '../visualRefs/VisualFeaturePicker';
import ExampleSetToggle from '../visualRefs/ExampleSetToggle';
import { FACE_SHAPE_CATEGORY, type ExampleSet } from '../visualRefs/refCatalog';
import { EYE_COLOR_SWATCHES, HAIR_COLOR_SWATCHES, SKIN_TONE_SWATCHES } from '../visualRefs/colorSwatches';

// ── Groups ────────────────────────────────────────────────────────────

export type GroupId = 0 | 1 | 2 | 3 | 4 | 5;
export const GROUP_COUNT = 6;

/** What the artist says when each group opens, and a short name for progress. */
export const GROUPS: readonly { id: GroupId; name: string; line: string }[] = [
  { id: 0, name: 'Basics',   line: "Let's start with the basics." },
  { id: 1, name: 'Face',     line: 'Now the shape of the face.' },
  { id: 2, name: 'Eyes',     line: 'And the eyes?' },
  { id: 3, name: 'Nose & mouth', line: 'What about the nose and mouth?' },
  { id: 4, name: 'Hair & skin',  line: 'Tell me about the hair.' },
  { id: 5, name: 'Character',    line: 'Anything distinctive I should capture?' },
];

// ── Shared chip controls ──────────────────────────────────────────────

const CHIP_ON = 'bg-gem border-gem/50 text-gem-ink';
const CHIP_OFF = 'bg-surface-elevated border-edge-md text-ink-2 hover:border-gem/40';

/** Single- or multi-select over plain strings (the value is the label). */
export function ChipRow({
  options,
  value,
  onChange,
  multi = false,
  maxMulti,
  ariaLabel,
  swatches,
}: {
  options: readonly string[];
  value: string | string[];
  onChange: (next: string | string[]) => void;
  multi?: boolean;
  maxMulti?: number;
  ariaLabel?: string;
  /** Explanatory colour per option (C14). The label stays; the value is untouched. */
  swatches?: Record<string, string>;
}) {
  const selectedSet = new Set(Array.isArray(value) ? value : value ? [value] : []);

  const handleClick = (option: string) => {
    if (multi) {
      const arr = Array.isArray(value) ? value : [];
      if (arr.includes(option)) {
        onChange(arr.filter((v) => v !== option));
      } else if (!maxMulti || arr.length < maxMulti) {
        onChange([...arr, option]);
      }
    } else {
      onChange(value === option ? '' : option);
    }
  };

  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={ariaLabel}>
      {options.map((option) => {
        const selected = selectedSet.has(option);
        const disabled = multi && maxMulti != null && !selected && selectedSet.size >= maxMulti;
        return (
          <button
            key={option}
            type="button"
            disabled={disabled}
            aria-pressed={selected}
            onClick={() => handleClick(option)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors border ${
              selected ? CHIP_ON : disabled ? 'bg-surface border-edge text-ink-3 cursor-not-allowed' : CHIP_OFF
            }`}
          >
            {swatches?.[option] && (
              <span
                aria-hidden="true"
                data-testid="color-swatch"
                className="inline-block h-3 w-3 rounded-full ring-1 ring-black/20 shrink-0"
                style={{ backgroundColor: swatches[option] }}
              />
            )}
            {option}
          </button>
        );
      })}
    </div>
  );
}

/** Single-select over {label, value} pairs; re-clicking clears. */
export function LabeledChipRow({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: readonly { label: string; value: string }[];
  value: string;
  onChange: (v: string) => void;
  ariaLabel?: string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label={ariaLabel}>
      {options.map((opt) => {
        const selected = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(selected ? '' : opt.value)}
            className={`px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors border ${
              selected ? CHIP_ON : CHIP_OFF
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** Field label. `required` marks the answer as needed before the Interview can finish. */
export function Note({ children, required = false }: { children: string; required?: boolean }) {
  return (
    <p className="text-[11px] text-ink-3 uppercase tracking-wider mb-1.5 flex items-center gap-1.5">
      {children}
      {required && (
        <span className="normal-case tracking-normal text-[10px] font-medium text-gem bg-gem-soft rounded px-1.5 py-px">
          Required
        </span>
      )}
    </p>
  );
}

// ── Group props ───────────────────────────────────────────────────────

export interface GroupProps {
  spec: IdentitySpec;
  propagate: (s: IdentitySpec) => void;
  set: (f: keyof IdentitySpec, v: unknown) => void;
  setIdentity: (f: string, v: string | string[]) => void;
  basics: CreationBasics;
  onBasicsChange: (b: CreationBasics) => void;
  traits: string[];
  toggleTrait: (t: string) => void;
  /** After a failed Continue: show which required answers are missing. */
  showMissing: boolean;
  /** Which explanatory example images the picture-card fields show. UI only. */
  exampleSet: ExampleSet;
  onExampleSetChange: (set: ExampleSet) => void;
}

// ── Q0 — Basics: name, alias, gender, age, species ────────────────────
//
// Polish Phase 1 (C8). Name and alias moved here from the removed Basics
// screen; gender, age range and species are asked here and ONLY here — the
// Interview is the single truth the Character row and the DNA are written
// from.

function GroupBasics({ spec, propagate, set, basics, onBasicsChange, showMissing }: GroupProps) {
  const nameMissing = showMissing && basics.name.trim() === '';
  const genderMissing = showMissing && !spec.gender;
  const ageMissing = showMissing && !spec.age_band;
  return (
    <div className="space-y-4">
      <div>
        <Note required>Name</Note>
        <input
          className="input"
          placeholder="e.g. Kael Ashborne"
          value={basics.name}
          onChange={(e) => onBasicsChange({ ...basics, name: e.target.value })}
          aria-label="Character name"
          aria-invalid={nameMissing || undefined}
          autoFocus
        />
        {nameMissing && <p className="text-xs text-amber-400/90 mt-1">A name is needed.</p>}
      </div>
      <div>
        <Note>Alias</Note>
        <input
          className="input"
          placeholder="What others call them (optional)"
          value={basics.alias}
          onChange={(e) => onBasicsChange({ ...basics, alias: e.target.value })}
          aria-label="Character alias"
        />
      </div>
      <div>
        <Note required>Gender</Note>
        <LabeledChipRow ariaLabel="Gender" options={GENDER_OPTIONS} value={spec.gender} onChange={(v) => set('gender', v)} />
        {genderMissing && <p className="text-xs text-amber-400/90 mt-1">Choose one.</p>}
      </div>
      <div>
        <Note required>Age range</Note>
        <ChipRow ariaLabel="Age range" options={AGE_BAND_OPTIONS} value={spec.age_band} onChange={(v) => set('age_band', v as string)} />
        {ageMissing && <p className="text-xs text-amber-400/90 mt-1">Choose one.</p>}
      </div>
      <div>
        <Note>Species</Note>
        <LabeledChipRow
          ariaLabel="Species"
          options={SPECIES_OPTIONS}
          value={spec.species}
          onChange={(v) => propagate({ ...spec, species: (v || 'human') as Species, species_tells: [] })}
        />
      </div>
    </div>
  );
}

// ── Q1 — Face shape ───────────────────────────────────────────────────

// Face shape is the first field shown as picture cards (Polish Phase 3A).
// Same options, same stored value; the example-set toggle only changes which
// pictures are shown and is never written anywhere.

function GroupFace({ spec, set, exampleSet, onExampleSetChange }: GroupProps) {
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Note>Face shape</Note>
        <VisualFeaturePicker
          category={FACE_SHAPE_CATEGORY}
          ariaLabel="Face shape"
          value={spec.face_shape as typeof FACE_SHAPE_CATEGORY.options[number]['value'] | undefined}
          onChange={(v) => set('face_shape', v)}
          exampleSet={exampleSet}
        />
        <ExampleSetToggle value={exampleSet} onChange={onExampleSetChange} />
      </div>
      <div>
        <Note>Jaw</Note>
        <LabeledChipRow ariaLabel="Jaw" options={JAW_TYPES} value={spec.jaw_type ?? ''} onChange={(v) => set('jaw_type', v || undefined)} />
      </div>
      <div>
        <Note>Cheekbones</Note>
        <LabeledChipRow ariaLabel="Cheekbones" options={CHEEKBONE_TYPES} value={spec.cheekbone_type ?? ''} onChange={(v) => set('cheekbone_type', v || undefined)} />
      </div>
    </div>
  );
}

// ── Q2 — Eyes ─────────────────────────────────────────────────────────
//
// One eyebrow control. "Brows (detailed)" (brow_type) asked the same anatomy
// with a subset of the same words, was ignored by the V2 pack, and was ignored
// by the sketch whenever this one was answered (C5).

function GroupEyes({ spec, set, setIdentity }: GroupProps) {
  return (
    <div className="space-y-4">
      <div>
        <Note>Eye shape</Note>
        <LabeledChipRow ariaLabel="Eye shape" options={EYE_SHAPES} value={spec.eye_shape ?? ''} onChange={(v) => set('eye_shape', v || undefined)} />
      </div>
      <div>
        <Note>Eye spacing</Note>
        <LabeledChipRow ariaLabel="Eye spacing" options={EYE_SPACINGS} value={spec.eye_spacing ?? ''} onChange={(v) => set('eye_spacing', v || undefined)} />
      </div>
      <div>
        <Note>Eye colour</Note>
        <ChipRow ariaLabel="Eye colour" options={EYE_COLORS} value={spec.identity.eye_color} onChange={(v) => setIdentity('eye_color', v as string)} swatches={EYE_COLOR_SWATCHES} />
      </div>
      <div>
        <Note>Eyebrows</Note>
        <LabeledChipRow ariaLabel="Eyebrows" options={EYEBROW_SHAPE_OPTIONS} value={spec.eyebrow_shape ?? ''} onChange={(v) => set('eyebrow_shape', v || undefined)} />
      </div>
    </div>
  );
}

// ── Q3 — Nose and mouth ───────────────────────────────────────────────

function GroupNoseMouth({ spec, set }: GroupProps) {
  return (
    <div className="space-y-4">
      <div>
        <Note>Nose</Note>
        <LabeledChipRow ariaLabel="Nose" options={NOSE_TYPES} value={spec.nose_type ?? ''} onChange={(v) => set('nose_type', v || undefined)} />
      </div>
      <div>
        <Note>Lips</Note>
        <LabeledChipRow ariaLabel="Lips" options={LIP_TYPES} value={spec.lip_type ?? ''} onChange={(v) => set('lip_type', v || undefined)} />
      </div>
    </div>
  );
}

// ── Q4 — Hair and skin ────────────────────────────────────────────────
//
// Hair length is set through withHairLength (C9): choosing Shaved clears
// style and texture and hides both controls, so a stale "slicked back wavy"
// can never ride along into a shaved head's prompt.

function GroupHair({ spec, propagate, set, setIdentity }: GroupProps) {
  const detail = hairDetailApplies(spec);
  return (
    <div className="space-y-4">
      <div>
        <Note>Hair colour</Note>
        <ChipRow ariaLabel="Hair colour" options={HAIR_COLORS} value={spec.identity.hair_color} onChange={(v) => setIdentity('hair_color', v as string)} swatches={HAIR_COLOR_SWATCHES} />
      </div>
      <div>
        <Note>Hair length</Note>
        <ChipRow
          ariaLabel="Hair length"
          options={HAIR_LENGTHS}
          value={spec.identity.hair_length}
          onChange={(v) => propagate(withHairLength(spec, v as string))}
        />
      </div>
      {detail && (
        <>
          <div>
            <Note>Hair texture</Note>
            <LabeledChipRow ariaLabel="Hair texture" options={HAIR_TEXTURE_OPTIONS} value={spec.hair_texture ?? ''} onChange={(v) => set('hair_texture', v || undefined)} />
          </div>
          <div>
            <Note>Hair style</Note>
            <LabeledChipRow ariaLabel="Hair style" options={HAIR_STYLE_OPTIONS} value={spec.hair_style ?? ''} onChange={(v) => set('hair_style', v || undefined)} />
          </div>
        </>
      )}
      <div>
        <Note>Hairline</Note>
        <LabeledChipRow ariaLabel="Hairline" options={HAIRLINE_TYPES} value={spec.hairline_type ?? ''} onChange={(v) => set('hairline_type', v || undefined)} />
      </div>
      <div>
        <Note>Skin tone</Note>
        <ChipRow ariaLabel="Skin tone" options={SKIN_TONES} value={spec.identity.skin_tone} onChange={(v) => setIdentity('skin_tone', v as string)} swatches={SKIN_TONE_SWATCHES} />
      </div>
      <div>
        <Note>Facial hair</Note>
        <LabeledChipRow ariaLabel="Facial hair" options={FACIAL_HAIR_TYPES} value={spec.facial_hair_type ?? ''} onChange={(v) => set('facial_hair_type', v || undefined)} />
      </div>
    </div>
  );
}

// ── Q5 — Character: species tells and personality ─────────────────────
//
// Personality traits are the one control here that is not anatomy. They are
// folded into every V2 card prompt as the character's overall feel (see
// canon_card_prompts.build_preamble → "overall character vibe"), which is
// worth saying, and worth not overstating (C17).

function GroupCharacter({ spec, set, traits, toggleTrait }: GroupProps) {
  const tells = SPECIES_TELLS_MAP[spec.species as Species] ?? [];
  return (
    <div className="space-y-4">
      {spec.species && spec.species !== 'human' && tells.length > 0 && (
        <div>
          <Note>{`${SPECIES_OPTIONS.find((o) => o.value === spec.species)?.label ?? spec.species} tells (up to 3)`}</Note>
          <ChipRow
            ariaLabel="Species tells"
            options={tells}
            value={spec.species_tells}
            onChange={(v) => set('species_tells', v as string[])}
            multi
            maxMulti={3}
          />
        </div>
      )}

      <div>
        <Note>Personality traits</Note>
        <p className="text-xs text-ink-3 mb-2">
          These shape the overall feel of your character&apos;s images — bearing and
          expression, not anatomy.
        </p>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Personality traits">
          {PERSONALITY_TRAITS.map((trait) => {
            const on = traits.includes(trait);
            return (
              <button
                key={trait}
                type="button"
                aria-pressed={on}
                onClick={() => toggleTrait(trait)}
                className={`px-2.5 py-1.5 rounded-full text-xs font-medium transition-colors border ${on ? CHIP_ON : CHIP_OFF}`}
              >
                {trait}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export const GROUP_COMPONENTS: Record<GroupId, (p: GroupProps) => JSX.Element> = {
  0: GroupBasics,
  1: GroupFace,
  2: GroupEyes,
  3: GroupNoseMouth,
  4: GroupHair,
  5: GroupCharacter,
};
