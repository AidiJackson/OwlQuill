import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Feather } from 'lucide-react';
import { apiClient } from '@/lib/apiClient';

import StepBasics from './steps/StepBasics';
import StepPersonality from './steps/StepPersonality';
import StepSketch from './steps/StepSketch';
import StepGeneratePack from './steps/StepGeneratePack';
import StepSelect from './steps/StepSelect';
import StepDossierLock from './steps/StepDossierLock';

import ErrorBoundary from '@/components/ErrorBoundary';
import { upsertDNA } from './shared/api';
import { checkCreationSession } from './shared/sessionGuard';
import type {
  CreationBasics,
  CreationSeeds,
  V2PackResponse,
  BodyMorphology,
} from './shared/types';
import { STEP_LABELS, DEFAULT_BODY_MORPHOLOGY } from './shared/types';

export default function CharacterCreationFlow() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [step, setStep] = useState(0);
  const [characterId, setCharacterId] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loadingDraft, setLoadingDraft] = useState(() => !!searchParams.get('characterId'));

  const [basics, setBasics] = useState<CreationBasics>({
    name: '',
    age: '',
    species: '',
    gender_presentation: '',
  });

  const [seeds, setSeeds] = useState<CreationSeeds>({
    traits: [],
    vibeText: '',
    identitySpec: null,
  });

  const [bodyMorphology, setBodyMorphology] = useState<BodyMorphology>(DEFAULT_BODY_MORPHOLOGY);

  const [_sketchImageId, setSketchImageId] = useState<number | null>(null);
  const [generatedPack, setGeneratedPack] = useState<V2PackResponse | null>(null);
  const [selectedImageIndex, setSelectedImageIndex] = useState(0);

  // ── B15.6: bfcache / mobile restore session hardening ───────────────
  // sketchSessionNonce: incremented on bfcache restore so StepSketch remounts
  // with clean state, preventing a stale sketch from surviving a back/fwd restore.
  const [sketchSessionNonce, setSketchSessionNonce] = useState(0);
  const [pageshowPersisted, setPageshowPersisted] = useState(false);
  const [sessionRecoveryAction, setSessionRecoveryAction] = useState('');

  // Refs give the pageshow handler access to current step/characterId without
  // stale-closure issues (handler is registered once, deps array is []).
  const stepRef = useRef(step);
  const characterIdRef = useRef(characterId);
  useEffect(() => { stepRef.current = step; }, [step]);
  useEffect(() => { characterIdRef.current = characterId; }, [characterId]);

  // The "route characterId" is the characterId present in the URL query string.
  // On a normal resume it matches stateCharacterId; on bfcache-restore after
  // navigating away it may differ, which is the key mismatch we guard against.
  const routeCharacterIdRaw = searchParams.get('characterId');
  const routeCharacterId = routeCharacterIdRaw
    ? (Number.isNaN(Number(routeCharacterIdRaw)) ? null : Number(routeCharacterIdRaw))
    : null;

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

      setPageshowPersisted(true);
      setSessionRecoveryAction(result.recoveryAction);

      if (result.recoveryAction === 'bfcache-mismatch:reset-to-step-0') {
        // Route and state ids diverge — recover to a safe starting point.
        setCharacterId(null);
        setStep(0);
        setSketchImageId(null);
        return;
      }

      if (result.recoveryAction === 'bfcache-restore:sketch-cleared') {
        // Same ids but bfcache restored the sketch step — clear stale sketch.
        setSketchImageId(null);
        setSketchSessionNonce((n) => n + 1);
      }
    };

    window.addEventListener('pageshow', handlePageshow);
    return () => window.removeEventListener('pageshow', handlePageshow);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Load existing draft when characterId query param is present
  useEffect(() => {
    const resumeId = searchParams.get('characterId');
    if (!resumeId) return;
    const id = Number(resumeId);
    if (isNaN(id)) {
      setLoadingDraft(false);
      return;
    }
    apiClient
      .getCharacter(id)
      .then((char) => {
        setCharacterId(char.id);
        setBasics({
          name: char.name || '',
          age: char.age || '',
          species: char.species || '',
          gender_presentation: '',
        });
      })
      .catch(() => {
        setError('Failed to load draft character.');
      })
      .finally(() => {
        setLoadingDraft(false);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Transition: Personality → Sketch (create character + upsert DNA)
  const handleAfterPersonality = async () => {
    setSaving(true);
    setError('');
    try {
      let cid = characterId;

      // Create character if not yet created
      if (!cid) {
        const character = await apiClient.createCharacter({
          name: basics.name,
          age: basics.age || undefined,
          species: basics.species || undefined,
        });
        cid = character.id;
        setCharacterId(cid);
      } else {
        // Update basics if character already exists
        await apiClient.updateCharacter(cid, {
          name: basics.name,
          age: basics.age || undefined,
          species: basics.species || undefined,
        });
      }

      // Upsert DNA
      await upsertDNA(cid, {
        species: basics.species || undefined,
        gender_presentation: basics.gender_presentation || undefined,
        visual_traits_json: {
          personality_traits: seeds.traits,
          vibe: seeds.vibeText,
          identity_spec: seeds.identitySpec || undefined,
        },
        structural_profile_json: {
          age_band: basics.age || undefined,
        },
      });

      setStep(2);
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
        {step === 0 && (
          <StepBasics
            data={basics}
            onChange={setBasics}
            onNext={() => setStep(1)}
          />
        )}

        {step === 1 && (
          <StepPersonality
            data={seeds}
            onChange={setSeeds}
            onNext={handleAfterPersonality}
            onBack={() => setStep(0)}
            saving={saving}
          />
        )}

        {step === 2 && characterId && (
          <StepSketch
            key={`${characterId}-${sketchSessionNonce}`}
            characterId={characterId}
            identitySpec={seeds.identitySpec}
            basics={basics}
            activeCreationCharacterId={characterId}
            routeCharacterId={routeCharacterId}
            pageshowPersisted={pageshowPersisted}
            sessionRecoveryAction={sessionRecoveryAction}
            onConfirmed={(id) => {
              setSketchImageId(id || null);
              setStep(3);
            }}
            onBack={() => setStep(1)}
          />
        )}

        {step === 3 && characterId && (
          <StepGeneratePack
            characterId={characterId}
            vibeText={seeds.vibeText}
            identitySpec={seeds.identitySpec}
            bodyMorphology={bodyMorphology}
            onBodyMorphologyChange={setBodyMorphology}
            pack={generatedPack}
            onPackGenerated={(pack) => {
              setGeneratedPack(pack);
              setSelectedImageIndex(0);
            }}
            onNext={() => setStep(4)}
            onBack={() => setStep(2)}
          />
        )}

        {step === 4 && generatedPack && (
          <StepSelect
            pack={generatedPack}
            selectedIndex={selectedImageIndex}
            onSelect={setSelectedImageIndex}
            onNext={() => setStep(5)}
            onBack={() => setStep(3)}
          />
        )}

        {step === 5 && characterId && generatedPack && (
          <StepDossierLock
            characterId={characterId}
            pack={generatedPack}
            selectedIndex={selectedImageIndex}
            basics={basics}
          />
        )}
        </ErrorBoundary>
      </div>
    </div>
  );
}
