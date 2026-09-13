// The Interview — one question group at a time, with the artist's sketch pad
// building alongside on wider screens.
//
// Polish Phase 1. This file is the step SHELL: layout, group progress,
// navigation, required-field feedback and the hand-off to the flow. The
// questions themselves live in interviewGroups.tsx.
//
// Decisions recorded here:
//   * Name and alias open the Interview (C8) — the separate Basics screen was
//     a single input with a Next button once its duplicate age/species/gender
//     fields were removed, so it was folded into group 1, whose artist line
//     already said "Let's start with the basics."
//   * The sketch pad is ambient (C15): larger on tablet/desktop, hidden on
//     phones, never a control (C3).
//   * Progress is visible (C11): six dots and "n of 6"; Next/Back are real
//     buttons; the three required answers are marked before anyone reaches
//     the end and is told.
import { useState, useCallback } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { CreationBasics, CreationSeeds, IdentitySpec } from '../shared/types';
import { isInterviewComplete } from '../shared/interviewRules';
import SketchFacePreview from '../components/SketchFacePreview';
import NotesStrip from '../components/NotesStrip';
import { GROUPS, GROUP_COMPONENTS, GROUP_COUNT, type GroupId } from './interviewGroups';
import { useExampleSet } from '../visualRefs/useExampleSet';

/* ── Empty spec ─────────────────────────────────────────────────────── */
//
// Fields that no control writes any more (style, marks_accessories,
// wardrobe, extra_notes, build, face_features) stay in the shape so a stored
// character still validates and the backend's coercions (style '' →
// "realistic") keep applying. See interviewGroups.tsx for what is asked.

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
  hair_texture: undefined,
  hair_style: undefined,
  eyebrow_shape: undefined,
};

function normaliseSpec(incoming: Partial<IdentitySpec> | null | undefined): IdentitySpec {
  if (!incoming) return EMPTY_SPEC;
  return {
    ...EMPTY_SPEC,
    ...incoming,
    identity: { ...EMPTY_SPEC.identity, ...(incoming.identity ?? {}) },
    species_tells: incoming.species_tells ?? [],
  };
}

// ── Main component ─────────────────────────────────────────────────────

interface Props {
  basics: CreationBasics;
  onBasicsChange: (b: CreationBasics) => void;
  data: CreationSeeds;
  onChange: (data: CreationSeeds) => void;
  onNext: () => void;
  saving: boolean;
}

export default function StepPersonality({
  basics,
  onBasicsChange,
  data,
  onChange,
  onNext,
  saving,
}: Props) {
  // A stored spec (resume) may predate a field or carry ``identity: null`` —
  // the backend schema allows it — so it is laid over EMPTY_SPEC rather than
  // used as-is, and every group can read ``spec.identity.*`` safely.
  const [spec, setSpec] = useState<IdentitySpec>(() => normaliseSpec(data.identitySpec));
  const [activeGroup, setActiveGroup] = useState<GroupId>(0);
  const [triedSubmit, setTriedSubmit] = useState(false);
  // Which explanatory example images the picture-card fields show (Phase 3A).
  // A viewing preference: suggested by the chosen gender, overridable, never
  // part of the spec.
  const { exampleSet, setExampleSet } = useExampleSet(spec.gender);

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

  const nameOk = basics.name.trim().length > 0;
  const canProceed = !saving && nameOk && isInterviewComplete(spec);
  const isLast = activeGroup === GROUP_COUNT - 1;

  const handleContinue = () => {
    if (!canProceed) {
      setTriedSubmit(true);
      setActiveGroup(0);
      return;
    }
    onNext();
  };

  const advance = () => {
    if (!isLast) setActiveGroup((activeGroup + 1) as GroupId);
  };

  const retreat = () => {
    if (activeGroup > 0) setActiveGroup((activeGroup - 1) as GroupId);
  };

  const Group = GROUP_COMPONENTS[activeGroup];
  const group = GROUPS[activeGroup];

  return (
    <div className="space-y-5">
      {/* Step header */}
      <div className="text-center space-y-0.5">
        <h2 className="text-xl font-semibold text-ink">Interview</h2>
        <p className="text-xs text-ink-3">The artist is listening.</p>
      </div>

      {/* Group progress — six dots and a count (C11) */}
      <div className="flex items-center justify-center gap-3" aria-label={`Question group ${activeGroup + 1} of ${GROUP_COUNT}: ${group.name}`}>
        <div className="flex items-center gap-1.5" aria-hidden="true">
          {GROUPS.map((g) => (
            <span
              key={g.id}
              className={`h-1.5 rounded-full transition-all ${
                g.id === activeGroup ? 'w-5 bg-gem' : g.id < activeGroup ? 'w-1.5 bg-gem/50' : 'w-1.5 bg-surface-overlay'
              }`}
            />
          ))}
        </div>
        <span className="text-xs text-ink-3">
          {activeGroup + 1} of {GROUP_COUNT} · {group.name}
        </span>
      </div>

      {/* Sketch pad (tablet/desktop only) + the active group */}
      <div className="flex flex-col sm:flex-row gap-5 items-start">
        <div className="hidden sm:flex shrink-0 flex-col">
          <SketchFacePreview spec={spec} width={200} />
          <NotesStrip spec={spec} width={200} />
        </div>

        <div className="flex-1 min-w-0 w-full flex flex-col gap-4">
          <p className="text-sm font-medium text-ink italic leading-snug">{group.line}</p>

          <Group
            spec={spec}
            propagate={propagate}
            set={set}
            setIdentity={setIdentity}
            basics={basics}
            onBasicsChange={onBasicsChange}
            traits={data.traits}
            toggleTrait={toggleTrait}
            showMissing={triedSubmit}
            exampleSet={exampleSet}
            onExampleSetChange={setExampleSet}
          />

          {triedSubmit && !canProceed && !saving && (
            <p className="text-xs text-amber-400/90" role="alert">
              Name, gender and age range are needed before the artist can sketch.
            </p>
          )}

          {/* Group navigation — real buttons, both directions */}
          <div className="flex items-center justify-between gap-2 pt-1">
            <button
              type="button"
              onClick={retreat}
              disabled={activeGroup === 0}
              className="btn btn-secondary text-sm inline-flex items-center gap-1 disabled:opacity-40"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              Back
            </button>
            {!isLast ? (
              <button
                type="button"
                onClick={advance}
                className="btn btn-secondary text-sm inline-flex items-center gap-1"
              >
                Next
                <ChevronRight className="w-3.5 h-3.5" />
              </button>
            ) : (
              <span className="text-xs text-ink-3">Last question</span>
            )}
          </div>
        </div>
      </div>

      {/* Finish the Interview */}
      <div className="flex justify-end pt-2 border-t border-edge">
        <button
          type="button"
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
