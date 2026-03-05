import { useState, useCallback } from 'react';
import { Check } from 'lucide-react';
import type { CreationSeeds, IdentitySpec, Species } from '../shared/types';
import {
  PERSONALITY_TRAITS,
  STYLE_OPTIONS,
  GENDER_OPTIONS,
  AGE_BAND_OPTIONS,
  HAIR_COLORS,
  HAIR_LENGTHS,
  EYE_COLORS,
  SKIN_TONES,
  FACE_FEATURES,
  BODY_TYPES,
  HEIGHT_BANDS,
  MARKS_ACCESSORIES,
  SPECIES_OPTIONS,
  SPECIES_TELLS_MAP,
} from '../shared/types';

/* ── Constants ─────────────────────────────────────────────────────── */

const MAX_FACE_FEATURES = 2;
const MAX_EXTRA_NOTES = 120;

const EMPTY_SPEC: IdentitySpec = {
  style: '',
  gender: '',
  age_band: '',
  species: 'human',
  species_tells: [],
  identity: {
    hair_color: '',
    hair_length: '',
    eye_color: '',
    skin_tone: '',
    face_features: [],
  },
  build: {
    body_type: '',
    height_band: '',
  },
  marks_accessories: { items: [] },
  wardrobe: {
    outfit_type: '',
    primary_color: '',
    secondary_color: '',
    footwear: '',
    accessory: '',
    notes: '',
  },
  extra_notes: '',
};

/* ── Reusable sub-components ───────────────────────────────────────── */

/** Section heading with optional "done" checkmark and helper text. */
function SectionGroup({
  label,
  helper,
  children,
  required,
  done,
  className = '',
}: {
  label: string;
  helper?: string;
  children: React.ReactNode;
  required?: boolean;
  done?: boolean;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="flex items-center gap-1.5 mb-2">
        <label className="block text-sm font-medium text-gray-300">
          {label}
          {required && <span className="text-emerald-400 ml-1">*</span>}
        </label>
        {done && <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />}
      </div>
      {children}
      {helper && <p className="text-xs text-gray-500 mt-1.5">{helper}</p>}
    </div>
  );
}

