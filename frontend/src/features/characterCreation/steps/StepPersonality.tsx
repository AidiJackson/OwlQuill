import { useState, useCallback } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
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
  HAIR_TEXTURE_OPTIONS,
  HAIR_STYLE_OPTIONS,
  EYEBROW_SHAPE_OPTIONS,
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
  // B15
  hair_texture: undefined,
  hair_style: undefined,
  eyebrow_shape: undefined,
};

// ── Question groups ──────────────────────────────────────────────────

type GroupId = 0 | 1 | 2 | 3 | 4 | 5;

const GROUP_ARTIST_LINE: Record<GroupId, string> = {
  0: "Let's start with the basics.",
  1: "Now the shape of the face.",
  2: "And the eyes?",
  3: "What about the nose and mouth?",
  4: "Tell me about the hair.",
  5: "Anything distinctive I should capture?",
};

// ── Chip components ───────────────────────────────────────────────────

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
                ? 'bg-gem border-gem/50 text-white'
                : disabled
                ? 'bg-surface border-edge text-ink-3 cursor-not-allowed'
                : 'bg-surface-elevated border-edge-md text-ink-2 hover:border-edge-md'
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
                ? 'bg-gem border-gem/50 text-white'
                : 'bg-surface-elevated border-edge-md text-ink-2 hover:border-edge-md'
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
      className="w-full rounded-lg bg-surface-elevated border border-edge-md text-ink-2 text-sm
                 px-3 py-2 appearance-none focus:outline-none focus:ring-2 focus:ring-gem/40
                 focus:border-gem/50 transition-colors"
    >
      <option value="">{placeholder}</option>
      {options.map((opt) => (
        <option key={opt.value} value={opt.value}>{opt.label}</option>
      ))}
    </select>
  );
}

/** Annotation label above a chip row. Lowercase, very light. */
function Note({ children }: { children: string }) {
  return <p className="text-[10px] text-ink-3 uppercase tracking-wider mb-1">{children}</p>;
}

// ── Compact notes strip ───────────────────────────────────────────────

function NotesStrip({ spec }: { spec: IdentitySpec }) {
  const parts: string[] = [];
  if (spec.gender) parts.push(GENDER_OPTIONS.find((g) => g.value === spec.gender)?.label ?? spec.gender);
  if (spec.age_band) parts.push(spec.age_band);
  if (spec.species && spec.species !== 'human') parts.push(spec.species);
  if (spec.face_shape) parts.push(spec.face_shape);
  if (spec.jaw_type) parts.push(spec.jaw_type + ' jaw');
  if (spec.eye_shape) parts.push(spec.eye_shape + ' eyes');
  if (spec.identity?.eye_color) parts.push(spec.identity.eye_color);
  if (spec.nose_type) parts.push(spec.nose_type + ' nose');
  if (spec.lip_type) parts.push(spec.lip_type + ' lips');
  if (spec.identity?.hair_color) parts.push(spec.identity.hair_color);
  if (spec.identity?.hair_length) parts.push(spec.identity.hair_length + ' hair');
  if (spec.hair_texture) parts.push(spec.hair_texture);
  if (spec.hair_style) parts.push(spec.hair_style.replace(/_/g, ' '));
  if (spec.eyebrow_shape) parts.push(spec.eyebrow_shape + ' brows');
  if (spec.facial_hair_type && spec.facial_hair_type !== 'none') parts.push(spec.facial_hair_type.replace(/_/g, ' '));

  if (!parts.length) return null;

  return (
    <p className="text-[10px] text-ink-3 leading-relaxed mt-2" style={{ maxWidth: 154 }}>
      {parts.join(' · ')}
    </p>
  );
}

// ── Group field renderers ─────────────────────────────────────────────

