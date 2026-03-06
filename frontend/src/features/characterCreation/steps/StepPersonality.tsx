import { useState, useCallback } from 'react';
import { Check, ChevronRight, Edit2 } from 'lucide-react';
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
  MARKS_ACCESSORIES,
  SPECIES_OPTIONS,
  SPECIES_TELLS_MAP,
  FACE_SHAPES,
  JAW_TYPES,
  CHEEKBONE_TYPES,
  EYE_SHAPES,
  EYE_SPACINGS,
  BROW_TYPES,
  NOSE_TYPES,
  LIP_TYPES,
  HAIRLINE_TYPES,
  FACIAL_HAIR_TYPES,
} from '../shared/types';
import SketchFacePreview from '../components/SketchFacePreview';

/* ── Constants ─────────────────────────────────────────────────────── */

const MAX_EXTRA_NOTES = 120;

const EMPTY_SPEC: IdentitySpec = {
  style: '',
  gender: '',
  age_band: '',
  species: 'human',
  species_tells: [],
  identity: { hair_color: '', hair_length: '', eye_color: '', skin_tone: '', face_features: [] },
  build: { body_type: '', height_band: '' },
  marks_accessories: { items: [] },
  wardrobe: { outfit_type: '', primary_color: '', secondary_color: '', footwear: '', accessory: '', notes: '' },
  extra_notes: '',
};

// ── Question groups ──────────────────────────────────────────────────

type GroupId = 0 | 1 | 2 | 3 | 4 | 5;

const GROUP_COPY: Record<GroupId, { heading: string; sub: string }> = {
  0: { heading: "Let's start with the basics.", sub: "Style, gender, age, species." },
  1: { heading: "Now, the shape of the face.", sub: "How does the structure read?" },
  2: { heading: "And the eyes?", sub: "The eyes give everything away." },
  3: { heading: "What about the nose and mouth?", sub: "The defining middle third." },
  4: { heading: "Hair and complexion.", sub: "Last of the solid details." },
  5: { heading: "Anything distinctive I should capture?", sub: "Marks, species tells, final notes." },
};

/* ── Reusable sub-components ───────────────────────────────────────── */

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

function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-gray-400">{label}</label>
      {children}
    </div>
  );
}

/* ── Group summary row (collapsed state) ───────────────────────────── */

function GroupSummary({
  groupId,
  spec,
  traits,
  onEdit,
}: {
  groupId: GroupId;
  spec: IdentitySpec;
  traits: string[];
  onEdit: () => void;
}) {
  const copy = GROUP_COPY[groupId];
  const summary = buildGroupSummary(groupId, spec, traits);

  return (
    <button
      type="button"
      onClick={onEdit}
      className="w-full flex items-center justify-between gap-3 px-3 py-2.5
                 rounded-lg bg-gray-900/60 border border-gray-800 text-left
                 hover:border-gray-700 transition-colors group"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Check className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
        <span className="text-xs font-medium text-gray-400 shrink-0">{copy.heading.replace('.', '')}</span>
        {summary && (
          <span className="text-xs text-gray-500 truncate">&mdash; {summary}</span>
        )}
      </div>
      <Edit2 className="w-3 h-3 text-gray-600 group-hover:text-gray-400 shrink-0 transition-colors" />
    </button>
  );
}

