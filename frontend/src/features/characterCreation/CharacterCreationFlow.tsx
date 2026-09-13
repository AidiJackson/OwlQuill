import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Feather } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

import StepPersonality from './steps/StepPersonality';
import StepSketch from './steps/StepSketch';
import StepGeneratePack from './steps/StepGeneratePack';
import StepSelect from './steps/StepSelect';
import StepDossierLock from './steps/StepDossierLock';

import ErrorBoundary from '@/components/ErrorBoundary';
import { getDNA, upsertDNA } from './shared/api';
import { checkCreationSession } from './shared/sessionGuard';
import { characterFieldsFromSpec, isInterviewComplete } from './shared/interviewRules';
import type {
  CreationBasics,
  CreationSeeds,
  IdentitySpec,
  V2PackResponse,
  BodyMorphology,
} from './shared/types';
import {
  STEP_LABELS,
  STEP_INTERVIEW,
  STEP_SKETCH,
  STEP_PACK,
  STEP_SELECT,
  STEP_DOSSIER,
  DEFAULT_BODY_MORPHOLOGY,
} from './shared/types';

export default function CharacterCreationFlow() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [step, setStep] = useState(STEP_INTERVIEW);
  const [characterId, setCharacterId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loadingDraft, setLoadingDraft] = useState(() => !!searchParams.get('characterId'));

  const [basics, setBasics] = useState<CreationBasics>({ name: '', alias: '' });

  const [seeds, setSeeds] = useState<CreationSeeds>({
    traits: [],
    identitySpec: null,
  });

  const [bodyMorphology, setBodyMorphology] = useState<BodyMorphology>(DEFAULT_BODY_MORPHOLOGY);

  // Polish Phase 1: the accepted sketch's image id used to be kept here and
  // read by nothing — the sketch is a preview and does not seed the pack
  // (product decision P1). Removed rather than carried.
  const [generatedPack, setGeneratedPack] = useState<V2PackResponse | null>(null);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);

  // ── B15.6: bfcache / mobile restore session hardening ───────────────
  // sketchSessionNonce: incremented on bfcache restore so StepSketch remounts
  // with clean state, preventing a stale sketch from surviving a back/fwd restore.
  const [sketchSessionNonce, setSketchSessionNonce] = useState(0);

  // Refs give the pageshow handler access to current step/characterId without
  // stale-closure issues (handler is registered once, deps array is []).
  const stepRef = useRef(step);
  const characterIdRef = useRef(characterId);
  useEffect(() => { stepRef.current = step; }, [step]);
  useEffect(() => { characterIdRef.current = characterId; }, [characterId]);

  // The "route characterId" (the ?characterId query param) is compared with
  // the state id inside the pageshow guard below, read from the live URL at
  // event time so the comparison cannot go stale.

  // ── B15.6: pageshow guard — fires on every page navigation including bfcache
  useEffect(() => {
    const handlePageshow = (evt: PageTransitionEvent) => {
      const currentStep = stepRef.current;
      const currentCharId = characterIdRef.current;

      // Recompute route id at event time from the live URL (avoids closure staleness).
      const rawRouteId = new URLSearchParams(window.location.search).get('characterId');
      const currentRouteId = rawRouteId
        ? (Number.isNaN(Number(rawRouteId)) ? null : Number(rawRouteId))
        : null;

      const result = checkCreationSession({
        persisted: evt.persisted,
        stateCharacterId: currentCharId,
        routeCharacterId: currentRouteId,
        step: currentStep,
      });

      if (result.recoveryAction === 'none') return;

      if (import.meta.env.DEV) {
        console.info('[CreationSession] pageshow guard fired', {
          persisted: evt.persisted,
          step: currentStep,
          stateCharacterId: currentCharId,
          routeCharacterId: currentRouteId,
          mismatch: result.mismatch,
          recoveryAction: result.recoveryAction,
        });
      }

      if (result.recoveryAction === 'bfcache-mismatch:reset-to-step-0') {
        // Route and state ids diverge — recover to a safe starting point.
        setCharacterId(null);
        setStep(STEP_INTERVIEW);
        return;
      }

      if (result.recoveryAction === 'bfcache-restore:sketch-cleared') {
        // Same ids but bfcache restored the sketch step — clear stale sketch.
        setSketchSessionNonce((n) => n + 1);
      }
    };

    window.addEventListener('pageshow', handlePageshow);
    return () => window.removeEventListener('pageshow', handlePageshow);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Resume a draft when ?characterId is present (Polish Phase 1, C2)
  //
  // The Character row gives the name and alias; the DNA row gives the whole
  // Interview (identity_spec + personality_traits), which the wizard writes
  // on "Continue to Sketch" and could never read back before. Resume opens at
  // the furthest step the persisted state honestly supports:
  //   * a complete Interview (gender + age band answered) → Sketch;
  //   * a stored but incomplete Interview, or none → Interview, with whatever
  //     was stored filled in and nothing invented.
  useEffect(() => {
    const resumeId = searchParams.get('characterId');
    if (!resumeId) return;
    const id = Number(resumeId);
    if (isNaN(id)) {
      setLoadingDraft(false);
      return;
    }
    Promise.all([apiClient.getCharacter(id), getDNA(id)])
      .then(([char, dna]) => {
        setCharacterId(char.id);
        setBasics({ name: char.name || '', alias: char.alias || '' });
        const traits = dna?.visual_traits_json?.personality_traits;
        const spec = dna?.visual_traits_json?.identity_spec as IdentitySpec | undefined;
        if (spec) {
          setSeeds({
            traits: Array.isArray(traits) ? (traits as string[]) : [],
            identitySpec: spec,
          });
          if (isInterviewComplete(spec)) setStep(STEP_SKETCH);
        }
      })
      .catch(() => {
        setError('Failed to load draft character.');
      })
      .finally(() => {
        setLoadingDraft(false);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Transition: Interview → Sketch (create/update character + upsert DNA)
  //
  // Polish Phase 1 (C8): the Interview is the single truth. The Character
  // row's display fields (species label, age band) and the DNA's
  // species/gender are all written from the same spec, so they cannot
  // disagree. Name and alias come from the Interview's opening group.
  const handleAfterPersonality = async () => {
    setSaving(true);
    setError('');
    try {
      const spec = seeds.identitySpec;
      const display = spec ? characterFieldsFromSpec(spec) : {};
      const fields = {
        name: basics.name.trim(),
        alias: basics.alias.trim() || undefined,
        ...display,
      };
      let cid = characterId;
      if (!cid) {
        const character = await apiClient.createCharacter(fields);
        cid = character.id;
        setCharacterId(cid);
      } else {
        await apiClient.updateCharacter(cid, fields);
      }
      await upsertDNA(cid, {
        species: spec?.species || undefined,
        gender_presentation: spec?.gender || undefined,
        visual_traits_json: {
          personality_traits: seeds.traits,
          identity_spec: spec || undefined,
        },
        structural_profile_json: {
          age_band: spec?.age_band || undefined,
        },
      });
      setStep(STEP_SKETCH);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save character data.');
    } finally {
      setSaving(false);
    }
  };

  if (loadingDraft) {
    return (
      <div className="min-h-screen flex items-center justify-center text-ink-2">
        Loading draft…
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <div className="border-b border-edge bg-surface">
        <div className="max-w-xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-ink-2">
            <Feather className="w-5 h-5 text-gem" />
            <span className="text-sm font-medium">New Character</span>
          </div>
          <button
            className="text-xs text-ink-3 hover:text-ink-2 transition-colors"
            onClick={() => navigate('/characters')}
          >
            Cancel
          </button>
        </div>
      </div>

      {/* Step indicator */}
      <div className="max-w-xl mx-auto w-full px-4 pt-6 pb-2">
        <div className="flex items-center justify-center gap-1">
          {STEP_LABELS.map((label, i) => (
            <div key={label} className="flex items-center">
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                  i === step
                    ? 'bg-gem text-gem-ink'
                    : i < step
                      ? 'bg-gem-soft text-gem'
                      : 'bg-surface-elevated text-ink-3'
                }`}
              >
                {i + 1}
              </div>
              {i < STEP_LABELS.length - 1 && (
                <div
                  className={`w-6 sm:w-10 h-0.5 transition-colors ${
                    i < step ? 'bg-gem' : 'bg-surface-elevated'
                  }`}
                />
              )}
            </div>
          ))}
        </div>
        <div className="text-center mt-1">
          <span className="text-xs text-ink-3">
            Step {step + 1}: {STEP_LABELS[step]}
          </span>
        </div>
      </div>

      {/* Global error */}
      {error && (
        <div className="max-w-xl mx-auto w-full px-4 pt-2">
          <p className="text-sm text-amber-400/90 bg-amber-400/10 rounded-lg px-4 py-2 text-center">
            {error}
          </p>
        </div>
      )}

      {/* Step content */}
      <div className="flex-1 max-w-xl mx-auto w-full px-4 py-6">
        <ErrorBoundary fallback={<p className="text-center text-sm text-ink-2 py-8">Something went wrong. Please refresh and try again.</p>}>
        {step === STEP_INTERVIEW && (
          <StepPersonality
            basics={basics}
            onBasicsChange={setBasics}
            data={seeds}
            onChange={setSeeds}
            onNext={handleAfterPersonality}
            saving={saving}
          />
        )}

        {step === STEP_SKETCH && characterId && (
          <StepSketch
            key={`${characterId}-${sketchSessionNonce}`}
            characterId={characterId}
            identitySpec={seeds.identitySpec}
            activeCreationCharacterId={characterId}
            onConfirmed={() => setStep(STEP_PACK)}
            onBack={() => setStep(STEP_INTERVIEW)}
          />
        )}

        {step === STEP_PACK && characterId && (
          <StepGeneratePack
            characterId={characterId}
            identitySpec={seeds.identitySpec}
            bodyMorphology={bodyMorphology}
            onBodyMorphologyChange={setBodyMorphology}
            pack={generatedPack}
            onPackGenerated={(pack) => {
              setGeneratedPack(pack);
              setSelectedImageIndex(0);
            }}
            onNext={() => setStep(STEP_SELECT)}
            onBack={() => setStep(STEP_SKETCH)}
          />
        )}

        {step === STEP_SELECT && generatedPack && (
          <StepSelect
            pack={generatedPack}
            selectedIndex={selectedImageIndex}
            onSelect={setSelectedImageIndex}
            onNext={() => setStep(STEP_DOSSIER)}
            onBack={() => setStep(STEP_PACK)}
          />
        )}

        {step === STEP_DOSSIER && characterId && generatedPack && (
          <StepDossierLock
            characterId={characterId}
            pack={generatedPack}
            selectedIndex={selectedImageIndex}
            basics={basics}
            species={seeds.identitySpec ? characterFieldsFromSpec(seeds.identitySpec).species : undefined}
          />
        )}
        </ErrorBoundary>
      </div>
    </div>
  );
}
