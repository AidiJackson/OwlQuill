import { useState, useCallback } from 'react';
import { Sparkles } from 'lucide-react';
import type { CreationSeeds, IdentitySpec } from '../shared/types';
import {
  PERSONALITY_TRAITS,
  HAIR_COLORS,
  HAIR_LENGTHS,
  EYE_COLORS,
  SKIN_TONES,
  FACE_FEATURES,
  BODY_TYPES,
  HEIGHT_BANDS,
  OUTFIT_TYPES,
  PRIMARY_COLORS,
  FOOTWEAR_OPTIONS,
  ACCESSORY_OPTIONS,
  MARKS_ACCESSORIES,
} from '../shared/types';

/* ── Constants ─────────────────────────────────────────────────────── */

const MAX_FACE_FEATURES = 2;
const MAX_EXTRA_NOTES = 120;
const MAX_OUTFIT_NOTES = 80;

const EMPTY_SPEC: IdentitySpec = {
  style: '',
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

/** Section wrapper with a label and optional helper text. */
function SectionGroup({
  label,
  helper,
  children,
  className = '',
}: {
  label: string;
  helper?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label className="block text-sm font-medium text-gray-300 mb-2">{label}</label>
      {children}
      {helper && <p className="text-xs text-gray-500 mt-1.5">{helper}</p>}
    </div>
  );
}

/** A row of small chip buttons. Single-select toggles the value; multi-select toggles membership in an array. */
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
      // Single select: toggle off if already selected
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
                ? 'bg-owl-600 border-owl-500 text-white'
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

/** Styled select dropdown matching the dark theme. */
function SelectField({
  options,
  value,
  onChange,
  placeholder,
}: {
  options: readonly string[];
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm
                 px-3 py-2 appearance-none focus:outline-none focus:ring-2 focus:ring-owl-600/40
                 focus:border-owl-500 transition-colors"
    >
      <option value="">{placeholder}</option>
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
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
  // Local spec state, initialized from data or empty
  const [spec, setSpec] = useState<IdentitySpec>(data.identitySpec ?? EMPTY_SPEC);
  const [extraNotes, setExtraNotes] = useState(spec.extra_notes);
  const [outfitNotes, setOutfitNotes] = useState(spec.wardrobe.notes);

  /** Propagate spec changes upward into CreationSeeds. */
  const propagate = useCallback(
    (next: IdentitySpec) => {
      setSpec(next);
      onChange({ ...data, identitySpec: next });
    },
    [data, onChange],
  );

  /* ── Identity field updaters ─────────────────────────────────────── */

  const updateIdentity = (field: string, value: string | string[]) => {
    const next = {
      ...spec,
      identity: { ...spec.identity, [field]: value },
    };
    propagate(next);
  };

  const updateBuild = (field: string, value: string) => {
    const next = {
      ...spec,
      build: { ...spec.build, [field]: value },
    };
    propagate(next);
  };

  const updateMarks = (items: string[]) => {
    propagate({ ...spec, marks_accessories: { items } });
  };

  const updateWardrobe = (field: string, value: string) => {
    const next = {
      ...spec,
      wardrobe: { ...spec.wardrobe, [field]: value },
    };
    propagate(next);
  };

  const handleOutfitNotes = (value: string) => {
    if (value.length <= MAX_OUTFIT_NOTES) {
      setOutfitNotes(value);
      updateWardrobe('notes', value);
    }
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

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="text-center space-y-2">
        <div className="mx-auto w-12 h-12 rounded-full bg-owl-600/20 flex items-center justify-center">
          <Sparkles className="w-6 h-6 text-owl-400" />
        </div>
        <h2 className="text-xl font-semibold text-gray-100">Define Their Essence</h2>
        <p className="text-sm text-gray-400">
          Pick traits and describe how your character looks. These shape visual generation.
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
                    ? 'bg-owl-600 border-owl-500 text-white'
                    : 'bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-600'
                }`}
              >
                {trait}
              </button>
            );
          })}
        </div>
      </SectionGroup>

      {/* ── Divider ────────────────────────────────────────────────── */}
      <div className="border-t border-gray-800" />

      {/* ── Identity ───────────────────────────────────────────────── */}
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">
          Appearance
        </h3>

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

        <SectionGroup
          label="Face Features"
          helper={`Select up to ${MAX_FACE_FEATURES}`}
        >
          <ChipRow
            options={FACE_FEATURES}
            value={spec.identity.face_features}
            onChange={(v) => updateIdentity('face_features', v)}
            multi
            maxMulti={MAX_FACE_FEATURES}
          />
        </SectionGroup>
      </div>

      {/* ── Build ──────────────────────────────────────────────────── */}
      <div className="space-y-4">
        <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">
          Build
        </h3>

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

      {/* ── Marks & Accessories ────────────────────────────────────── */}
      <SectionGroup label="Marks and Accessories" helper="Select any that apply">
        <ChipRow
          options={MARKS_ACCESSORIES}
          value={spec.marks_accessories.items}
          onChange={(v) => updateMarks(v as string[])}
          multi
        />
      </SectionGroup>

      {/* ── Wardrobe ───────────────────────────────────────────────── */}
      <div className="rounded-xl bg-gray-850 border border-gray-700/50 p-4 space-y-4"
           style={{ backgroundColor: 'rgba(31, 31, 40, 0.6)' }}>
        <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">
          Wardrobe
        </h3>

        <div className="grid grid-cols-2 gap-3">
          <SectionGroup label="Outfit Type">
            <SelectField
              options={OUTFIT_TYPES}
              value={spec.wardrobe.outfit_type}
              onChange={(v) => updateWardrobe('outfit_type', v)}
              placeholder="Select outfit"
            />
          </SectionGroup>

          <SectionGroup label="Primary Color">
            <SelectField
              options={PRIMARY_COLORS}
              value={spec.wardrobe.primary_color}
              onChange={(v) => updateWardrobe('primary_color', v)}
              placeholder="Select color"
            />
          </SectionGroup>

          <SectionGroup label="Secondary Color" helper="Optional">
            <SelectField
              options={PRIMARY_COLORS}
              value={spec.wardrobe.secondary_color}
              onChange={(v) => updateWardrobe('secondary_color', v)}
              placeholder="None"
            />
          </SectionGroup>

          <SectionGroup label="Footwear">
            <SelectField
              options={FOOTWEAR_OPTIONS}
              value={spec.wardrobe.footwear}
              onChange={(v) => updateWardrobe('footwear', v)}
              placeholder="Select footwear"
            />
          </SectionGroup>

          <SectionGroup label="Accessory">
            <SelectField
              options={ACCESSORY_OPTIONS}
              value={spec.wardrobe.accessory}
              onChange={(v) => updateWardrobe('accessory', v)}
              placeholder="None"
            />
          </SectionGroup>
        </div>

        <SectionGroup label="Outfit Details">
          <input
            type="text"
            maxLength={MAX_OUTFIT_NOTES}
            value={outfitNotes}
            onChange={(e) => handleOutfitNotes(e.target.value)}
            placeholder="e.g. torn sleeves, leather belt, gold trim"
            className="w-full rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm
                       px-3 py-2 placeholder:text-gray-600 focus:outline-none focus:ring-2
                       focus:ring-owl-600/40 focus:border-owl-500 transition-colors"
          />
          <div className="flex justify-end mt-1">
            <span className={`text-xs ${outfitNotes.length >= MAX_OUTFIT_NOTES ? 'text-red-400' : 'text-gray-500'}`}>
              {outfitNotes.length} / {MAX_OUTFIT_NOTES}
            </span>
          </div>
        </SectionGroup>
      </div>

      {/* ── Optional Details (replaces old vibe textarea) ──────────── */}
      <SectionGroup label="Optional Details" helper="Anything else that defines their look.">
        <textarea
          className="w-full rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm
                     px-3 py-2 placeholder:text-gray-600 focus:outline-none focus:ring-2
                     focus:ring-owl-600/40 focus:border-owl-500 transition-colors resize-none"
          rows={2}
          maxLength={MAX_EXTRA_NOTES}
          placeholder="e.g. battle-worn look, silver-streaked hair, quiet intensity"
          value={extraNotes}
          onChange={(e) => handleExtraNotes(e.target.value)}
        />
        <div className="flex justify-end mt-1">
          <span className={`text-xs ${extraNotes.length >= MAX_EXTRA_NOTES ? 'text-red-400' : 'text-gray-500'}`}>
            {extraNotes.length} / {MAX_EXTRA_NOTES}
          </span>
        </div>
      </SectionGroup>

      {/* ── Navigation ─────────────────────────────────────────────── */}
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