function GroupQ0({ spec, propagate, set }: {
  spec: IdentitySpec;
  propagate: (s: IdentitySpec) => void;
  set: (f: keyof IdentitySpec, v: unknown) => void;
}) {
  return (
    <div className="space-y-3.5">
      <div>
        <Note>Style</Note>
        <SelectField
          options={[...STYLE_OPTIONS]}
          value={spec.style}
          onChange={(v) => set('style', v)}
          placeholder="Select a visual style"
        />
      </div>
      <div>
        <Note>Gender</Note>
        <LabeledChipRow options={GENDER_OPTIONS} value={spec.gender} onChange={(v) => set('gender', v)} />
      </div>
      <div>
        <Note>Age range</Note>
        <ChipRow options={AGE_BAND_OPTIONS} value={spec.age_band} onChange={(v) => set('age_band', v as string)} />
      </div>
      <div>
        <Note>Species</Note>
        <LabeledChipRow
          options={SPECIES_OPTIONS}
          value={spec.species}
          onChange={(v) => propagate({ ...spec, species: (v || 'human') as Species, species_tells: [] })}
        />
      </div>
    </div>
  );
}

function GroupQ1({ spec, set }: {
  spec: IdentitySpec;
  set: (f: keyof IdentitySpec, v: unknown) => void;
}) {
  return (
    <div className="space-y-3.5">
      <div>
        <Note>Face shape</Note>
        <LabeledChipRow options={FACE_SHAPES} value={spec.face_shape ?? ''} onChange={(v) => set('face_shape', v || undefined)} />
      </div>
      <div>
        <Note>Jaw</Note>
        <LabeledChipRow options={JAW_TYPES} value={spec.jaw_type ?? ''} onChange={(v) => set('jaw_type', v || undefined)} />
      </div>
      <div>
        <Note>Cheekbones</Note>
        <LabeledChipRow options={CHEEKBONE_TYPES} value={spec.cheekbone_type ?? ''} onChange={(v) => set('cheekbone_type', v || undefined)} />
      </div>
    </div>
  );
}

function GroupQ2({ spec, set, setIdentity }: {
  spec: IdentitySpec;
  set: (f: keyof IdentitySpec, v: unknown) => void;
  setIdentity: (f: string, v: string | string[]) => void;
}) {
  return (
    <div className="space-y-3.5">
      <div>
        <Note>Eye shape</Note>
        <LabeledChipRow options={EYE_SHAPES} value={spec.eye_shape ?? ''} onChange={(v) => set('eye_shape', v || undefined)} />
      </div>
      <div>
        <Note>Eye spacing</Note>
        <LabeledChipRow options={EYE_SPACINGS} value={spec.eye_spacing ?? ''} onChange={(v) => set('eye_spacing', v || undefined)} />
      </div>
      <div>
        <Note>Eye colour</Note>
        <ChipRow options={EYE_COLORS} value={spec.identity.eye_color} onChange={(v) => setIdentity('eye_color', v as string)} />
      </div>
      <div>
        <Note>Eyebrow shape</Note>
        <LabeledChipRow options={EYEBROW_SHAPE_OPTIONS} value={spec.eyebrow_shape ?? ''} onChange={(v) => set('eyebrow_shape', v || undefined)} />
      </div>
      <div>
        <Note>Brows (detailed)</Note>
        <LabeledChipRow options={BROW_TYPES} value={spec.brow_type ?? ''} onChange={(v) => set('brow_type', v || undefined)} />
      </div>
    </div>
  );
}

function GroupQ3({ spec, set }: {
  spec: IdentitySpec;
  set: (f: keyof IdentitySpec, v: unknown) => void;
}) {
  return (
    <div className="space-y-3.5">
      <div>
        <Note>Nose</Note>
        <LabeledChipRow options={NOSE_TYPES} value={spec.nose_type ?? ''} onChange={(v) => set('nose_type', v || undefined)} />
      </div>
      <div>
        <Note>Lips</Note>
        <LabeledChipRow options={LIP_TYPES} value={spec.lip_type ?? ''} onChange={(v) => set('lip_type', v || undefined)} />
      </div>
    </div>
  );
}