function buildGroupSummary(groupId: GroupId, spec: IdentitySpec, _traits: string[]): string {
  switch (groupId) {
    case 0: {
      const parts: string[] = [];
      if (spec.gender) parts.push(GENDER_OPTIONS.find((g) => g.value === spec.gender)?.label ?? spec.gender);
      if (spec.age_band) parts.push(spec.age_band);
      if (spec.species && spec.species !== 'human') parts.push(spec.species);
      if (spec.style) parts.push(spec.style);
      return parts.join(', ');
    }
    case 1: {
      const parts: string[] = [];
      if (spec.face_shape) parts.push(spec.face_shape + ' face');
      if (spec.jaw_type) parts.push(spec.jaw_type + ' jaw');
      if (spec.cheekbone_type) parts.push(spec.cheekbone_type + ' cheekbones');
      return parts.join(', ');
    }
    case 2: {
      const parts: string[] = [];
      if (spec.eye_shape) parts.push(spec.eye_shape + ' eyes');
      if (spec.identity.eye_color) parts.push(spec.identity.eye_color);
      if (spec.brow_type) parts.push(spec.brow_type + ' brows');
      return parts.join(', ');
    }
    case 3: {
      const parts: string[] = [];
      if (spec.nose_type) parts.push(spec.nose_type + ' nose');
      if (spec.lip_type) parts.push(spec.lip_type + ' lips');
      return parts.join(', ');
    }
    case 4: {
      const parts: string[] = [];
      if (spec.identity.hair_color) parts.push(spec.identity.hair_color);
      if (spec.identity.hair_length) parts.push(spec.identity.hair_length);
      if (spec.identity.skin_tone) parts.push(spec.identity.skin_tone + ' skin');
      return parts.join(', ');
    }
    case 5: {
      const parts: string[] = [];
      if (spec.marks_accessories.items.length) parts.push(spec.marks_accessories.items.join(', '));
      if (spec.extra_notes) parts.push('"' + spec.extra_notes.slice(0, 32) + (spec.extra_notes.length > 32 ? '…' : '') + '"');
      return parts.join(' · ');
    }
  }
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
  const [activeGroup, setActiveGroup] = useState<GroupId>(0);
  const [farthestGroup, setFarthestGroup] = useState<GroupId>(0);
  const [triedSubmit, setTriedSubmit] = useState(false);

  const propagate = useCallback(
    (next: IdentitySpec) => {
      setSpec(next);
      onChange({ ...data, identitySpec: next });
    },
    [data, onChange],
  );

  /* ── Field updaters ──────────────────────────────────────────────── */

  const set = (field: keyof IdentitySpec, value: unknown) =>
    propagate({ ...spec, [field]: value });

  const setIdentity = (field: string, value: string | string[]) =>
    propagate({ ...spec, identity: { ...spec.identity, [field]: value } });

  const advanceGroup = () => {
    const next = Math.min(activeGroup + 1, 5) as GroupId;
    setActiveGroup(next);
    if (next > farthestGroup) setFarthestGroup(next);
  };

  const canProceed = !saving && !!spec.style && !!spec.gender && !!spec.age_band;

  const handleNext = () => {
    if (!canProceed) {
      setTriedSubmit(true);
      setActiveGroup(0);
      return;
    }
    onNext();
  };

  const toggleTrait = (trait: string) => {
    const next = data.traits.includes(trait)
      ? data.traits.filter((t) => t !== trait)
      : [...data.traits, trait];
    onChange({ ...data, traits: next });
  };

  /* ── Render group content ────────────────────────────────────────── */

  function renderGroup(g: GroupId) {
    switch (g) {
      case 0:
        return (
          <div className="space-y-4">
            <FieldRow label="Style">
              <SelectField
                options={[...STYLE_OPTIONS]}
                value={spec.style}
                onChange={(v) => set('style', v)}
                placeholder="Select a visual style"
              />
            </FieldRow>
            <FieldRow label="Gender">
              <LabeledChipRow
                options={GENDER_OPTIONS}
                value={spec.gender}
                onChange={(v) => set('gender', v)}
              />
            </FieldRow>
            <FieldRow label="Age range">
              <ChipRow
                options={AGE_BAND_OPTIONS}
                value={spec.age_band}
                onChange={(v) => set('age_band', v as string)}
              />
            </FieldRow>
            <FieldRow label="Species">
              <LabeledChipRow
                options={SPECIES_OPTIONS}
                value={spec.species}
                onChange={(v) =>
                  propagate({ ...spec, species: (v || 'human') as Species, species_tells: [] })
                }
              />
            </FieldRow>
          </div>
        );

      case 1:
        return (
          <div className="space-y-4">
            <FieldRow label="Face shape">
              <LabeledChipRow
                options={FACE_SHAPES}
                value={spec.face_shape ?? ''}
                onChange={(v) => set('face_shape', v || undefined)}
              />
            </FieldRow>
            <FieldRow label="Jaw">
              <LabeledChipRow
                options={JAW_TYPES}
                value={spec.jaw_type ?? ''}
                onChange={(v) => set('jaw_type', v || undefined)}
              />
            </FieldRow>
            <FieldRow label="Cheekbones">
              <LabeledChipRow
                options={CHEEKBONE_TYPES}
                value={spec.cheekbone_type ?? ''}
                onChange={(v) => set('cheekbone_type', v || undefined)}
              />
            </FieldRow>
          </div>
        );

      case 2:
        return (
          <div className="space-y-4">
            <FieldRow label="Eye shape">
              <LabeledChipRow
                options={EYE_SHAPES}
                value={spec.eye_shape ?? ''}
                onChange={(v) => set('eye_shape', v || undefined)}
              />
            </FieldRow>
            <FieldRow label="Eye spacing">
              <LabeledChipRow
                options={EYE_SPACINGS}
                value={spec.eye_spacing ?? ''}
                onChange={(v) => set('eye_spacing', v || undefined)}
              />
            </FieldRow>
            <FieldRow label="Eye colour">
              <ChipRow
                options={EYE_COLORS}
                value={spec.identity.eye_color}
                onChange={(v) => setIdentity('eye_color', v as string)}
              />
            </FieldRow>
            <FieldRow label="Brows">
              <LabeledChipRow
                options={BROW_TYPES}
                value={spec.brow_type ?? ''}
                onChange={(v) => set('brow_type', v || undefined)}
              />
            </FieldRow>
          </div>
        );

      case 3:
        return (
          <div className="space-y-4">
            <FieldRow label="Nose">
              <LabeledChipRow
                options={NOSE_TYPES}
                value={spec.nose_type ?? ''}
                onChange={(v) => set('nose_type', v || undefined)}
              />
            </FieldRow>
            <FieldRow label="Lips">
              <LabeledChipRow
                options={LIP_TYPES}
                value={spec.lip_type ?? ''}
                onChange={(v) => set('lip_type', v || undefined)}
              />
            </FieldRow>
          </div>
        );

      case 4:
        return (
          <div className="space-y-4">
            <FieldRow label="Hair colour">
              <ChipRow
                options={HAIR_COLORS}
                value={spec.identity.hair_color}
                onChange={(v) => setIdentity('hair_color', v as string)}
              />
            </FieldRow>
            <FieldRow label="Hair length">
              <ChipRow
                options={HAIR_LENGTHS}
                value={spec.identity.hair_length}
                onChange={(v) => setIdentity('hair_length', v as string)}
              />
            </FieldRow>
            <FieldRow label="Hairline">
              <LabeledChipRow
                options={HAIRLINE_TYPES}
                value={spec.hairline_type ?? ''}
                onChange={(v) => set('hairline_type', v || undefined)}
              />
            </FieldRow>
            <FieldRow label="Skin tone">
              <ChipRow
                options={SKIN_TONES}
                value={spec.identity.skin_tone}
                onChange={(v) => setIdentity('skin_tone', v as string)}
              />
            </FieldRow>
            <FieldRow label="Facial hair">
              <LabeledChipRow
                options={FACIAL_HAIR_TYPES}
                value={spec.facial_hair_type ?? ''}
                onChange={(v) => set('facial_hair_type', v || undefined)}
              />
            </FieldRow>
          </div>
        );

      case 5:
        return (
          <div className="space-y-4">
            <FieldRow label="Marks and accessories">
              <ChipRow
                options={MARKS_ACCESSORIES}
                value={spec.marks_accessories.items}
                onChange={(v) =>
                  propagate({ ...spec, marks_accessories: { items: v as string[] } })
                }
                multi
              />
            </FieldRow>

            {spec.species && spec.species !== 'human' && (
              <FieldRow label={`${spec.species.charAt(0).toUpperCase() + spec.species.slice(1)} tells (max 3)`}>
                <ChipRow
                  options={SPECIES_TELLS_MAP[spec.species as Species] ?? []}
                  value={spec.species_tells}
                  onChange={(v) => set('species_tells', v as string[])}
                  multi
                  maxMulti={3}
                />
              </FieldRow>
            )}

            <FieldRow label="Artist notes">
              <textarea
                className="w-full rounded-lg bg-gray-800 border border-gray-700 text-gray-300 text-sm
                           px-3 py-2 placeholder:text-gray-600 focus:outline-none focus:ring-2
                           focus:ring-emerald-600/40 focus:border-emerald-500 transition-colors resize-none"
                rows={2}
                maxLength={MAX_EXTRA_NOTES}
                placeholder="e.g. intense gaze, quiet dignity, faint scar above left brow"
                value={spec.extra_notes}
                onChange={(e) => {
                  if (e.target.value.length <= MAX_EXTRA_NOTES) {
                    set('extra_notes', e.target.value);
                  }
                }}
              />
              <div className="flex justify-end mt-0.5">
                <span
                  className={`text-xs ${
                    (spec.extra_notes?.length ?? 0) >= MAX_EXTRA_NOTES
                      ? 'text-red-400'
                      : 'text-gray-600'
                  }`}
                >
                  {spec.extra_notes?.length ?? 0} / {MAX_EXTRA_NOTES}
                </span>
              </div>
            </FieldRow>

            {/* Personality traits — surfaced here as optional colour */}
            <FieldRow label="Personality traits (optional)">
              <div className="flex flex-wrap gap-1.5">
                {PERSONALITY_TRAITS.map((trait) => {
                  const selected = data.traits.includes(trait);
                  return (
                    <button
                      key={trait}
                      type="button"
                      onClick={() => toggleTrait(trait)}
                      className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors border ${
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
            </FieldRow>
          </div>
        );
    }
  }

  /* ── Render ──────────────────────────────────────────────────────── */

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="text-center space-y-1">
        <h2 className="text-xl font-semibold text-gray-100">Sketch Interview</h2>
        <p className="text-sm text-gray-500">
          Describe the face. The artist is listening.
        </p>
      </div>

      {/* Two-column layout: face preview (left) + interview (right) */}
      <div className="flex gap-4 items-start">
        {/* Progressive face preview */}
        <div className="shrink-0 pt-1">
          <SketchFacePreview spec={spec} />
        </div>

        {/* Interview column */}
        <div className="flex-1 min-w-0 space-y-2">
          {/* Completed groups — summary rows */}
          {([0, 1, 2, 3, 4, 5] as GroupId[])
            .filter((g) => g < activeGroup && g <= farthestGroup)
            .map((g) => (
              <GroupSummary
                key={g}
                groupId={g}
                spec={spec}
                traits={data.traits}
                onEdit={() => setActiveGroup(g)}
              />
            ))}

          {/* Active group */}
          <div className="rounded-xl border border-gray-700 bg-gray-900/40 overflow-hidden">
            {/* Group heading */}
            <div className="px-4 pt-4 pb-2">
              <p className="text-sm font-semibold text-gray-100">
                {GROUP_COPY[activeGroup].heading}
              </p>
              <p className="text-xs text-gray-500 mt-0.5">{GROUP_COPY[activeGroup].sub}</p>
            </div>

            {/* Group fields */}
            <div className="px-4 pb-4">{renderGroup(activeGroup)}</div>

            {/* Group navigation */}
            <div className="px-4 pb-4 flex justify-end">
              {activeGroup < 5 ? (
                <button
                  type="button"
                  onClick={advanceGroup}
                  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg
                             bg-gray-800 border border-gray-700 text-gray-300 text-sm
                             hover:border-gray-600 hover:text-gray-100 transition-colors"
                >
                  Next <ChevronRight className="w-3.5 h-3.5" />
                </button>
              ) : (
                /* Final group — show validation hint but no second "Next" here */
                triedSubmit && !canProceed ? (
                  <p className="text-xs text-amber-400/90 text-right">
                    Style, Gender and Age are required — check Q1.
                  </p>
                ) : null
              )}
            </div>
          </div>

          {/* Groups not yet reached — upcoming indicator */}
          {activeGroup < 5 && (
            <p className="text-xs text-gray-600 text-right">
              {5 - activeGroup} question{5 - activeGroup !== 1 ? 's' : ''} remaining
            </p>
          )}
        </div>
      </div>

      {/* Required fields reminder after submit attempt */}
      {triedSubmit && !canProceed && (
        <p className="text-xs text-amber-400/90 text-center">
          Style, Gender, and Age Range are required to continue.
        </p>
      )}

      {/* Navigation */}
      <div className="flex justify-between pt-2">
        <button className="btn btn-secondary" onClick={onBack}>
          Back
        </button>
        <button
          className="btn btn-primary"
          onClick={handleNext}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Continue to Sketch'}
        </button>
      </div>
    </div>
  );
}