/** A row of small chip buttons. Single-select toggles the value; multi-select toggles membership. */
function ChipRow({
  options,
  value,
  onChange,
  multi = false,
  maxMulti,
}: {
  options: readonly string[];
  value: string | string[];
  onChange: (next: string | string[]) => void;
  multi?: boolean;
  maxMulti?: number;
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
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const selected = selectedSet.has(option);
        const disabled = multi && maxMulti != null && !selected && selectedSet.size >= maxMulti;
        return (
          <button
            key={option}
            type="button"
            disabled={disabled}
            onClick={() => handleClick(option)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors border ${
              selected
                ? 'bg-emerald-600 border-emerald-500 text-white'
                : disabled
                  ? 'bg-gray-900 border-gray-800 text-gray-600 cursor-not-allowed'
                  : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
            }`}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}

/** Chip row where display label differs from stored value. */
function LabeledChipRow({
  options,
  value,
  onChange,
}: {
  options: readonly { label: string; value: string }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => {
        const selected = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(selected ? '' : opt.value)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors border ${
              selected
                ? 'bg-emerald-600 border-emerald-500 text-white'
                : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** Styled select dropdown. */
function SelectField({
  options,
  value,
  onChange,
  placeholder,
}: {
  options: { label: string; value: string }[];
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm
                 px-3 py-2 appearance-none focus:outline-none focus:ring-2 focus:ring-emerald-600/40
                 focus:border-emerald-500 transition-colors"
    >
      <option value="">{placeholder}</option>
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>
          {opt.label}
        </option>
      ))}
    </select>
  );
}

/* ── Main component ────────────────────────────────────────────────── */

interface Props {
  data: CreationSeeds;
  onChange: (data: CreationSeeds) => void;
  onNext: () => void;
  onBack: () => void;
  saving: boolean;
}

export default function StepPersonality({ data, onChange, onNext, onBack, saving }: Props) {
  const [spec, setSpec] = useState<IdentitySpec>(data.identitySpec ?? EMPTY_SPEC);
  const [extraNotes, setExtraNotes] = useState(spec.extra_notes);
  const [triedSubmit, setTriedSubmit] = useState(false);

  const propagate = useCallback(
    (next: IdentitySpec) => {
      setSpec(next);
      onChange({ ...data, identitySpec: next });
    },
    [data, onChange],
  );

  /* ── Field updaters ──────────────────────────────────────────────── */

  const updateIdentity = (field: string, value: string | string[]) => {
    propagate({ ...spec, identity: { ...spec.identity, [field]: value } });
  };

  const updateBuild = (field: string, value: string) => {
    propagate({ ...spec, build: { ...spec.build, [field]: value } });
  };

  const updateMarks = (items: string[]) => {
    propagate({ ...spec, marks_accessories: { items } });
  };

  const handleExtraNotes = (value: string) => {
    if (value.length <= MAX_EXTRA_NOTES) {
      setExtraNotes(value);
      propagate({ ...spec, extra_notes: value });
    }
  };

  const toggleTrait = (trait: string) => {
    const next = data.traits.includes(trait)
      ? data.traits.filter((t) => t !== trait)
      : [...data.traits, trait];
    onChange({ ...data, traits: next });
  };

  const canProceed = !saving && !!spec.style && !!spec.gender && !!spec.age_band;

  const handleNext = () => {
    if (!canProceed) {
      setTriedSubmit(true);
      return;
    }
    onNext();
  };

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center space-y-2">
        <h2 className="text-xl font-semibold text-gray-100">Sketch Interview</h2>
        <p className="text-sm text-gray-400">
          Answer a few quick questions so our sketch artist can capture the face accurately.
        </p>
      </div>

      {/* ── Personality Traits ─────────────────────────────────────── */}
      <SectionGroup label="Personality Traits">
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
                    ? 'bg-emerald-600 border-emerald-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
                }`}
              >
                {trait}
              </button>
            );
          })}
        </div>
      </SectionGroup>

      <div className="border-t border-gray-800" />

      {/* ── Section A: Identity ─────────────────────────────────────── */}
      <div className="space-y-1">
        <p className="text-xs text-gray-500 uppercase tracking-wider font-medium">
          A — Identity <span className="text-gray-600 normal-case">(required)</span>
        </p>
      </div>

      <div className="space-y-4">
        <SectionGroup label="Style" required done={!!spec.style}>
          <SelectField
            options={[...STYLE_OPTIONS]}
            value={spec.style}
            onChange={(v) => propagate({ ...spec, style: v })}
            placeholder="Select a visual style"
          />
        </SectionGroup>

        <SectionGroup label="Gender" required done={!!spec.gender}>
          <LabeledChipRow
            options={GENDER_OPTIONS}
            value={spec.gender}
            onChange={(v) => propagate({ ...spec, gender: v })}
          />
        </SectionGroup>

        <SectionGroup label="Age Range" required done={!!spec.age_band}>
          <ChipRow
            options={AGE_BAND_OPTIONS}
            value={spec.age_band}
            onChange={(v) => propagate({ ...spec, age_band: v as string })}
          />
        </SectionGroup>

        <SectionGroup label="Species" done={spec.species !== 'human' || !!spec.species}>
          <LabeledChipRow
            options={SPECIES_OPTIONS}
            value={spec.species}
            onChange={(v) =>
              propagate({ ...spec, species: (v || 'human') as Species, species_tells: [] })
            }
          />
        </SectionGroup>
      </div>

      <div className="border-t border-gray-800" />

      {/* ── Section B: Facial Appearance ────────────────────────────── */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-4">
          B — Facial Appearance <span className="text-gray-600 normal-case">(optional)</span>
        </p>
        <div className="space-y-4">
          <SectionGroup label="Hair Color">
            <ChipRow
              options={HAIR_COLORS}
              value={spec.identity.hair_color}
              onChange={(v) => updateIdentity('hair_color', v as string)}
            />
          </SectionGroup>

          <SectionGroup label="Hair Length">
            <ChipRow
              options={HAIR_LENGTHS}
              value={spec.identity.hair_length}
              onChange={(v) => updateIdentity('hair_length', v as string)}
            />
          </SectionGroup>

          <SectionGroup label="Eye Color">
            <ChipRow
              options={EYE_COLORS}
              value={spec.identity.eye_color}
              onChange={(v) => updateIdentity('eye_color', v as string)}
            />
          </SectionGroup>

          <SectionGroup label="Skin Tone">
            <ChipRow
              options={SKIN_TONES}
              value={spec.identity.skin_tone}
              onChange={(v) => updateIdentity('skin_tone', v as string)}
            />
          </SectionGroup>

          <SectionGroup label="Face Features" helper={`Select up to ${MAX_FACE_FEATURES}`}>
            <ChipRow
              options={FACE_FEATURES}
              value={spec.identity.face_features}
              onChange={(v) => updateIdentity('face_features', v)}
              multi
              maxMulti={MAX_FACE_FEATURES}
            />
          </SectionGroup>

          <SectionGroup label="Marks and Accessories" helper="Select any that apply">
            <ChipRow
              options={MARKS_ACCESSORIES}
              value={spec.marks_accessories.items}
              onChange={(v) => updateMarks(v as string[])}
              multi
            />
          </SectionGroup>
        </div>
      </div>

      {/* ── Section B.2: Build ──────────────────────────────────────── */}
      <div className="space-y-4">
        <SectionGroup label="Body Type">
          <ChipRow
            options={BODY_TYPES}
            value={spec.build.body_type}
            onChange={(v) => updateBuild('body_type', v as string)}
          />
        </SectionGroup>

        <SectionGroup label="Height">
          <ChipRow
            options={HEIGHT_BANDS}
            value={spec.build.height_band}
            onChange={(v) => updateBuild('height_band', v as string)}
          />
        </SectionGroup>
      </div>

      {/* ── Section C: Supernatural Tells ───────────────────────────── */}
      {spec.species && spec.species !== 'human' && (
        <>
          <div className="border-t border-gray-800" />
          <div>
            <p className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-4">
              C — Supernatural Tells <span className="text-gray-600 normal-case">(optional, max 3)</span>
            </p>
            <SectionGroup
              label="Visual Tells"
              helper={`Subtle hints visible in the sketch (${spec.species_tells.length}/3)`}
            >
              <ChipRow
                options={SPECIES_TELLS_MAP[spec.species as Species] ?? []}
                value={spec.species_tells}
                onChange={(v) => propagate({ ...spec, species_tells: v as string[] })}
                multi
                maxMulti={3}
              />
            </SectionGroup>
          </div>
        </>
      )}

      <div className="border-t border-gray-800" />

      {/* ── Section D: Artist Notes ──────────────────────────────────── */}
      <div>
        <p className="text-xs text-gray-500 uppercase tracking-wider font-medium mb-4">
          D — Artist Notes <span className="text-gray-600 normal-case">(optional)</span>
        </p>
        <SectionGroup
          label="Anything distinctive the artist should know?"
          helper="Use this for small face or vibe details, not clothing."
        >
          <textarea
            className="w-full rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm
                       px-3 py-2 placeholder:text-gray-600 focus:outline-none focus:ring-2
                       focus:ring-emerald-600/40 focus:border-emerald-500 transition-colors resize-none"
            rows={2}
            maxLength={MAX_EXTRA_NOTES}
            placeholder="e.g. intense gaze, quiet dignity, faint scar above left brow"
            value={extraNotes}
            onChange={(e) => handleExtraNotes(e.target.value)}
          />
          <div className="flex justify-end mt-1">
            <span className={`text-xs ${extraNotes.length >= MAX_EXTRA_NOTES ? 'text-red-400' : 'text-gray-500'}`}>
              {extraNotes.length} / {MAX_EXTRA_NOTES}
            </span>
          </div>
        </SectionGroup>
      </div>

      {/* Required fields reminder — only after a submit attempt */}
      {triedSubmit && !canProceed && (
        <p className="text-xs text-amber-400/90 text-center">
          Style, Gender, and Age Range are required to continue.
        </p>
      )}

      {/* ── Navigation ─────────────────────────────────────────────── */}
      <div className="flex justify-between pt-2">
        <button className="btn btn-secondary" onClick={onBack}>
          Back
        </button>
        <button
          className="btn btn-primary"
          onClick={handleNext}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Next'}
        </button>
      </div>
    </div>
  );
}