function GroupQ4({ spec, set, setIdentity }: {
  spec: IdentitySpec;
  set: (f: keyof IdentitySpec, v: unknown) => void;
  setIdentity: (f: string, v: string | string[]) => void;
}) {
  return (
    <div className="space-y-3.5">
      <div>
        <Note>Hair colour</Note>
        <ChipRow options={HAIR_COLORS} value={spec.identity.hair_color} onChange={(v) => setIdentity('hair_color', v as string)} />
      </div>
      <div>
        <Note>Hair length</Note>
        <ChipRow options={HAIR_LENGTHS} value={spec.identity.hair_length} onChange={(v) => setIdentity('hair_length', v as string)} />
      </div>
      <div>
        <Note>Hair texture</Note>
        <LabeledChipRow options={HAIR_TEXTURE_OPTIONS} value={spec.hair_texture ?? ''} onChange={(v) => set('hair_texture', v || undefined)} />
      </div>
      <div>
        <Note>Hair style</Note>
        <LabeledChipRow options={HAIR_STYLE_OPTIONS} value={spec.hair_style ?? ''} onChange={(v) => set('hair_style', v || undefined)} />
      </div>
      <div>
        <Note>Hairline</Note>
        <LabeledChipRow options={HAIRLINE_TYPES} value={spec.hairline_type ?? ''} onChange={(v) => set('hairline_type', v || undefined)} />
      </div>
      <div>
        <Note>Skin tone</Note>
        <ChipRow options={SKIN_TONES} value={spec.identity.skin_tone} onChange={(v) => setIdentity('skin_tone', v as string)} />
      </div>
      <div>
        <Note>Facial hair</Note>
        <LabeledChipRow options={FACIAL_HAIR_TYPES} value={spec.facial_hair_type ?? ''} onChange={(v) => set('facial_hair_type', v || undefined)} />
      </div>
    </div>
  );
}

function GroupQ5({ spec, propagate, set, traits, toggleTrait }: {
  spec: IdentitySpec;
  propagate: (s: IdentitySpec) => void;
  set: (f: keyof IdentitySpec, v: unknown) => void;
  traits: string[];
  toggleTrait: (t: string) => void;
}) {
  return (
    <div className="space-y-3.5">
      <div>
        <Note>Marks and accessories</Note>
        <ChipRow
          options={MARKS_ACCESSORIES}
          value={spec.marks_accessories.items}
          onChange={(v) => propagate({ ...spec, marks_accessories: { items: v as string[] } })}
          multi
        />
      </div>

      {spec.species && spec.species !== 'human' && (
        <div>
          <Note>{`${spec.species} tells (max 3)`}</Note>
          <ChipRow
            options={SPECIES_TELLS_MAP[spec.species as Species] ?? []}
            value={spec.species_tells}
            onChange={(v) => set('species_tells', v as string[])}
            multi
            maxMulti={3}
          />
        </div>
      )}

      <div>
        <Note>Artist notes</Note>
        <textarea
          className="w-full rounded-lg bg-surface-elevated border border-edge-md text-ink-2 text-xs
                     px-3 py-2 placeholder:text-ink-3 focus:outline-none focus:ring-2
                     focus:ring-gem/40 focus:border-gem/50 transition-colors resize-none"
          rows={2}
          maxLength={MAX_EXTRA_NOTES}
          placeholder="e.g. intense gaze, quiet dignity, faint scar above left brow"
          value={spec.extra_notes}
          onChange={(e) => {
            if (e.target.value.length <= MAX_EXTRA_NOTES) set('extra_notes', e.target.value);
          }}
        />
      </div>

      <div>
        <Note>Personality traits</Note>
        <div className="flex flex-wrap gap-1.5">
          {PERSONALITY_TRAITS.map((trait) => (
            <button
              key={trait}
              type="button"
              onClick={() => toggleTrait(trait)}
              className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors border ${
                traits.includes(trait)
                  ? 'bg-gem border-gem/50 text-white'
                  : 'bg-surface-elevated border-edge-md text-ink-2 hover:border-edge-md'
              }`}
            >
              {trait}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────

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
  const [triedSubmit, setTriedSubmit] = useState(false);

  const propagate = useCallback(
    (next: IdentitySpec) => {
      setSpec(next);
      onChange({ ...data, identitySpec: next });
    },
    [data, onChange],
  );

  const set = (field: keyof IdentitySpec, value: unknown) =>
    propagate({ ...spec, [field]: value });

  const setIdentity = (field: string, value: string | string[]) =>
    propagate({ ...spec, identity: { ...spec.identity, [field]: value } });

  const toggleTrait = (trait: string) => {
    const next = data.traits.includes(trait)
      ? data.traits.filter((t) => t !== trait)
      : [...data.traits, trait];
    onChange({ ...data, traits: next });
  };

  const canProceed = !saving && !!spec.style && !!spec.gender && !!spec.age_band;

  const handleContinue = () => {
    if (!canProceed) {
      setTriedSubmit(true);
      setActiveGroup(0);
      return;
    }
    onNext();
  };

  const advance = () => {
    if (activeGroup < 5) setActiveGroup((activeGroup + 1) as GroupId);
  };

  const retreat = () => {
    if (activeGroup > 0) setActiveGroup((activeGroup - 1) as GroupId);
  };

  // ── Render ────────────────────────────────────────────────────────

  function renderActiveGroup() {
    switch (activeGroup) {
      case 0: return <GroupQ0 spec={spec} propagate={propagate} set={set} />;
      case 1: return <GroupQ1 spec={spec} set={set} />;
      case 2: return <GroupQ2 spec={spec} set={set} setIdentity={setIdentity} />;
      case 3: return <GroupQ3 spec={spec} set={set} />;
      case 4: return <GroupQ4 spec={spec} set={set} setIdentity={setIdentity} />;
      case 5: return <GroupQ5 spec={spec} propagate={propagate} set={set} traits={data.traits} toggleTrait={toggleTrait} />;
    }
  }

  return (
    <div className="space-y-5">
      {/* Step header */}
      <div className="text-center space-y-0.5">
        <h2 className="text-xl font-semibold text-ink">Sketch Interview</h2>
        <p className="text-xs text-ink-3">The artist is listening.</p>
      </div>

      {/* Main two-column layout */}
      <div className="flex gap-5 items-start">

        {/* Left: sketch pad + notes strip */}
        <div className="shrink-0 flex flex-col">
          <SketchFacePreview spec={spec} />
          <NotesStrip spec={spec} />
        </div>

        {/* Right: one active question at a time */}
        <div className="flex-1 min-w-0 flex flex-col gap-3">

          {/* Previous question nav (very subtle) */}
          {activeGroup > 0 && (
            <button
              type="button"
              onClick={retreat}
              className="flex items-center gap-0.5 text-xs text-ink-3 hover:text-ink-2 transition-colors self-start"
            >
              <ChevronLeft className="w-3 h-3" />
              {(() => {
                const prev = (activeGroup - 1) as GroupId;
                return GROUP_ARTIST_LINE[prev].replace(/\.$/, '').replace(/\?$/, '');
              })()}
            </button>
          )}

          {/* Artist line */}
          <div>
            <p className="text-sm font-medium text-ink italic leading-snug">
              {GROUP_ARTIST_LINE[activeGroup]}
            </p>
          </div>

          {/* Group fields */}
          <div>{renderActiveGroup()}</div>

          {/* Required fields warning (Q1 only, after submit attempt) */}
          {activeGroup === 0 && triedSubmit && !canProceed && (
            <p className="text-xs text-amber-400/90">
              Style, Gender, and Age Range are required.
            </p>
          )}

          {/* Group advance / finish */}
          <div className="flex justify-end pt-1">
            {activeGroup < 5 ? (
              <button
                type="button"
                onClick={advance}
                className="flex items-center gap-1 text-xs text-ink-3 hover:text-ink transition-colors"
              >
                {GROUP_ARTIST_LINE[(activeGroup + 1) as GroupId]}
                <ChevronRight className="w-3.5 h-3.5 shrink-0" />
              </button>
            ) : (
              /* Final group hint */
              triedSubmit && !canProceed ? (
                <p className="text-xs text-amber-400/90 text-right">
                  Go back to Q1 — style, gender and age are required.
                </p>
              ) : null
            )}
          </div>
        </div>
      </div>

      {/* Bottom navigation */}
      <div className="flex justify-between pt-2 border-t border-edge">
        <button className="btn btn-secondary" onClick={onBack}>
          Back
        </button>
        <button
          className="btn btn-primary"
          onClick={handleContinue}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Continue to Sketch'}
        </button>
      </div>
    </div>
  );
}
